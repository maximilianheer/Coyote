#!/usr/bin/env python3
"""Early launch/parity check while IP packaging continues; final build gate remains."""
import argparse,json,os,shutil,signal,subprocess,time
from pathlib import Path
from prepare import HERE,sha,verify_sources
from worker import save

def run(jobdir, frames=2):
    if frames not in (2,8):raise ValueError('Expected two launch frames or all eight parity frames')
    output=jobdir/('early_launch_check' if frames==2 else 'early_full_check');output.mkdir(exist_ok=False)
    digest=verify_sources(jobdir)
    state=dict(status='running',stage='waiting_for_rtl',started_at=time.time(),
        pid=os.getpid(),source_manifest_sha256=digest,
        frames=frames,scope=f'{frames} consecutive frames, output backpressure, startup idle; final job RTL gate still required')
    save(output/'status.json',state)
    try:
        deadline=time.time()+7200
        while True:
            progress=json.loads((jobdir/'progress.json').read_text())
            if progress['status'] in ('failed','blocked'):raise RuntimeError('Hardware worker terminated before RTL check')
            log=jobdir/'project.log'
            text=log.read_text(errors='replace') if log.exists() else ''
            if 'Finished Command csynth_design' in text and 'Running: export_design' in text:break
            if time.time()>deadline:raise TimeoutError('RTL readiness deadline')
            state['heartbeat']=time.time();save(output/'status.json',state);time.sleep(10)
        core=list((jobdir/'build').rglob('solution1/syn/verilog/model_wrapper.v'))
        if len(core)!=1:raise RuntimeError('Expected one fresh model_wrapper RTL')
        shutil.copytree(core[0].parent,output/'core')
        for name in ['production_wrapper_tb.sv','production_wrapper_sim.tcl']:
            shutil.copy2(HERE/'tests'/name,output/name)
        rows=(jobdir/'rtl_expected.txt').read_text().splitlines()
        if len(rows)!=8:raise RuntimeError('Expected eight independently validated references')
        (output/'rtl_expected.txt').write_text('\n'.join(rows[:frames])+'\n')
        files={str(p.relative_to(output)):sha(p) for p in output.rglob('*') if p.is_file() and p.name!='status.json'}
        save(output/'sources.json',files)
        state.update(stage='simulation');save(output/'status.json',state)
        env=os.environ.copy();env['PRODUCTION_RTL_FRAMES']=str(frames);env['DRIVER_RESETS']='1'
        with (output/'check.log').open('w') as log:
            child=subprocess.Popen(['/tools/Xilinx/Vivado/2024.2/bin/vivado','-mode','batch','-source',str(output/'production_wrapper_sim.tcl')],cwd=output,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            state['child_pid']=child.pid
            deadline=time.time()+3600
            try:
                while child.poll() is None:
                    if time.time()>deadline:raise TimeoutError('Early RTL simulation exceeded one-hour bound')
                    state['heartbeat']=time.time();save(output/'status.json',state);time.sleep(5)
            except BaseException:
                os.killpg(child.pid,signal.SIGTERM)
                try:child.wait(timeout=5)
                except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL);child.wait()
                raise
        text=(output/'check.log').read_text(errors='replace')
        if child.returncode or f'PASS production wrapper frames={frames}' not in text or 'Fatal:' in text:
            raise RuntimeError('Early RTL launch check failed; inspect check.log')
        if verify_sources(jobdir)!=digest:raise RuntimeError('Hardware source changed during early check')
        if any(sha(output/p)!=h for p,h in files.items()):raise RuntimeError('Simulation inputs changed')
        state.update(status='passed',frames=frames,driver_resets=1,finished_at=time.time())
    except Exception as error:state.update(status='failed',error=str(error),finished_at=time.time())
    save(output/'status.json',state);print(json.dumps(state),flush=True)
    return 0 if state['status']=='passed' else 1
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('jobdir',type=Path);p.add_argument('--frames',type=int,choices=[2,8],default=2)
    a=p.parse_args();raise SystemExit(run(a.jobdir.resolve(),a.frames))
