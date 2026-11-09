#!/usr/bin/env python3
"""Validate and continue an isolated reader build under shared permits."""

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import shutil
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from implementation_permits import permit
from hbm_clock import verify_report_application_clock, verify_report_hbm_clock


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def save(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.replace(path)


def run(root):
    config = json.loads((root / 'config.json').read_text())
    state = {
        'id': config['id'], 'pid': os.getpid(), 'status': 'running',
        'stage': 'recovery_preflight', 'started_at': time.time(),
        'process_marker': 'readers_recovery_worker.py', 'hardware_validated': False,
    }
    environment = dict(os.environ)
    environment['OMP_NUM_THREADS'] = '4'
    environment['PATH'] = '/tools/Xilinx/Vivado/2024.2/bin:' + environment['PATH']
    environment['TMPDIR'] = str(root / 'tmp')
    (root / 'tmp').mkdir(exist_ok=True)
    vivado = '/tools/Xilinx/Vivado/2024.2/bin/vivado'

    def progress(**values):
        state.update(values)
        save(root / 'status.json', state)

    def command(stage, arguments, directory):
        progress(stage=stage, stage_started_at=time.time(), child_pid=None)
        with (root / f'{stage}.log').open('x') as output:
            child = subprocess.Popen(arguments, cwd=directory, env=environment,
                                     stdout=output, stderr=subprocess.STDOUT,
                                     start_new_session=True)
            progress(child_pid=child.pid)
            try:
                result = child.wait(timeout=86400)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGTERM)
                try:
                    child.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.wait()
                raise RuntimeError(f'{stage}: 24-hour stage watchdog expired')
        if result != 0:
            raise RuntimeError(f'{stage} exited {result}; see {stage}.log')

    progress()
    try:
        manifest = json.loads((root / 'recovery_manifest.json').read_text())
        assert manifest['application_mhz'] == 250 and manifest['hbm_mhz'] == 450
        sources = json.loads((root / 'source_hashes.json').read_text())
        for relative, expected in sources.items():
            if sha(root / relative) != expected:
                raise RuntimeError(f'Sealed source changed: {relative}')
        cache = manifest.get('validation_cache')
        if cache:
            cached_root = Path(cache['root'])
            if sha(cached_root / 'validation.json') != cache['result_sha256']:
                raise RuntimeError('Cached validation result changed')
            if json.loads((cached_root / 'source_hashes.json').read_text()) != sources:
                raise RuntimeError('Cached validation source manifest changed')
            for relative, expected in cache['identities'].items():
                if sha(root / relative) != expected or sha(cached_root / relative) != expected:
                    raise RuntimeError(f'Cached validation input changed: {relative}')
            pin = json.loads((root / 'model_clock_pin.json').read_text())
            assert sha(Path(pin['weights'])) == pin['weights_sha256']
            assert sha(Path(pin['cpu_reference_library']['path'])) == pin['cpu_reference_library']['sha256']
            assert json.loads((cached_root / 'validation.json').read_text())['status'] == 'passed'
            shutil.copy2(cached_root / 'validation.json', root / 'validation.json')
            save(root / 'validation_reuse.json', cache)
        else:
            command('validate', [sys.executable, str(root / 'tooling/validate.py'), str(root)], root)
        command('project_probe', [vivado, '-mode', 'batch', '-source',
                                 str(root / 'recovery_project_probe.tcl'), '-notrace'], root)
        if 'RECOVERY_PROJECT_VALIDATION_PASSED' not in (root / 'project_probe.log').read_text():
            raise RuntimeError('Migrated project validation did not complete')
        save(root / 'recovery_validation.json', {
            'status': 'passed', 'at': time.time(),
            'source_manifest_sha256': sha(root / 'source_hashes.json'),
            'validation_sha256': sha(root / 'validation.json'),
            'project_probe_sha256': sha(root / 'project_probe.log'),
            'vivado_version': '2024.2', 'configure_or_project_repeated': False,
        })
        with permit(progress):
            progress(implementation_started_at=time.time())
            for stage, script in [
                ('synth_shell', 'synth_shell.tcl'), ('synth_user', 'synth_user.tcl'),
                ('link', 'link.tcl'), ('shell', 'pnr_shell.tcl'),
                ('bitgen', 'bitgen.tcl'),
            ]:
                if stage == 'bitgen':
                    report = root / 'build/reports/shell_timing_summary.rpt'
                    contents = report.read_text()
                    if 'All user specified timing constraints are met.' not in contents:
                        raise RuntimeError('Routed timing failed; bitstream generation withheld')
                    verify_report_application_clock(report, 250)
                    verify_report_hbm_clock(report, 450)
                command(stage, [vivado, '-mode', 'batch', '-source',
                                str(root / 'build' / script), '-notrace'], root / 'build')
            command('verify', [sys.executable, str(root / 'tooling/verify.py'), str(root)], root)
            result = json.loads((root / 'verification.json').read_text())
            if result['status'] != 'passed':
                raise RuntimeError('Final build acceptance failed')
            artifacts = list((root / 'build/bitstreams').glob('*'))
            artifacts += [root / 'verification.json', root / 'validation.json',
                          root / 'source_hashes.json', root / 'recovery_manifest.json']
            artifacts += list((root / 'build/reports').glob('*.rpt'))
            save(root / 'artifacts.json', {
                'files': {str(path.relative_to(root)): sha(path)
                          for path in artifacts if path.is_file()},
                'hardware_validated': False,
            })
            progress(status='passed', stage='complete', finished_at=time.time())
        return 0
    except Exception as error:
        progress(status='failed', error=str(error), finished_at=time.time())
        return 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('root', type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    with (root / 'worker.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        raise SystemExit(run(root))
