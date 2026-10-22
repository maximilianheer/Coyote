#!/usr/bin/env python3
"""Read-only first-hour inspection of the selected queues; outcome monitors stay attached."""
import argparse, json, os, time, sys
from pathlib import Path
if (Path(__file__).resolve().parent/'controller').is_dir():sys.path.insert(0,str(Path(__file__).resolve().parent/'controller'))
from selected_builds import load
from implementation_permits import alive
from worker import save

def inspect(root):
    jobs={}
    for row in load(root/'campaign.json')['jobs']:
        job=Path(row['job']);state=load(job/'status.json')
        jobs[row['id']]={'queue':load(root/'jobs'/(row['id']+'.json')),'worker':state,
                         'worker_alive':alive(state.get('pid'),str(job))}
        stage=job/(state.get('stage','')+'.log')
        if stage.is_file():jobs[row['id']]['stage_log']={'bytes':stage.stat().st_size,'mtime':stage.stat().st_mtime}
    mem={k:v.strip() for k,v in (line.split(':',1) for line in Path('/proc/meminfo').read_text().splitlines()) if k in ('MemAvailable','SwapFree')}
    return {'at':time.time(),'queues':{lane:load(root/(lane+'.json')) for lane in ('primary','nonstreaming')},'jobs':jobs,
            'memory':mem,'load_average':os.getloadavg()}

def run(root):
    state_path=root/'first_hour_inspection.json';state=load(state_path)
    state.update(status='monitoring',pid=os.getpid());state.setdefault('started_at',time.time())
    out=root/'inspections';out.mkdir(exist_ok=True)
    while True:
        record=inspect(root);save(out/(str(int(record['at']))+'.json'),record)
        state.update(heartbeat=time.time(),last_inspection=record['at'])
        if time.time()-state['started_at']>=3600:state.update(status='complete',finished_at=time.time())
        save(state_path,state)
        if state['status']=='complete':return
        time.sleep(60)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);a=p.parse_args();run(a.root.resolve())
