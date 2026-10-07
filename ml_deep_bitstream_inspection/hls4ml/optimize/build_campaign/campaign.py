#!/usr/bin/env python3
"""Five-slot dependency-aware build queue, managed under a dedicated tmux socket."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from prepare import prepare, INITIAL
from worker import save
from recovery import recover_failed, archive_and_retry

HERE=Path(__file__).resolve().parent
ORDER=['S_I','I','H16','H8','H4','H2','H1','HN','HR','HE','U','N','P','C']
TERMINAL={'passed','failed','blocked'}

def eligible(job,jobs):
    ident=job['id']
    if job['status']!='pending': return False
    byid={j['id']:j for j in jobs}
    deps = list(INITIAL) if ident in ('HN','HR') else list(INITIAL)+['HN','HR'] if ident=='HE' else []
    return all(byid[d]['status'] in TERMINAL for d in deps)

def render(root,state):
    lines=['# Build status', '', f"Campaign: `{root.name}`. Phase: **{state['phase']}**. Updated: {time.ctime()}",
           '', '| Job | Status | Stage | Hours | Details |','| --- | --- | --- | ---: | --- |']
    for j in state['jobs']:
        elapsed=(j.get('finished_at',time.time())-j.get('started_at',time.time()))/3600
        details=j.get('error','')
        if 'artifacts' in j and 'partial_bytes' in j['artifacts']:
            details=f"{j['artifacts']['partial_bytes']/2**20:.3f} MiB; hardware validation pending"
        lines.append(f"| {j['id']} | {j['status']} | {j.get('stage','')} | {max(0,elapsed):.2f} | {details.replace('|','/')} |")
    lines+=['', f"Attach: `tmux -L coyote-opt attach -t {state['tmux_session']}`",
            '', 'Build success does not imply hardware/PR validation.']
    (root/'STATUS.md').write_text('\n'.join(lines)+'\n')

def run(root,jobs_limit=5):
    if not 1<=jobs_limit<=5:raise ValueError('jobs must be between 1 and 5')
    with (root/'scheduler.lock').open('w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        return run_locked(root,jobs_limit)

def run_locked(root,jobs_limit):
    state=json.loads((root/'status.json').read_text())
    state.update(phase='running',scheduler_pid=os.getpid(),max_jobs=jobs_limit)
    # Resume can adopt still-live tmux workers; never starts duplicate workers.
    for j in state['jobs']:
        if j['status']=='running':
            try: os.kill(j['pid'],0)
            except (ProcessLookupError,KeyError):
                p=root/'jobs'/j['id']/'progress.json'
                progress=json.loads(p.read_text()) if p.exists() else {}
                if progress.get('status') in TERMINAL: j.update(progress)
                else:j.update(status='failed',error='Interrupted worker; inspect logs before retrying',finished_at=time.time())
    while True:
        retry_file=root/'retry_requests.json'
        if retry_file.exists():
            requests=json.loads(retry_file.read_text())
            for request in requests:
                ident=request['id'] if isinstance(request,dict) else request
                settings=request.get('settings',{}) if isinstance(request,dict) else {}
                if set(settings)-{'geometry_override','capacity_retries'}:
                    raise ValueError('Unsupported retry settings')
                job=next(j for j in state['jobs'] if j['id']==ident)
                if job['status'] not in TERMINAL:continue
                archive_and_retry(root,job,**settings)
            retry_file.unlink()
        for job in state['jobs']:
            if job['status']!='running':continue
            progress_path=root/'jobs'/job['id']/'progress.json'
            if progress_path.exists():
                try:progress=json.loads(progress_path.read_text())
                except json.JSONDecodeError:continue
                job.update(progress)
            if job['status']=='running':
                try:os.kill(job['pid'],0)
                except ProcessLookupError:job.update(status='failed',error='Adopted worker disappeared',finished_at=time.time())
        if not (root/'dispatch_paused').exists():recover_failed(root,state)
        state['jobs'].sort(key=lambda j:ORDER.index(j['id']))
        for job in state['jobs']:
            if (root/'dispatch_paused').exists():break
            if sum(j['status']=='running' for j in state['jobs'])>=jobs_limit:break
            if not eligible(job,state['jobs']):continue
            ident=job['id'];dst=root/'jobs'/ident
            job.update(stage='preparation',started_at=time.time())
            print(f'{time.ctime()}: prepare {ident}',flush=True)
            try:
                if not job.get('prepared'):prepare(root,job,state)
                save(dst/'job.json',job)
                # Each worker occupies its own tmux window; launcher shell waits for it.
                launch=dst/'launch.sh'
                launch.write_text('#!/usr/bin/env bash\nset -euo pipefail\n'
                    + 'exec '+__import__('shlex').join([sys.executable,'-u',str(HERE/('recover_timing.py' if job.get('timing_recovery') else 'worker.py')),str(dst)])
                    + ' >> '+__import__('shlex').quote(str(dst/'worker.log'))+' 2>&1\n')
                launch_time=time.time()
                subprocess.run(['tmux','-L','coyote-opt','new-window','-d','-t',state['tmux_session'],
                                '-n',ident,'bash '+__import__('shlex').quote(str(launch))],check=True)
                # Worker publishes its actual PID; window setup failure does not count as running.
                for _ in range(100):
                    p=dst/'progress.json'
                    if p.exists():
                        try:
                            if json.loads(p.read_text()).get('started_at',0)>=launch_time:break
                        except json.JSONDecodeError:pass
                    time.sleep(.1)
                if not p.exists() or json.loads(p.read_text()).get('started_at',0)<launch_time:
                    raise RuntimeError('Worker did not publish fresh progress within 10 seconds')
                job.update(json.loads(p.read_text()))
                print(f'{time.ctime()}: launched {ident}, pid={job.get("pid")}',flush=True)
            except Exception as error:
                job.update(status='blocked',error=str(error),finished_at=time.time())
                print(f'{ident}: {error}',flush=True)
            state['heartbeat']=time.time();save(root/'status.json',state);render(root,state)
        state['heartbeat']=time.time()
        state['phase']='paused' if (root/'dispatch_paused').exists() else 'running'
        if all(j['status'] in TERMINAL for j in state['jobs']):state['phase']='finished'
        save(root/'status.json',state);render(root,state)
        if state['phase']=='finished':return
        time.sleep(10)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['run','status','dry-run'])
    p.add_argument('root',type=Path);p.add_argument('--jobs',type=int,default=5);a=p.parse_args()
    if a.action=='run':run(a.root.resolve(),a.jobs)
    elif a.action=='status':print((a.root/'STATUS.md').read_text())
    else:
        state=json.loads((a.root/'status.json').read_text())
        print('Initially eligible:',', '.join(j['id'] for j in state['jobs'] if eligible(j,state['jobs'])))
        print('Priority: '+ ' '.join(ORDER))
