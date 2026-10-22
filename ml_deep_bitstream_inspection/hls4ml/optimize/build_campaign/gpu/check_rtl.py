#!/usr/bin/env python3
import argparse,json,os,subprocess,hashlib
from pathlib import Path
HERE=Path(__file__).resolve().parent
CAMPAIGN=HERE.parent
REPO=CAMPAIGN.parents[2]
def run(job, package=None):
    src=job/'hw/src';sim=job/'rtl_validation';sim.mkdir(exist_ok=True)
    env=dict(os.environ);env['PATH']='/tools/Xilinx/Vivado/2024.2/bin:'+env['PATH']
    if package is None:
        package=REPO/'hls4ml/optimize/runs/20261001_184524/jobs/I/build/opt_i_shell/hdl/lynx_pkg.sv'
    files=[package,job/'coyote/hw/hdl/pkg/axi_intf.sv',job/'coyote/hw/hdl/pkg/lynx_intf.sv',src/'hdl/gpu_control.sv',src/'hdl/gpu_poll.sv',src/'hdl/elastic_fifo.sv',job/'tests/direct_top_elaboration.sv',job/'tests/gpu_variants_tb.sv']
    commands=[('compile',['xvlog','--sv','-i',str(src),'-i',str(src/'hdl'),'-i',str(job/'coyote/hw/hdl/pkg'),*[str(p) for p in files]]),('elaborate',['xelab','gpu_variants_tb','-s','gpu_test']),('simulate',['xsim','gpu_test','-runall'])]
    for name,args in commands:
        with (sim/(name+'.log')).open('w') as f:subprocess.run(args,cwd=sim,env=env,stdout=f,stderr=subprocess.STDOUT,check=True)
    if 'PASS GPU variant' not in (sim/'simulate.log').read_text():raise RuntimeError('RTL did not pass')
    files += list(src.rglob('*.svh'))
    (sim/'validation.json').write_text(json.dumps({'status':'passed','files':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}},indent=2))
    print((sim/'simulate.log').read_text().split('PASS GPU variant')[-1][:220])
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('job',type=Path);p.add_argument('--package',type=Path);a=p.parse_args();run(a.job.resolve(),a.package)
