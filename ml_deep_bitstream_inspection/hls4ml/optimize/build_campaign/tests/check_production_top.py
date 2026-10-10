#!/usr/bin/env python3
"""Elaborate passive production wiring against actual generated Coyote types."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

HERE = Path(__file__).resolve().parent


def run(job, output):
    output.mkdir(parents=True, exist_ok=False)
    pkg = job/'coyote/hw/hdl/pkg'
    packages = list((job/'build').glob('*_shell/hdl/lynx_pkg.sv'))
    if len(packages) != 1:
        raise RuntimeError('Expected one generated Coyote package')
    maintained = HERE.parent/'hardware'
    for path in [maintained/'production/vfpga_timed.svh',
                 maintained/'production/passive_timestamps.sv',
                 maintained/'debug_probe.svh', HERE/'production_top_elaboration.sv']:
        shutil.copy2(path, output/path.name)
    files = [packages[0], pkg/'axi_intf.sv', pkg/'lynx_intf.sv',
             output/'passive_timestamps.sv', output/'production_top_elaboration.sv']
    records = files+[output/'vfpga_timed.svh', output/'debug_probe.svh']
    (output/'sources.json').write_text(json.dumps({str(p):hashlib.sha256(p.read_bytes()).hexdigest()
                                                  for p in records}, indent=2)+'\n')
    tools = Path('/tools/Xilinx/Vivado/2024.2/bin')
    with (output/'check.log').open('w') as log:
        subprocess.run([str(tools/'xvlog'), '--sv', '-i', str(pkg), '-i', str(output),
                        *map(str,files)], cwd=output, stdout=log, stderr=subprocess.STDOUT, check=True)
        subprocess.run([str(tools/'xelab'), 'top_elaboration', '-s', 'production_top',
                        '-timescale', '1ns/1ps'], cwd=output, stdout=log,
                       stderr=subprocess.STDOUT, check=True)
    (output/'status.json').write_text(json.dumps(dict(status='passed',
        scope='Coyote interface wiring only; HLS port stub, no CNN behavior'))+'\n')
    print('PASS passive production top elaboration')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('job', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    run(args.job.resolve(), args.output.resolve())
