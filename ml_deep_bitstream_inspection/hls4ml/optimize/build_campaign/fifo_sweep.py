#!/usr/bin/env python3
"""Native FIFO sweep: profile, validate and build. No board operations."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from iteration_prepare import snapshot, ITERATIONS
from iteration_monitor import alive, send
from fifo_sweep_results import read, verify_inputs, profile_summary, artifact_summary, hls_estimates
from prepare import HERE, REPO, sha
from worker import save

DEPTHS=(1024,4096,16384,65536,100000,262144)
CAMPAIGN=HERE.parent/'runs/configurable_streaming_20261010'
A=CAMPAIGN/'OPT_3_BRAM_FIFO_A/attempt_03'
B2=CAMPAIGN/'OPT_2_DSP_RESOURCES_B2/attempt_01'
TERMINAL={'passed','failed','blocked','duplicate'}


def load(path,default=None):
    return read(path) if path.exists() else ({} if default is None else default)


def event(root,ident,stage,outcome,detail=''):
    key=hashlib.sha256(f'{ident}:{stage}:{outcome}'.encode()).hexdigest()[:20]
    save(root/'events'/(key+'.json'),{'id':ident,'outcome':outcome,'stage':stage,'at':time.time(),
         'message':f'Native FIFO sweep {ident}: {stage} {outcome}. {detail} Results: {root}'})


def initialize(root):
    if root.exists():raise FileExistsError('Use run/status to resume an initialized sweep')
    root.mkdir(parents=True)
    for d in ['configs','points','events','logs','inspections']:(root/d).mkdir()
    points=[]
    base=read(ITERATIONS/'OPT_3_BRAM_FIFO_A/iteration.json')
    for depth in DEPTHS:
        ident=f'OPT_FIFO_A_P{depth}'
        cfg=json.loads(json.dumps(base));cfg.update(id=ident,derived_from='OPT_1_STREAMING')
        cfg['hls']['profiling_depth']=depth
        config_dir=root/'configs'/ident;config_dir.mkdir()
        save(config_dir/'iteration.json',cfg)
        (config_dir/'model_config.json').write_bytes((ITERATIONS/'OPT_3_BRAM_FIFO_A/model_config.json').read_bytes())
        point={'id':ident,'depth':depth,'config':str(config_dir/'iteration.json')}
        if depth==100000:
            actual=verify_inputs(A)
            for k in ['model','hls','interface']:
                if actual[k]!=base[k]:raise ValueError('Current A cannot serve as the 100000-depth reference')
            point.update(job=str(A),external=True,reuses='OPT_3_BRAM_FIFO_A')
        points.append(point)
    cfg=read(ITERATIONS/'OPT_1_STREAMING/iteration.json');cfg['build']['routed']=True
    config_dir=root/'configs/OPT_1_STREAMING';config_dir.mkdir()
    save(config_dir/'iteration.json',cfg)
    (config_dir/'model_config.json').write_bytes((ITERATIONS/'OPT_1_STREAMING/model_config.json').read_bytes())
    points.append({'id':'OPT_1_STREAMING','depth':None,'config':str(config_dir/'iteration.json')})
    points.append({'id':'OPT_2_DSP_RESOURCES_B2','depth':None,'job':str(B2),'external':True})
    for point in points:
        p=root/'points'/point['id'];p.mkdir()
        if not point.get('external'):
            job=root/point['id']/'attempt_01'
            snapshot(Path(point['config']),job);point['job']=str(job)
        save(p/'state.json',{'status':'pending','stage':'profile','job':point['job']})
    config={'schema':1,'points':points,'depths':DEPTHS,'implementation_lock':str(CAMPAIGN/'implementation.lock'),
            'external_jobs':[str(A),str(B2)],'max_hls_workers':2,'implementation_threads':4,
            'results':str(HERE.parent/'reports/optimizations/fifo_sweep'/root.name),
            'board_operations':False,'automatic_builds':True,'created_at':time.time(),
            'toolchain':'2024.2','samples':2}
    save(root/'sweep.json',config)
    save(root/'tooling_manifest.json',{str(p.relative_to(HERE)):sha(p) for p in HERE.glob('*.py')})
    save(root/'status.json',{'status':'prepared','stage':'prepared','board_operations':False})
    print(root,flush=True)


def require_tooling(root):
    for name,digest in read(root/'tooling_manifest.json').items():
        if sha(HERE/name)!=digest:raise ValueError('Sweep tooling changed: '+name+'; create a new sweep or explicitly refresh before launch')


def profile_point(root,point):
    folder=root/'points'/point['id'];job=Path(point['job'])
    if not point.get('external') and not (folder/'profile.json').exists():execute(root,point,'profile')
    data=profile_summary(job);save(folder/'profile.json',data)
    if point.get('depth') and data['profiling_depth']!=point['depth']:raise ValueError('Profile depth mismatch')
    save(folder/'state.json',{'status':'profiled','stage':'profile_complete','job':str(job),
                             'fingerprint':data['fingerprint'],'finished_at':time.time()})
    event(root,point['id'],'profile','passed',data.get('interpretation','baseline'))
    return data


def execute(root,point,phase):
    folder=root/'points'/point['id'];job=Path(point['job'])
    previous=load(folder/'state.json')
    if previous.get('stage')==phase and alive(previous.get('pid'),str(job)):
        # A controller restart must adopt the existing worker, never reset its
        # status or launch another process against the same attempt.
        while alive(previous['pid'],str(job)):
            previous.update(heartbeat=time.time(),reattached=True,
                            worker_stage=load(job/'status.json').get('stage'))
            save(folder/'state.json',previous);time.sleep(10)
        result=load(job/'status.json')
        if result.get('status')!='passed':raise RuntimeError('Reattached worker failed: '+str(job))
        return result
    env=dict(os.environ,HLS4ML_IMPLEMENTATION_LOCK=read(root/'sweep.json')['implementation_lock'],
             PYTHONUNBUFFERED='1')
    command=[sys.executable,str(job/'tooling/iteration_worker.py'),str(job),phase]
    log=folder/(phase+'.log')
    with log.open('a') as output:
        child=subprocess.Popen(command,cwd=REPO,env=env,stdout=output,stderr=subprocess.STDOUT,start_new_session=True)
        state={'status':'running','stage':phase,'pid':child.pid,'job':str(job),'started_at':time.time()}
        save(folder/'state.json',state)
        # Native conversion has its own six-hour process-group watchdog. Other
        # stages are observed; do not classify zero completed frames as a stall.
        while child.poll() is None:
            progress=load(job/'status.json')
            state.update(heartbeat=time.time(),worker_stage=progress.get('stage'))
            save(folder/'state.json',state);time.sleep(10)
        if child.returncode:raise RuntimeError(f'{phase} exited {child.returncode}: {log}')
    return load(job/'status.json')


def recover(root,point):
    job=Path(point['job']);output=job/'recovery/route_01'
    if output.exists():
        state=load(output/'status.json')
        if state.get('status')=='passed':return
        raise RuntimeError('Bounded timing recovery already attempted; diagnosis required')
    env=dict(os.environ,HLS4ML_IMPLEMENTATION_LOCK=read(root/'sweep.json')['implementation_lock'])
    with (root/'points'/point['id']/'recovery.log').open('w') as log:
        child=subprocess.Popen([sys.executable,str(HERE/'iteration_recover.py'),str(job),'--output',str(output)],
                               cwd=REPO,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        while child.poll() is None:
            save(root/'points'/point['id']/'state.json',{'status':'running','stage':'timing_recovery',
                 'pid':child.pid,'job':str(job),'heartbeat':time.time()});time.sleep(10)
        if child.returncode:raise RuntimeError('Timing recovery failed; inspect '+str(output))


def finish_artifacts(root,point):
    job=Path(point['job']);folder=root/'points'/point['id']
    result=artifact_summary(job)
    save(folder/'artifacts.json',result);save(folder/'hls_estimates.json',hls_estimates(job))
    save(folder/'state.json',{'status':'passed','stage':'build_complete','job':str(job),'finished_at':time.time()})
    event(root,point['id'],'build','passed','Timing and RTL gates passed. No board programming.')


def build_point(root,point):
    folder=root/'points'/point['id'];job=Path(point['job'])
    if point.get('external'):
        while True:
            state=load(job/'status.json')
            recoveries=sorted(job.glob('recovery/route_*/status.json'))
            if recoveries:state=load(recoveries[-1])
            if state.get('status')=='passed':break
            if state.get('status') in ('failed','blocked'):
                raise RuntimeError('Existing attempt/recovery failed: '+state.get('error','inspect original logs'))
            if not alive(state.get('pid'),str(job)):
                raise RuntimeError('Existing worker disappeared; original artifacts left untouched')
            save(folder/'state.json',{'status':'running','stage':'waiting_existing_build','job':str(job),
                 'heartbeat':time.time(),'worker_stage':state.get('stage')});time.sleep(20)
    else:
        execute(root,point,'validate')
        event(root,point['id'],'validation','passed')
        save(folder/'hls_estimates.json',hls_estimates(job))
        try:execute(root,point,'build')
        except RuntimeError:
            if 'Timing failure:' not in load(job/'status.json').get('error',''):raise
            recover(root,point)
    finish_artifacts(root,point)


def guarded(root,point,phase):
    try:
        return profile_point(root,point) if phase=='profile' else build_point(root,point)
    except Exception as error:
        save(root/'points'/point['id']/'state.json',{'status':'failed','stage':phase,'job':point['job'],
             'error':str(error),'finished_at':time.time()})
        event(root,point['id'],phase,'failed',str(error));return None


def external_hls(config):
    count=0
    for path in config['external_jobs']:
        job=Path(path);s=load(job/'status.json')
        if s.get('status')=='running' and alive(s.get('pid'),str(job)) and s.get('stage') not in {
                'waiting_implementation_lock','synth','link','shell','bitgen','timing_check','complete'}:count+=1
    return count


def dispatch(root,points,phase,state):
    config=read(root/'sweep.json');pending=list(points);running={}
    with ThreadPoolExecutor(max_workers=2) as pool:
        while pending or running:
            # Existing A has priority for HLS/simulation capacity. Waiting external
            # comparators are checked separately rather than occupying worker slots.
            capacity=max(0,2-external_hls(config))
            while pending and len(running)<capacity:
                point=pending.pop(0);running[pool.submit(guarded,root,point,phase)]=point
            for future in list(running):
                if future.done():future.result();del running[future]
            state.update(heartbeat=time.time(),stage=phase,active=[p['id'] for p in running.values()],
                         queued=[p['id'] for p in pending]);save(root/'status.json',state)
            if pending or running:time.sleep(10)


def run(root,until):
    retired=load(root/'status.json')
    if retired.get('status')=='superseded':
        raise RuntimeError('Sweep dispatch retired; resume selected campaign: '+retired['superseded_by'])
    with (root/'supervisor.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        require_tooling(root)
        config=read(root/'sweep.json');old=load(root/'status.json')
        if old.get('status')=='running' and alive(old.get('pid'),'fifo_sweep.py'):
            raise RuntimeError('Another sweep supervisor is active')
        started=old.get('started_at',time.time())
        state={'status':'running','stage':'profile','pid':os.getpid(),'started_at':started,
               'heartbeat':time.time(),'until':until,'board_operations':False}
        save(root/'status.json',state)
        pending=[]
        for p in config['points']:
            folder=root/'points'/p['id'];s=load(folder/'state.json')
            if s.get('status')=='failed':continue  # failures require a new explicit attempt
            if p.get('external'):
                if not (folder/'profile.json').exists():guarded(root,p,'profile')
            elif not (folder/'profile.json').exists():pending.append(p)
            else:profile_summary(Path(p['job']))  # verify evidence on resume
        dispatch(root,pending,'profile',state)
        # Prefer the existing A image when another profile yields the same design.
        order=sorted(config['points'],key=lambda p:(not p.get('external'),DEPTHS.index(p['depth']) if p.get('depth') else 99))
        seen={};builds=[];external=[]
        for p in order:
            folder=root/'points'/p['id'];s=load(folder/'state.json')
            if s.get('status')=='failed' or not (folder/'profile.json').exists():continue
            key=load(folder/'profile.json')['fingerprint']
            if key in seen:
                save(folder/'state.json',{'status':'duplicate','stage':'deduplicated','alias_of':seen[key],
                     'job':p['job'],'fingerprint':key});continue
            seen[key]=p['id']
            if s.get('status')=='passed':continue
            (external if p.get('external') else builds).append(p)
        if until=='build':
            # Follow the two incumbents without taking either of the HLS slots.
            with ThreadPoolExecutor(max_workers=2) as followers:
                watches=[followers.submit(guarded,root,p,'build') for p in external]
                dispatch(root,builds,'build',state)
                while any(not f.done() for f in watches):
                    state.update(stage='waiting_existing_builds',heartbeat=time.time());save(root/'status.json',state);time.sleep(20)
                for f in watches:f.result()
        statuses={p['id']:load(root/'points'/p['id']/'state.json').get('status') for p in config['points']}
        state.update(status='failed' if 'failed' in statuses.values() else 'passed',stage='complete',
                     outcomes=statuses,finished_at=time.time(),heartbeat=time.time())
        save(root/'status.json',state);event(root,'campaign',until,state['status'])
        write_results(root)
        return int(state['status']!='passed')


def write_results(root):
    python=REPO/'ml_baseline/.venv_hls4ml/bin/python'
    with (root/'logs/results.log').open('a') as log:
        return subprocess.call([str(python),str(HERE/'fifo_sweep.py'),'summarize',str(root)],stdout=log,stderr=subprocess.STDOUT)


def inspect(root):
    now=time.time();config=read(root/'sweep.json')
    data={'at':now,'campaign':load(root/'status.json'),'points':{},'existing':{}}
    for p in config['points']:
        job=Path(p['job'])
        data['points'][p['id']]={'sweep':load(root/'points'/p['id']/'state.json'),'worker':load(job/'status.json')}
    for name,path in [('A',A),('B2',B2/'recovery/route_01')]:
        s=load(path/'status.json');s['process_alive']=alive(s.get('pid'),str(path if name=='A' else B2))
        data['existing'][name]=s
    mem={line.split(':')[0]:line.split(':')[1].strip() for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith(('MemAvailable:','SwapFree:'))}
    data['memory']=mem
    data['processes']=subprocess.check_output(['ps','-eo','pid,ppid,rss,pcpu,etime,comm'],text=True).splitlines()
    data['processes']=[r for r in data['processes'] if any(x in r for x in ['PID','xsim','xelab','vivado','vitis_hls','cc1plus'])]
    save(root/'inspections/latest.json',data)
    with (root/'inspections/history.jsonl').open('a') as f:f.write(json.dumps(data)+'\n')
    return data


def monitor(root):
    with (root/'monitor.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        book=load(root/'monitor.json',{'delivered':[]});book.update(pid=os.getpid(),status='running')
        book.setdefault('delivered',[])
        last_inspect=0;last_summary=0;attempted={};absent_since=None
        event(root,'monitor','attached','running','Profiles and builds only; first-hour observation enabled.')
        while True:
            state=load(root/'status.json');now=time.time()
            if now-last_inspect>=60:inspect(root);last_inspect=now
            if now-last_summary>=300:write_results(root);last_summary=now
            if state.get('status')=='running' and not alive(state.get('pid'),'fifo_sweep.py'):
                if absent_since is None:absent_since=now
                if now-absent_since>=60:
                    event(root,'campaign','supervisor_'+str(state.get('pid')),'failed',
                          'Supervisor absent for at least 60 seconds; inspect child workers before restarting.')
            else:absent_since=None
            if state.get('started_at') and now-state['started_at']>=3600:
                event(root,'monitor','first_hour','complete','First-hour inspection log saved; termination monitoring continues.')
            pending=False
            for path in sorted((root/'events').glob('*.json')):
                if path.name in book['delivered']:continue
                pending=True
                if now-attempted.get(path.name,0)<60:continue
                attempted[path.name]=now
                if send(root,read(path)):book['delivered'].append(path.name)
            book.update(heartbeat=now,first_hour_complete=bool(state.get('started_at') and now-state['started_at']>=3600))
            save(root/'monitor.json',book)
            if state.get('status') in TERMINAL and not pending:
                book['status']='complete';save(root/'monitor.json',book);return
            time.sleep(20)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['init','run','monitor','status','inspect','summarize'])
    parser.add_argument('root',type=Path)
    parser.add_argument('--until',choices=['profile','build'],default='build')
    args=parser.parse_args();root=args.root.resolve()
    if args.action=='init':initialize(root)
    elif args.action=='run':raise SystemExit(run(root,args.until))
    elif args.action=='monitor':monitor(root)
    elif args.action=='status':print(json.dumps({'campaign':load(root/'status.json'),
        'points':{p['id']:load(root/'points'/p['id']/'state.json') for p in read(root/'sweep.json')['points']}},indent=2))
    elif args.action=='inspect':print(json.dumps(inspect(root),indent=2))
    else:
        from fifo_sweep_results import summarize
        summarize(root)
