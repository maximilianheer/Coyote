#!/usr/bin/env python3
"""Check maintained direct tops against actual generated Coyote interfaces."""
import argparse,hashlib,json,subprocess
from pathlib import Path

def run(job,package,gpu_path=False,output=None):
    if gpu_path and job.name!='D_G':raise ValueError('GPU path simulation requires D_G')
    cwd=output or job/('gpu_path_validation' if gpu_path else 'top_elaboration');cwd.mkdir(parents=True,exist_ok=True)
    pkg=job/'coyote/hw/hdl/pkg';source=job/'hw/src'
    files=[package,pkg/'axi_intf.sv',pkg/'lynx_intf.sv',source/'hdl/direct_control.sv',
        source/'hdl/elastic_fifo.sv',job/'tests/direct_top_elaboration.sv']
    if gpu_path:files.append(Path(__file__).with_name('direct_gpu_path_tb.sv').resolve())
    args=['/tools/Xilinx/Vivado/2024.2/bin/xvlog','--sv','-i',str(pkg),'-i',str(source),'-i',str(source/'hdl'),
        *map(str,files)]
    records=files+[source/'vfpga_top.svh',source/'hdl/direct_variant.svh',source/'hdl/debug_probe.svh']
    (cwd/'sources.json').write_text(json.dumps({str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in records},indent=2)+'\n')
    top='direct_gpu_path_tb' if gpu_path else 'top_elaboration'
    with (cwd/'check.log').open('w') as f:
        subprocess.run(args,cwd=cwd,stdout=f,stderr=subprocess.STDOUT,check=True)
        subprocess.run(['/tools/Xilinx/Vivado/2024.2/bin/xelab',top,'-s','direct_top','-timescale','1ns/1ps'],cwd=cwd,stdout=f,stderr=subprocess.STDOUT,check=True)
        if gpu_path:subprocess.run(['/tools/Xilinx/Vivado/2024.2/bin/xsim','direct_top','-runall'],cwd=cwd,stdout=f,stderr=subprocess.STDOUT,check=True)
    if gpu_path and 'PASS GPU path:' not in (cwd/'check.log').read_text():raise RuntimeError('GPU path simulation did not pass')
    print('PASS GPU path simulation' if gpu_path else 'PASS direct top elaboration',job.name)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('job',type=Path);p.add_argument('package',type=Path)
    p.add_argument('--gpu-path',action='store_true');p.add_argument('--output',type=Path)
    a=p.parse_args();run(a.job.resolve(),a.package.resolve(),a.gpu_path,a.output.resolve() if a.output else None)
