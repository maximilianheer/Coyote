#!/usr/bin/env python3
"""Simulate exported checker primitives, checking assertions as well as exit status."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time

TOOLS=Path('/tools/Xilinx/Vivado/2024.2/bin')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('work',type=Path)
    p.add_argument('--application',action='store_true',help='Whole routed application; fixed empty-header shell boundary')
    a=p.parse_args();work=a.work.resolve()
    netlists=['userlogic_routed.v'] if a.application else ['preprocess_wrapper_hls_ip.v','cnn_wrapper_hls_ip.v']
    tests=['routed_userlogic_tb.sv'] if a.application else ['elastic_fifo.sv','direct_pipe_tb.sv']
    top='routed_userlogic_tb' if a.application else 'direct_pipe_tb'
    generics=[] if a.application else ['--generic_top','STARTUP_IDLE=20000','--generic_top','ALWAYS_READY=1']
    marker='PASS routed application: empty frame, exact pixels/logit and CSR verdict' if a.application else 'PASS direct synthesized RTL parity: frames=1'
    commands=[
        ('compile_netlists',[str(TOOLS/'xvlog'),'--incr','--relax','--work','xil_defaultlib',
            *netlists,'/tools/Xilinx/Vivado/2024.2/data/verilog/src/glbl.v']),
        ('compile_testbench',[str(TOOLS/'xvlog'),'--incr','--relax','--sv','--work','xil_defaultlib',*tests]),
        ('elaborate',[str(TOOLS/'xelab'),'--incr','--debug','typical','--relax','--mt','2',
            *generics,
            '-L','xil_defaultlib','-L','unisims_ver','-L','unimacro_ver','-L','secureip',
            '--snapshot','routed_checker','xil_defaultlib.'+top,'xil_defaultlib.glbl']),
        ('simulate',[str(TOOLS/'xsim'),'routed_checker','-runall','-log','simulation.log']),
    ]
    state=dict(status='running',started_at=time.time(),scope='functional routed CNN, synthesized preprocessing, behavioral FIFO; uniform reset replicas; one empty frame')
    if a.application:
        state['scope']='functional routed preprocessing, FIFO, CNN and CSR controller; one empty frame; uniform reset replicas, fixed zero-header equality boundary, reconstructed local CSR read-accept condition; PCIe and physical timing excluded'
    state['source_sha256']={name:hashlib.sha256((work/name).read_bytes()).hexdigest() for name in netlists+tests}
    def save():
        target=work/'status.json';tmp=work/'status.json.tmp';tmp.write_text(json.dumps(state,indent=2)+'\n');tmp.replace(target)
    try:
        for stage,args in commands:
            state.update(stage=stage,command=args,stage_started_at=time.time());save()
            with (work/(stage+'.log')).open('w') as log:
                child=subprocess.Popen(args,cwd=work,stdout=log,stderr=subprocess.STDOUT)
                state['child_pid']=child.pid;save()
                while child.poll() is None:
                    state['heartbeat']=time.time();save();time.sleep(5)
                if child.returncode:raise RuntimeError(f'{stage}: exit {child.returncode}')
        text=(work/'simulation.log').read_text()
        if marker not in text or 'Fatal:' in text or 'FATAL' in text:
            raise RuntimeError('functional parity failed; inspect simulation.log')
        state['status']='passed'
    except Exception as error:
        state.update(status='failed',error=str(error))
    state['finished_at']=time.time();save()
    raise SystemExit(state['status']!='passed')
