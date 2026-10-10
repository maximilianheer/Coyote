#!/usr/bin/env python3
"""Silent 30-minute inspections; notifications only for hardware outcomes/blockers."""
import argparse,json,os,time
from pathlib import Path
from monitor import notify
from worker import save

def hardware_event(job):
    return job.get('hardware_started',False) and job.get('status') in ('passed','failed','blocked')

def run(root):
    path=root/'monitor_state.json'
    book=json.loads(path.read_text()) if path.exists() else dict(sent=[],last_inspection=0)
    while True:
        try:state=json.loads((root/'status.json').read_text())
        except (FileNotFoundError,json.JSONDecodeError):time.sleep(10);continue
        now=time.time()
        if now-book['last_inspection']>=1800:
            snapshot=dict(time=now,phase=state.get('phase'),scheduler_age=now-state.get('heartbeat',now),jobs=[])
            for job in state.get('jobs',[]):
                info={k:job[k] for k in ['id','status','stage','pid','attempt'] if k in job}
                if job.get('status')=='running':
                    try:os.kill(job['pid'],0);info['process_alive']=True
                    except (ProcessLookupError,KeyError):info['process_alive']=False
                log=root/'jobs'/job['id']/(job.get('stage','worker')+'.log')
                if log.exists():info.update(log_bytes=log.stat().st_size,log_age=now-log.stat().st_mtime)
                snapshot['jobs'].append(info)
            with (root/'inspections.jsonl').open('a') as f:f.write(json.dumps(snapshot)+'\n')
            book['last_inspection']=now
        for job in state.get('jobs',[]):
            key=f"{job['id']}:{job.get('attempt',1)}:{job.get('timing_recovery',0)}:{job['status']}"
            if hardware_event(job) and key not in book['sent']:
                message=f"{root.name}: hardware build {job['id']} {job['status']}; {job.get('stage','')}. {job.get('error','')}\nArtifacts/logs: {root/'jobs'/job['id']}"
                if notify(root,message):book['sent'].append(key)
        # Recovery can requeue a terminated attempt between monitor samples.
        events=root/'hardware_outcomes.jsonl'
        if events.exists():
            for line in events.read_text().splitlines():
                try:entry=json.loads(line)
                except json.JSONDecodeError:continue
                key=entry['key']
                if key not in book['sent'] and notify(root,entry['message']):book['sent'].append(key)
        if state.get('phase')=='running' and now-state.get('heartbeat',now)>180:
            key='scheduler_stale:'+str(state.get('scheduler_pid'))
            if key not in book['sent'] and notify(root,f'{root.name}: build scheduler stopped responding; autonomous recovery needs inspection.'):
                book['sent'].append(key)
        save(path,book)
        if state.get('phase')=='finished':
            # Do not notify for test-only jobs. Per-build outcomes are sufficient.
            return
        time.sleep(15)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);a=p.parse_args();run(a.root.resolve())
