#!/usr/bin/env python3
"""Recover physical timing in a fresh attempt without changing source or clocks."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time

from implementation_permits import permit
from prepare import HERE, sha
from worker import collect_artifacts, final_timing_reports, save


def run(original, output):
    output.mkdir(parents=True, exist_ok=False)
    config = json.loads((original / 'config.json').read_text())
    config['recovery_of'] = str(original)
    config['recovery_strategy'] = 'same-clock AggressiveFanoutOpt and NoTimingRelaxation'
    save(output / 'config.json', config)
    state = {
        'id': config['id'], 'pid': os.getpid(), 'status': 'running',
        'stage': 'verify', 'started_at': time.time(),
        'process_marker': 'deployment_recover.py', 'hardware_validated': False,
    }

    def progress(**values):
        state.update(values)
        save(output / 'status.json', state)

    progress()
    try:
        inputs = json.loads((original / 'source_hashes.json').read_text())
        for name, expected in inputs.items():
            if sha(original / name) != expected:
                raise RuntimeError('Changed original source: ' + name)
        build = original / 'build'
        report = build / 'reports/shell_timing_summary.rpt'
        text = report.read_text()
        if 'Timing constraints are not met.' not in text:
            raise RuntimeError('Physical recovery requires a completed failing timing report')
        seed = build / 'checkpoints/shell_routed.dcp'
        shutil.copy2(report, output / 'original_timing_summary.rpt')
        script = output / 'recover.tcl'
        template = HERE / 'implementation/recover_timing.tcl'
        script.write_text(template.read_text().replace('general.maxThreads 8', 'general.maxThreads 4'))
        save(output / 'provenance.json', {
            'original': str(original), 'source_manifest_sha256': sha(original / 'source_hashes.json'),
            'seed': str(seed), 'seed_sha256': sha(seed), 'script_sha256': sha(script),
            'failing_report_sha256': sha(report), 'strategy': 1,
            'clock_constraints_changed': False, 'firmware_changed': False,
            'diagnosis': '450MHz HBM width-converter to register-slice high-fanout setup path',
        })
        environment = os.environ.copy()
        environment['PATH'] = '/tools/Xilinx/Vivado/2024.2/bin:' + environment['PATH']

        def command(stage, arguments):
            progress(stage=stage, stage_started_at=time.time())
            with (output / (stage + '.log')).open('w') as log:
                process = subprocess.Popen(arguments, cwd=output, env=environment,
                                           stdout=log, stderr=subprocess.STDOUT)
                progress(child_pid=process.pid)
                code = process.wait()
            if code:
                raise RuntimeError(f'{stage} exited {code}; see {stage}.log')

        with permit(progress):
            command('timing_recovery', [
                'vivado', '-mode', 'batch', '-source', str(script),
                '-tclargs', str(build / 'base.tcl'), str(output), str(seed), '1',
            ])
            final_timing_reports(output, config['id'])
            for name in ['bitstreams', 'logs']:
                (output / name).mkdir(exist_ok=True)
            base = output / 'base.tcl'
            base.write_text(f'source {{{build / "base.tcl"}}}\n' + ''.join(
                f'set {variable} {{{output / folder}}}\n'
                for variable, folder in [('dcp_dir', 'checkpoints'), ('rprt_dir', 'reports'),
                                         ('bit_dir', 'bitstreams'), ('log_dir', 'logs')]
            ))
            bitgen, count = re.subn(r'(?m)^source "[^"\n]+/base\.tcl"$',
                'source {' + str(base) + '}', (build / 'bitgen.tcl').read_text())
            if count != 1:
                raise RuntimeError('Cannot isolate recovery bitgen script')
            (output / 'bitgen.tcl').write_text(bitgen)
            command('bitgen', ['vivado', '-mode', 'batch', '-source', str(output / 'bitgen.tcl')])
        for name, expected in inputs.items():
            if sha(original / name) != expected:
                raise RuntimeError('Original source changed during recovery: ' + name)
        artifacts = collect_artifacts(output, config['id'])
        save(output / 'artifacts.json', {
            'files': {str(Path(name).relative_to(output)): sha(name)
                      for category in artifacts.values() if isinstance(category, list)
                      for name in category}, 'hardware_validated': False,
        })
        progress(status='passed', stage='complete', finished_at=time.time())
        return 0
    except Exception as error:
        progress(status='failed', error=str(error), finished_at=time.time())
        return 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('original', type=Path)
    parser.add_argument('output', type=Path)
    arguments = parser.parse_args()
    with (arguments.original / 'recovery.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        raise SystemExit(run(arguments.original.resolve(), arguments.output.resolve()))
