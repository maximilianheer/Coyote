#!/usr/bin/env python3
"""Elaborate wrappers against actual generated Coyote interface definitions."""
import argparse
import json
from pathlib import Path
import subprocess

from prepare import HERE, sha
from worker import save


def run(job, package):
    directory = job / 'wiring_validation'
    directory.mkdir(exist_ok=True)
    source = job / 'hw/src'
    files = [package, job / 'coyote/hw/hdl/pkg/axi_intf.sv',
             job / 'coyote/hw/hdl/pkg/lynx_intf.sv',
             *sorted((source / 'hdl').glob('*.sv')),
             HERE / 'tests/deployment_top_elaboration.sv']
    commands = [
        ['xvlog', '--sv', '-i', str(source), '-i', str(source / 'hdl'),
         '-i', str(job / 'coyote/hw/hdl/pkg'), *map(str, files)],
        ['xelab', 'top_elaboration', '-s', 'deployment_wiring', '-mt', '4'],
    ]
    for arguments in commands:
        result = subprocess.run(['/tools/Xilinx/Vivado/2024.2/bin/' + arguments[0],
                                 *arguments[1:]], cwd=directory,
                                capture_output=True, text=True)
        output = result.stdout + result.stderr
        (directory / (arguments[0] + '.log')).write_text(output)
        if result.returncode or 'ERROR:' in output:
            raise RuntimeError(f'Wrapper {arguments[0]} failed: {directory}')
    inputs = files + list(source.rglob('*.svh'))
    save(directory / 'result.json', {
        'status': 'passed', 'scope': 'wiring_only_with_HLS_port_stubs',
        'files': {str(path): sha(path) for path in inputs},
    })
    print('PASS wrapper wiring ' + job.parent.name, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('job', type=Path)
    parser.add_argument('--package', required=True, type=Path)
    arguments = parser.parse_args()
    run(arguments.job.resolve(), arguments.package.resolve())
