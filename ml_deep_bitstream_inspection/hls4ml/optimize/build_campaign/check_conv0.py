#!/usr/bin/env python3
"""Isolate and validate conv0; retain source hashes and synthesis evidence."""
import argparse, json, os, shutil, subprocess, time
from pathlib import Path
from prepare import MODEL, HARDWARE, HERE, sha
from worker import save

def run(root):
    root.mkdir(parents=True,exist_ok=False)
    shutil.copytree(MODEL/'firmware',root/'firmware')
    for src in [HARDWARE/'common/conv0_dataflow.hpp',HERE/'tests/conv0_check.cpp',HERE/'tests/conv0_synth.tcl']:
        shutil.copy2(src,root/src.name)
    save(root/'sources.json',{str(p.relative_to(root)):sha(p) for p in root.rglob('*') if p.is_file()})
    state=dict(status='running',started_at=time.time(),pid=os.getpid())
    env=os.environ.copy();env['PATH']='/tools/Xilinx/Vitis_HLS/2024.2/bin:'+env['PATH']
    def cmd(stage,args):
        state.update(stage=stage);save(root/'status.json',state)
        with (root/(stage+'.log')).open('w') as f:
            subprocess.run(args,cwd=root,env=env,stdout=f,stderr=subprocess.STDOUT,check=True)
    try:
        cmd('compile',['g++','-O1','-std=c++14','-Wno-unknown-pragmas','-I/tools/Xilinx/Vitis/2024.2/include','-I.',
            '-DWEIGHTS_DIR="'+str(root/'firmware/weights')+'"','conv0_check.cpp','/usr/lib/x86_64-linux-gnu/libgmp.so.10','-pthread','-o','conv0_check'])
        cmd('parity',['./conv0_check'])
        for top in ['conv0_baseline','conv0_candidate']:
            env['CONV0_TOP']=top
            cmd(top,['vitis_hls','-f','conv0_synth.tcl'])
        state.update(status='passed',stage='synthesis_complete')
    except Exception as error:state.update(status='failed',error=str(error))
    state['finished_at']=time.time();save(root/'status.json',state)
    return 0 if state['status']=='passed' else 1
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('root',type=Path);a=ap.parse_args()
    raise SystemExit(run(a.root.resolve()))
