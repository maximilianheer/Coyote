#!/usr/bin/env python3
"""Independent hls4ml iterations: prepare, validate, build, status, resume, campaign."""
import argparse, concurrent.futures, fcntl, json, os, shutil, subprocess, sys, time
from pathlib import Path
from iteration_prepare import snapshot, ITERATIONS
from prepare import HERE, REPO
from worker import save

def new_attempt(root, ident):
    config=ITERATIONS/ident/'iteration.json'
    if not config.is_file():raise ValueError('Unknown iteration '+ident)
    parent=root/ident;parent.mkdir(parents=True,exist_ok=True)
    n=max([int(p.name.split('_')[1]) for p in parent.glob('attempt_*') if p.is_dir()]+[0])+1
    job=parent/f'attempt_{n:02d}';snapshot(config,job)
    return job

def run(job,stage):
    with (job/'worker.log').open('a') as log:
        return subprocess.call([sys.executable,str(job/'tooling/iteration_worker.py'),str(job),stage],stdout=log,stderr=subprocess.STDOUT)

def notify(root, ident, result):
    message=f'hls4ml {ident}: {result}. No board programming. Results: {root}'
    try:
        p=subprocess.run(['curl','--fail','--max-time','20','-s','-d',message,'https://ntfy.sh/coyote-build-sdeheredia'],capture_output=True,text=True)
        entry={'id':ident,'outcome':result,'notification_returncode':p.returncode,'at':time.time()}
    except OSError as e:entry={'id':ident,'outcome':result,'notification_error':str(e),'at':time.time()}
    with (root/'notifications.jsonl').open('a') as f:f.write(json.dumps(entry)+'\n')

def campaign(root):
    root.mkdir(parents=True,exist_ok=True)
    state={'status':'running','pid':os.getpid(),'started_at':time.time(),'baseline':None,'candidates':{}}
    save(root/'campaign.json',state)
    baseline=new_attempt(root,'OPT_1_STREAMING');state['baseline']=str(baseline);save(root/'campaign.json',state)
    code=run(baseline,'validate');notify(root,'OPT_1_STREAMING','validation passed' if code==0 else 'validation failed')
    if code:
        state.update(status='blocked',reason='Baseline correctness must pass before A/B2 launch')
        save(root/'campaign.json',state);return 1
    candidates=[new_attempt(root,i) for i in ['OPT_2_DSP_RESOURCES_B2','OPT_3_BRAM_FIFO_A']]
    state['candidates']={p.parent.name:str(p) for p in candidates};save(root/'campaign.json',state)
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futures={pool.submit(run,p,'build'):p for p in candidates}
        outcomes={}
        for future in concurrent.futures.as_completed(futures):
            job=futures[future];outcomes[job.parent.name]='passed' if future.result()==0 else 'failed'
            notify(root,job.parent.name,outcomes[job.parent.name]);state['outcomes']=outcomes;save(root/'campaign.json',state)
    state.update(status='passed' if all(v=='passed' for v in outcomes.values()) else 'failed',finished_at=time.time())
    save(root/'campaign.json',state);return int(state['status']!='passed')

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=['profile','prepare','validate','build','status','resume','campaign','retry'])
    p.add_argument('--root',type=Path,required=True);p.add_argument('--id',choices=[p.name for p in ITERATIONS.glob('OPT_*') if p.is_dir()])
    p.add_argument('--attempt',type=Path);p.add_argument('--profile-cache',type=Path);p.add_argument('--stage',choices=['profile','prepare','validate','build'],default='build')
    a=p.parse_args();root=a.root.resolve()
    if a.command=='status':
        for path in sorted(root.glob('*/attempt_*/status.json')):print(str(path),path.read_text())
        for path in sorted(root.glob('*/attempt_*/recovery/*/status.json')):print(str(path),path.read_text())
        for path in [root/'campaign.json',*sorted(root.glob('retry_OPT_*.json')),*sorted(root.glob('recovery_OPT_*.json'))]:
            if path.exists():print(str(path),path.read_text())
        return 0
    if a.command=='campaign':return campaign(root)
    if a.command=='retry':
        if not a.id:p.error('--id is required')
        job=new_attempt(root,a.id)
        if a.profile_cache:
            shutil.copytree(a.profile_cache.resolve(),job/'fifo_profile_cache')
            from prepare import sha
            metadata=json.loads((job/'attempt.json').read_text())
            metadata['inputs'].update({str(p.relative_to(job)):sha(p) for p in (job/'fifo_profile_cache').rglob('*') if p.is_file()})
            save(job/'attempt.json',metadata)
        record=root/('retry_'+a.id+'.json')
        state={'status':'running','pid':os.getpid(),'started_at':time.time(),
               'baseline':None,'candidates':{a.id:str(job)}}
        save(record,state)
        code=run(job,a.stage)
        state.update(status='passed' if code==0 else 'failed',finished_at=time.time())
        save(record,state);notify(root,a.id,state['status'])
        return code
    if a.command=='resume':
        if not a.attempt:p.error('--attempt is required for resume')
        job=a.attempt.resolve()
        # Resume only at safe completed boundaries; failed partial outputs get a fresh attempt.
        with (job/'worker.lock').open('a') as lock:
            try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:raise RuntimeError('Attempt is still running: '+str(job))
        old=json.loads((job/'status.json').read_text())
        if old['status']!='passed':
            ident=json.loads((job/'config/iteration.json').read_text())['id'];job=new_attempt(root,ident)
        return run(job,a.stage)
    if not a.id:p.error('--id is required')
    job=new_attempt(root,a.id)
    print(job,flush=True);return run(job,a.command)

if __name__=='__main__':raise SystemExit(main())
