#!/usr/bin/env python3
"""Run one sealed deployment build; never program the benchmark board."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import subprocess
import time

from implementation_permits import permit
from prepare import sha
from worker import collect_artifacts, save


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
            result = subprocess.run(arguments, cwd=directory, env=environment,
                                    stdout=log, stderr=subprocess.STDOUT)
        if result.returncode:
            raise RuntimeError(f'{stage} exited {result.returncode}; see {stage}.log')

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
        command('project', ['make', '-j1', 'project'], job / 'build')
        with permit(progress):
            for stage in ['synth', 'link', 'shell', 'bitgen']:
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
