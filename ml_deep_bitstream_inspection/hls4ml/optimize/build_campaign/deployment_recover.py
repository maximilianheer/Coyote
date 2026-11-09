#!/usr/bin/env python3
"""Recover physical timing in a fresh attempt without changing source or clocks."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import time

from implementation_permits import permit
from prepare import HERE, sha
from worker import collect_artifacts, final_timing_reports, save
from hbm_clock import verify_report_application_clock, verify_report_hbm_clock
from network_timing import verify_report_user_clock


def run(original, output, strategy=1):
    output.mkdir(parents=True, exist_ok=False)
    config = json.loads((original / 'config.json').read_text())
    config['recovery_of'] = str(original)
    config['recovery_strategy'] = strategy
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
        # A placement retry starts from the optimized, unplaced checkpoint.
        # Reusing a placed checkpoint would preserve the placement we want to
        # reconsider. Forced replication must also run before routing in 2024.2.
        if strategy == 3:
            seed_name = 'shell_opted.dcp'
        elif strategy in (2, 5, 6):
            seed_name = 'shell_placed.dcp'
        else:
            seed_name = 'shell_routed.dcp'
        seed = build / 'checkpoints' / seed_name
        shutil.copy2(report, output / 'original_timing_summary.rpt')
        script = output / 'recover.tcl'
        template = HERE / 'implementation/recover_timing.tcl'
        script.write_text(template.read_text().replace('general.maxThreads 8', 'general.maxThreads 4'))
        paths = []
        for block in re.split(r'(?=Slack \()', text):
            if not block.startswith('Slack (VIOLATED)'):
                continue
            details = {}
            for field in ['Source', 'Destination', 'Path Group']:
                match = re.search(r'(?m)^\s*' + field + r':\s*(\S+)', block)
                if match:
                    details[field] = match.group(1)
            match = re.match(r'Slack \(VIOLATED\)\s*:\s*([-0-9.]+)ns', block)
            if match:
                details['slack_ns'] = float(match.group(1))
            paths.append(details)
        save(output / 'provenance.json', {
            'original': str(original), 'source_manifest_sha256': sha(original / 'source_hashes.json'),
            'seed': str(seed), 'seed_sha256': sha(seed), 'script_sha256': sha(script),
            'failing_report_sha256': sha(report), 'strategy': strategy,
            'clock_constraints_changed': False, 'firmware_changed': False,
            'diagnosis': 'Post-route setup violations; target high-fanout routing with unchanged clocks',
            'failing_paths': paths, 'worker_sha256': sha(Path(__file__)),
        })
        environment = os.environ.copy()
        environment['PATH'] = '/tools/Xilinx/Vivado/2024.2/bin:' + environment['PATH']

        def command(stage, arguments):
            progress(stage=stage, stage_started_at=time.time())
            with (output / (stage + '.log')).open('w') as log:
                process = subprocess.Popen(arguments, cwd=output, env=environment,
                                           stdout=log, stderr=subprocess.STDOUT,
                                           start_new_session=True)
                progress(child_pid=process.pid)
                try:
                    code = process.wait(timeout=24 * 60 * 60)
                except subprocess.TimeoutExpired:
                    # Limit termination to this attempt's tool process group.
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=30)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait()
                    raise RuntimeError(f'{stage} exceeded the 24-hour watchdog')
            if code:
                raise RuntimeError(f'{stage} exited {code}; see {stage}.log')

        with permit(progress):
            command('timing_recovery', [
                'vivado', '-mode', 'batch', '-source', str(script),
                '-tclargs', str(build / 'base.tcl'), str(output), str(seed), str(strategy),
            ])
            final_timing_reports(output, config['id'])
            routed_report = output / 'reports/shell_timing_summary.rpt'
            application_mhz = config.get('clock_hz', 250000000) / 1e6
            verify_report_application_clock(routed_report, application_mhz)
            verify_report_hbm_clock(routed_report, config.get('hbm_axi_mhz', 450))
            verify_report_user_clock(
                routed_report, config.get('user_clock_hz', 250000000) / 1e6
            )
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
    parser.add_argument('--strategy', type=int, choices=[1, 2, 3, 5, 6], default=1)
    arguments = parser.parse_args()
    with (arguments.original / f'recovery_strategy_{arguments.strategy}.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        raise SystemExit(run(arguments.original.resolve(), arguments.output.resolve(), arguments.strategy))
