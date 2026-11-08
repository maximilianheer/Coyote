#!/usr/bin/env python3
"""Run transport RTL checks and reject XSim's zero-exit fatal/Tcl failures."""
import argparse
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
RTL = HERE / 'hardware/deployment'
TESTS = HERE / 'tests'
VIVADO = Path('/tools/Xilinx/Vivado/2024.2/bin')

CASES = {
    'deployment_control_tb': ['deployment_control'],
    'diagnostic_control_tb': ['diagnostic_control'],
    'deployment_transport_tb': ['dual_reader_ring'],
    'hbm_read_window_tb': ['hbm_read_window'],
    'hbm_forward_tb': ['hbm_forward'],
}


def run(root):
    for top, modules in CASES.items():
        directory = root / top
        directory.mkdir(parents=True, exist_ok=True)
        commands = [
            ['xvlog', '--sv', *[str(RTL / (name + '.sv')) for name in modules],
             str(TESTS / (top + '.sv'))],
            ['xelab', top, '-s', 'check', '-mt', '4'],
            ['xsim', 'check', '-runall'],
        ]
        for index, arguments in enumerate(commands):
            result = subprocess.run([str(VIVADO / arguments[0]), *arguments[1:]],
                                    cwd=directory, capture_output=True, text=True)
            output = result.stdout + result.stderr
            (directory / f'{index}_{arguments[0]}.log').write_text(output)
            if result.returncode or 'Fatal:' in output or 'ERROR:' in output:
                raise RuntimeError(f'{top}: {arguments[0]} failed; see {directory}')
            if index == 2 and 'PASS ' not in output:
                raise RuntimeError(f'{top}: simulator did not reach PASS')
        print('PASS ' + top, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('root', type=Path)
    run(parser.parse_args().root.resolve())
