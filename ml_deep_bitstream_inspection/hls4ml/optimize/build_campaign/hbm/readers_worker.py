#!/usr/bin/env python3
"""Foreground Coyote build adapter owned by the existing build orchestrator."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time


def save(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2))
    temporary.replace(path)


def run(root):
    config = json.loads((root / 'config.json').read_text())
    state = dict(id=config['id'], pid=os.getpid(), status='running', started_at=time.time())
    environment = dict(os.environ)
    environment['PATH'] = '/tools/Xilinx/Vivado/2024.2/bin:/tools/Xilinx/Vitis_HLS/2024.2/bin:' + environment['PATH']
    environment['OMP_NUM_THREADS'] = '4'
    environment['TMPDIR'] = str(root / 'tmp')
    (root / 'tmp').mkdir(exist_ok=True)
    assert json.loads((root / 'validation.json').read_text())['status'] == 'passed'
    sources = {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
               for directory in ['hw', 'coyote'] for path in (root / directory).rglob('*') if path.is_file()}
    save(root / 'source_hashes.json', sources)
    try:
        commands = [('configure', ['cmake', '-S', str(root / 'hw'), '-B', str(root / 'build'),
                                    '-DVITIS_HLS_MODE=vitis_hls', '-DCOMP_CORES=4',
                                    '-DVIVADO_ROOT_DIR=/tools/Xilinx/Vivado/2024.2',
                                    '-DVITIS_HLS_ROOT_DIR=/tools/Xilinx/Vitis_HLS/2024.2'], root)]
        commands += [(stage, ['make', '-j1', stage], root / 'build')
                     for stage in ['project', 'synth', 'link', 'shell', 'bitgen']]
        for stage, argv, cwd in commands:
            state.update(stage=stage, stage_started_at=time.time())
            save(root / 'status.json', state)
            with (root / f'{stage}.log').open('w') as output:
                result = subprocess.run(argv, cwd=cwd, env=environment, stdout=output, stderr=subprocess.STDOUT)
            if result.returncode:
                raise RuntimeError(f'{stage} exited {result.returncode}: {root / (stage + ".log")}')
        state.update(status='build_finished_unverified', finished_at=time.time())
        save(root / 'status.json', state)
    except BaseException as error:
        state.update(status='failed', error=repr(error), finished_at=time.time())
        save(root / 'status.json', state)
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('root', type=Path)
    run(parser.parse_args().root.resolve())
