#!/usr/bin/env python3
"""Elaborate every maintained top against a supplied generated Coyote package."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent))
from prepare import VARIANTS, sha

def main(root, package):
    results={}
    for ident in VARIANTS:
        job=root/'jobs'/ident
        if not job.exists(): continue
        cwd=job/'top_elaboration';cwd.mkdir(exist_ok=True)
        pkg=job/'coyote/hw/hdl/pkg'
        source=job/'hw/src'
        args=['/tools/Xilinx/Vivado/2024.2/bin/xvlog','--sv',
              '-i',str(pkg),'-i',str(source),'-i',str(source/'hdl')]
        if ident=='S_I':args+=['-d','BENCH_STREAMING']
        elif ident!='U':args+=['-d','BENCH_PHASE']
        args += [str(package),str(pkg/'axi_intf.sv'),str(pkg/'lynx_intf.sv'),
                 str(source/'hdl/benchmark_control.sv'),str(HERE/'top_elaboration.sv')]
        with (cwd/'check.log').open('w') as log:
            subprocess.run(args,cwd=cwd,stdout=log,stderr=subprocess.STDOUT,check=True)
            subprocess.run(['/tools/Xilinx/Vivado/2024.2/bin/xelab','top_elaboration',
                            '-s','top_check'],cwd=cwd,stdout=log,stderr=subprocess.STDOUT,check=True)
        results[ident]={'status':'passed','top_sha256':sha(source/'vfpga_top.svh'),
                        'parameters_sha256':sha(source/'hdl/benchmark_variant.svh')}
        print('PASS top elaboration',ident,flush=True)
    (root/'top_elaboration.json').write_text(json.dumps(dict(jobs=results,
        package=str(package),package_sha256=sha(package),
        test_sha256=sha(HERE/'top_elaboration.sv')),indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);p.add_argument('package',type=Path)
    a=p.parse_args();main(a.root.resolve(),a.package.resolve())
