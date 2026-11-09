#!/usr/bin/env python3
"""Finish acceptance and bitgen from a timing-valid routed checkpoint."""

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import time

from implementation_permits import permit
from prepare import sha
from worker import save, final_timing_reports, collect_artifacts
from hbm_clock import verify_report_application_clock, verify_report_hbm_clock
from network_timing import verify_report_user_clock


def run(original, output):
    config = json.loads((output / 'config.json').read_text())
    state = {'id': config['id'], 'pid': os.getpid(), 'status': 'running',
             'stage': 'verify_sources', 'started_at': time.time(),
             'process_marker': 'deployment_finish.py', 'hardware_validated': False}

    def progress(**fields):
        state.update(fields)
        save(output / 'status.json', state)

    def sources():
        for relative, digest in json.loads((original / 'source_hashes.json').read_text()).items():
            if sha(original / relative) != digest or sha(output / relative) != digest:
                raise RuntimeError('Changed source: ' + relative)

    progress()
    try:
        sources()
        final_timing_reports(original / 'build', config['id'])
        build = output / 'build'
        build.mkdir(exist_ok=True)
        shutil.copytree(original / 'build/reports', build / 'reports')
        (build / 'checkpoints').mkdir()
        seed = original / 'build/checkpoints/shell_routed.dcp'
        checkpoint = build / 'checkpoints/shell_routed.dcp'
        shutil.copy2(seed, checkpoint)
        save(output / 'continuation_identity.json', {
            'ancestor': str(original), 'checkpoint_sha256': sha(checkpoint),
            'source_manifest_sha256': sha(original / 'source_hashes.json'),
            'reason': 'Routed timing passed; old verifier rejected merged user-clock name',
            'synthesis_or_routing_repeated': False,
        })
        with permit(progress):
            progress(stage='verify_routed_clocks', stage_started_at=time.time())
            report = build / 'reports/shell_timing_summary.rpt'
            verify_report_application_clock(report, config['clock_hz'] / 1e6)
            verify_report_hbm_clock(report, config['hbm_axi_mhz'])
            verify_report_user_clock(report, config['user_clock_hz'] / 1e6)
            base = build / 'base.tcl'
            base.write_text('source {' + str(original / 'build/base.tcl') + '}\n'
                            + ''.join(f'set {key} {{{build / folder}}}\n' for key, folder in
                                      [('dcp_dir', 'checkpoints'), ('rprt_dir', 'reports'),
                                       ('bit_dir', 'bitstreams'), ('log_dir', 'logs')]))
            script, count = re.subn(r'(?m)^source "[^"\n]+/base\.tcl"$',
                                    'source {' + str(base) + '}',
                                    (original / 'build/bitgen.tcl').read_text())
            if count != 1:
                raise RuntimeError('Cannot isolate bitgen script')
            (build / 'bitgen.tcl').write_text(script)
            (build / 'logs').mkdir(exist_ok=True)
            progress(stage='bitgen', stage_started_at=time.time())
            with (output / 'bitgen.log').open('w') as log:
                child = subprocess.Popen(
                    ['/tools/Xilinx/Vivado/2024.2/bin/vivado', '-mode', 'batch',
                     '-source', str(build / 'bitgen.tcl')], cwd=build,
                    stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                progress(child_pid=child.pid)
                try:
                    code = child.wait(timeout=86400)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.wait()
                    raise RuntimeError('Bitgen exceeded 24-hour watchdog')
            if code:
                raise RuntimeError(f'Bitgen failed: {code}')
        sources()
        if sha(seed) != sha(checkpoint):
            raise RuntimeError('Routed checkpoint changed')
        artifacts = collect_artifacts(build, config['id'])
        files = {str(Path(name).relative_to(output)): sha(name)
                 for values in artifacts.values() if isinstance(values, list)
                 for name in values}
        for name in ['config.json', 'source_hashes.json', 'tool_identity.json',
                     'continuation_identity.json']:
            files[name] = sha(output / name)
        for path in (build / 'reports/user_clock_audit').glob('*'):
            if path.is_file():
                files[str(path.relative_to(output))] = sha(path)
        save(output / 'artifacts.json', {
            'files': files, 'hardware_validated': False})
        progress(status='passed', stage='complete', finished_at=time.time())
    except Exception as error:
        progress(status='failed', error=str(error), finished_at=time.time())


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('original', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    run(args.original.resolve(), args.output.resolve())
