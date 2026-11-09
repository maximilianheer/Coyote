#!/usr/bin/env python3
"""Run one sealed deployment build; never program the benchmark board."""
import argparse
import fcntl
import json
import os
import signal
from pathlib import Path
import subprocess
import time

from implementation_permits import permit
from prepare import sha
from worker import collect_artifacts, final_timing_reports, save
from hbm_clock import (verify_generated_hbm_clock, verify_hbm_clock_sources,
                       verify_report_application_clock, verify_report_hbm_clock)
from network_timing import (install_ethernet_control_replication,
                            verify_generated_control_clocks, verify_report_user_clock)


def run(job):
    config = json.loads((job / 'config.json').read_text())
    state = {
        'id': config['id'], 'pid': os.getpid(), 'status': 'running',
        'stage': 'starting', 'started_at': time.time(), 'hardware_validated': False,
    }
    environment = os.environ.copy()
    environment['PATH'] = ':'.join([
        '/tools/Xilinx/Vivado/2024.2/bin',
        '/tools/Xilinx/Vitis_HLS/2024.2/bin',
        '/tools/Xilinx/Vitis/2024.2/bin', environment['PATH'],
    ])
    environment['TMPDIR'] = str(job / 'tmp')
    environment['OMP_NUM_THREADS'] = '4'
    (job / 'tmp').mkdir(exist_ok=True)

    def progress(**values):
        state.update(values)
        save(job / 'status.json', state)

    def command(stage, arguments, directory):
        progress(stage=stage, stage_started_at=time.time())
        with (job / (stage + '.log')).open('w') as log:
            child = subprocess.Popen(arguments, cwd=directory, env=environment,
                                     stdout=log, stderr=subprocess.STDOUT,
                                     start_new_session=True)
            progress(child_pid=child.pid)
            try:
                code = child.wait(timeout=86400)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGTERM)
                try:
                    child.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.wait()
                raise RuntimeError(f'{stage} exceeded 24-hour watchdog')
        if code:
            raise RuntimeError(f'{stage} exited {code}; see {stage}.log')

    try:
        if config.get('variant'):
            wiring = job / 'wiring_validation/result.json'
            if not wiring.exists() or json.loads(wiring.read_text()).get('status') != 'passed':
                raise RuntimeError('Wrapper wiring validation is required before build launch')
            gate = job / 'validation.json'
            if not gate.exists() or json.loads(gate.read_text()).get('status') != 'passed':
                raise RuntimeError('Transport/preprocessing validation is required before build launch')
        for name, expected in json.loads((job / 'source_hashes.json').read_text()).items():
            if sha(job / name) != expected:
                raise RuntimeError('Changed sealed source: ' + name)
        command('configure', [
            'cmake', '-S', str(job / 'hw'), '-B', str(job / 'build'),
            '-DVITIS_HLS_MODE=vitis_hls', '-DCOMP_CORES=4',
            '-DVIVADO_ROOT_DIR=/tools/Xilinx/Vivado/2024.2',
            '-DVITIS_HLS_ROOT_DIR=/tools/Xilinx/Vitis_HLS/2024.2',
        ], job)
        if config.get('replicate_ethernet_padding_control'):
            install_ethernet_control_replication(job)
        if config.get('hls_ip_cache_manifest_sha256'):
            from deployment_ip_cache import install_cache
            install_cache(job, config)
        command('project', ['make', '-j1', 'project'], job / 'build')
        if config.get('user_clock_hz'):
            save(job / 'generated_control_clock_verification.json',
                 verify_generated_control_clocks(job / 'build', config['clock_hz'] / 1e6,
                                                 config['user_clock_hz'] / 1e6))
        hbm_mhz = config.get('hbm_axi_mhz', 450)
        if hbm_mhz != 450:
            verify_hbm_clock_sources(job)
            save(job / 'generated_hbm_clock_verification.json', {
                'mhz': hbm_mhz,
                'files': verify_generated_hbm_clock(job / 'build', hbm_mhz),
            })
        with permit(progress):
            for stage in ['synth', 'link', 'shell', 'bitgen']:
                if stage == 'bitgen':
                    # A timing-invalid image cannot be admitted for benchmarks.
                    # Reject it before spending time generating its bitstream.
                    final_timing_reports(job / 'build', config['id'])
                    report = job / 'build/reports/shell_timing_summary.rpt'
                    verify_report_application_clock(report, config.get('clock_hz', 250000000) / 1e6)
                    verify_report_hbm_clock(report, hbm_mhz)
                    if config.get('user_clock_hz'):
                        verify_report_user_clock(report, config['user_clock_hz'] / 1e6)
                command(stage, ['make', '-j1', stage], job / 'build')
        artifacts = collect_artifacts(job / 'build', config['id'])
        save(job / 'artifacts.json', {
            'files': {str(Path(name).relative_to(job)): sha(name)
                      for category in artifacts.values() if isinstance(category, list)
                      for name in category},
            'hardware_validated': False,
        })
        progress(status='passed', stage='complete', finished_at=time.time())
        return 0
    except Exception as error:
        progress(status='failed', error=str(error), finished_at=time.time())
        return 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('job', type=Path)
    arguments = parser.parse_args()
    job = arguments.job.resolve()
    with (job / 'worker.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        raise SystemExit(run(job))
