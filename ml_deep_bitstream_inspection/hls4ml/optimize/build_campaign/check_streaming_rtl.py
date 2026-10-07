#!/usr/bin/env python3
"""Check an isolated snapshot of completed HLS RTL, including the real IP models."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
from prepare import sha, verify_sources
from worker import save

def run(jobdir, name='streaming_rtl', notify_root=None):
    output=jobdir/name
    output.mkdir(exist_ok=False)
    outcome=dict(status='running',pid=os.getpid(),started_at=time.time())
    save(output/'check.json',outcome)
    try:
        manifest=verify_sources(jobdir)
        tops=list((jobdir/'build').rglob('solution1/syn/verilog/model_wrapper.v'))
        if len(tops)!=1:raise RuntimeError(f'Expected one synthesized top: {tops}')
        source=tops[0].parent
        files={p.name:sha(p) for p in source.iterdir() if p.is_file()}
        for name_ in files:shutil.copy2(source/name_,output/name_)
        for name_ in ['streaming_rtl_tb.sv','streaming_sim.tcl','streaming_wave.tcl']:
            shutil.copy2(jobdir/'tests'/name_,output/name_)
        shutil.copy2(jobdir/'rtl_expected.txt',output/'rtl_expected.txt')
        save(output/'source_hashes.json',dict(source_manifest_sha256=manifest,
             rtl_source=str(source),rtl_files=files,
             test_files={p.name:sha(p) for p in output.glob('streaming*') if p.is_file()},
             reference_sha256=sha(output/'rtl_expected.txt')))
        env=os.environ.copy()
        env['PATH']='/tools/Xilinx/Vivado/2024.2/bin:'+env['PATH']
        with (output/'check.log').open('w') as log:
            result=subprocess.run(['vivado','-mode','batch','-source',str(output/'streaming_sim.tcl')],
                cwd=output,env=env,stdout=log,stderr=subprocess.STDOUT)
        if result.returncode or 'PASS synthesized streaming RTL' not in (output/'check.log').read_text():
            raise RuntimeError(f'Synthesized RTL simulation failed: {output}/check.log')
        if {p.name:sha(p) for p in source.iterdir() if p.is_file()}!=files:
            raise RuntimeError('HLS RTL changed during simulation; repeat against stable output')
        if verify_sources(jobdir)!=manifest:raise RuntimeError('Prepared sources changed')
        outcome.update(status='passed')
        print('PASS synthesized streaming RTL; evidence:',output,flush=True)
    except Exception as exc:
        outcome.update(status='failed',error=str(exc))
        print(str(exc),flush=True)
    outcome['finished_at']=time.time()
    save(output/'check.json',outcome)
    if notify_root is not None:
        from monitor import notify
        notify(notify_root,f"S_I synthesized RTL check {outcome['status']}: {outcome.get('error','all checks passed')}. Evidence: {output}")
    return 0 if outcome['status']=='passed' else 1

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('jobdir',type=Path)
    p.add_argument('--output',default='streaming_rtl');p.add_argument('--notify-root',type=Path)
    args=p.parse_args()
    raise SystemExit(run(args.jobdir.resolve(),args.output,args.notify_root))
