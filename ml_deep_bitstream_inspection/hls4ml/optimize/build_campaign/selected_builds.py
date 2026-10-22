#!/usr/bin/env python3
"""Selected build-only campaign. Independent primary and non-streaming supervisors."""
import argparse, concurrent.futures, fcntl, json, os, shutil, subprocess, sys, time
from pathlib import Path
from prepare import HERE, REPO, sha
from worker import save
from implementation_permits import alive
from fifo_sweep_results import artifact_summary, profile_summary, verify_inputs

TERMINAL={'passed','failed','blocked'}

def load(path):return json.loads(path.read_text()) if path.exists() else {}

def verify_controller(root):
    for name,digest in load(root/'controller_manifest.json').items():
        if sha(root/name)!=digest:raise RuntimeError('Campaign controller changed: '+name)

def setup(root):
    from iteration_prepare import snapshot, ITERATIONS
    root.mkdir(parents=True,exist_ok=True)
    if (root/'campaign.json').exists():raise FileExistsError('Campaign already configured')
    runs=REPO/'hls4ml/optimize/runs';sweep=runs/'native_fifo_sweep_20261011';old=runs/'configurable_streaming_20261010'
    existing={
        'OPT_1_STREAMING':sweep/'OPT_1_STREAMING/attempt_01',
        'OPT_2_DSP_RESOURCES_B2':old/'OPT_2_DSP_RESOURCES_B2/attempt_01',
        'OPT_3_BRAM_FIFO_A':old/'OPT_3_BRAM_FIFO_A/attempt_03',
        'OPT_FIFO_A_P1024':sweep/'OPT_FIFO_A_P1024/attempt_01',
        'OPT_FIFO_A_P16384':sweep/'OPT_FIFO_A_P16384/attempt_01',
        'OPT_4_DSP_B2_CONV34_RF72':runs/'b2_conv34_rf72_20261012/OPT_4_DSP_B2_CONV34_RF72/attempt_01'}
    jobs=[];legacy=[]
    for ident,job in existing.items():
        c=verify_inputs(job);profile=profile_summary(job)
        # Seal the existing generated manifest before scheduling; never reprofile.
        for name,digest in load(job/'generated_manifest.json').items():
            if sha(job/name)!=digest:raise RuntimeError('Changed generated cache: '+name)
        record={'id':ident,'job':str(job),'lane':'primary','config_sha256':sha(job/'config/iteration.json'),
                'profile_fingerprint':profile['fingerprint']}
        state=load(job/'status.json')
        if (job/'artifact_manifest.json').exists():artifact_summary(job);record['already_built']=True
        elif alive(state.get('pid'),str(job)):
            record['adopt_pid']=state['pid'];legacy.append({'pid':state['pid'],'job':str(job)})
        jobs.append(record)
    for ident in ['OPT_5_DSP_B2_RF72_RF288','OPT_0_NONSTREAMING']:
        job=root/ident/'attempt_01';snapshot(ITERATIONS/ident/'iteration.json',job)
        jobs.append({'id':ident,'job':str(job),'lane':'nonstreaming' if ident=='OPT_0_NONSTREAMING' else 'primary',
                     'config_sha256':sha(job/'config/iteration.json')})
    controller=root/'controller';controller.mkdir()
    for p in HERE.glob('*.py'):shutil.copy2(p,controller/p.name)
    shutil.copytree(HERE/'implementation',controller/'implementation')
    save(root/'controller_manifest.json',{str(p.relative_to(root)):sha(p) for p in controller.rglob('*') if p.is_file()})
    permits=root/'permits';permits.mkdir();save(permits/'legacy.json',legacy)
    excluded=[f'OPT_FIFO_A_P{n}' for n in [4096,65536,262144]]
    config={'created_at':time.time(),'jobs':jobs,'not_selected':excluded,'implementation_slots':{'primary':3,'nonstreaming':1},
            'implementation_threads':4,'board_operations':False,'profiling_repeated':False,
            'legacy_shared_lock':str(old/'implementation.lock'),'report':str(REPO/'hls4ml/optimize/reports/optimizations/build_current_results_report.py')}
    save(root/'campaign.json',config)
    previous=load(sweep/'status.json');save(root/'previous_sweep_status.json',previous)
    save(sweep/'status.json',{**previous,'status':'superseded','stage':'selected build campaign','superseded_by':str(root),
                             'queued':[],'active':[],'not_selected':excluded,'heartbeat':time.time()})
    for ident in excluded:
        p=sweep/'points'/ident/'state.json';before=load(p)
        save(root/(ident+'_previous_state.json'),before)
        save(p,{**before,'status':'not_selected','build_selection':'not_selected','reason':'User narrowed routed builds; cached profiling retained','at':time.time()})
    return config


def selected(config,lane):return [r for r in config['jobs'] if r['lane']==lane and r['id'] not in config['not_selected']]

def execute(root,row):
    job=Path(row['job']);record=root/'jobs'/(row['id']+'.json');state=load(record)
    def update(**kw):
        state.update(id=row['id'],job=str(job),lane=row['lane'],heartbeat=time.time(),**kw);save(record,state)
    try:
        verify_controller(root)
        if sha(job/'config/iteration.json')!=row['config_sha256']:raise RuntimeError('Selected configuration changed')
        verify_inputs(job)
        if row.get('profile_fingerprint') and profile_summary(job)['fingerprint']!=row['profile_fingerprint']:
            raise RuntimeError('Cached profile mismatch')
        if (job/'artifact_manifest.json').exists():
            artifact_summary(job);update(status='passed',stage='complete',finished_at=time.time());return
        previous=load(record);pid=previous.get('worker_pid',row.get('adopt_pid',load(job/'status.json').get('pid')))
        if alive(pid,str(job)):
            update(status='running',stage='adopting worker',worker_pid=pid)
            while alive(pid,str(job)):
                worker=load(job/'status.json');update(stage=worker.get('stage','running'));time.sleep(20)
            # A stopped worker is never blindly rerun over existing HLS/RTL output.
            if (job/'artifact_manifest.json').exists():
                artifact_summary(job);update(status='passed',stage='complete',finished_at=time.time());return
            stage=load(job/'status.json')
            if stage.get('timing')!='failed':raise RuntimeError('Adopted worker stopped: '+stage.get('error',str(stage)))
        else:
            stage=load(job/'status.json')
            if previous.get('status') in TERMINAL:raise RuntimeError('Previous selected attempt failed; review before retry')
            if previous.get('worker_pid'):raise RuntimeError('Worker disappeared; inspect partial outputs before restarting')
            update(status='running',stage='starting')
            env=os.environ.copy();env.update(HLS4ML_IMPLEMENTATION_PERMITS=str(root/'permits'),HLS4ML_IMPLEMENTATION_LANE=row['lane'])
            with (job/'selected_worker.log').open('a') as log:
                process=subprocess.Popen([sys.executable,str(root/'controller/iteration_worker.py'),str(job),'build'],
                         env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            update(worker_pid=process.pid)
            while process.poll() is None:
                update(stage=load(job/'status.json').get('stage','starting'));time.sleep(20)
            stage=load(job/'status.json')
        if not (job/'artifact_manifest.json').exists() and stage.get('timing')=='failed':
            env=os.environ.copy();env.update(HLS4ML_IMPLEMENTATION_PERMITS=str(root/'permits'),HLS4ML_IMPLEMENTATION_LANE=row['lane'])
            output=job/'recovery/selected_route_01'
            if output.exists():raise RuntimeError('Recovery already attempted; inspect before retry')
            with (job/'selected_recovery.log').open('a') as log:
                process=subprocess.Popen([sys.executable,str(root/'controller/iteration_recover.py'),str(job),'--output',str(output)],
                    env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            update(stage='recovery',worker_pid=process.pid,recovery=str(output))
            while process.poll() is None:
                update(stage='recovery: '+load(output/'status.json').get('stage','starting'));time.sleep(20)
        artifact_summary(job)
        update(status='passed',stage='complete',finished_at=time.time())
    except Exception as error:update(status='failed',error=str(error),finished_at=time.time())


def run(root,lane):
    verify_controller(root);config=load(root/'campaign.json');rows=selected(config,lane)
    (root/'jobs').mkdir(exist_ok=True)
    with (root/(lane+'.lock')).open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        state={'status':'running','lane':lane,'pid':os.getpid(),'started_at':time.time(),'board_operations':False}
        # Non-build work is independent; only implementation stages acquire permits.
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(rows)) as pool:
            futures=[pool.submit(execute,root,row) for row in rows]
            while not all(f.done() for f in futures):
                state.update(heartbeat=time.time(),jobs={r['id']:load(root/'jobs'/(r['id']+'.json')) for r in rows})
                save(root/(lane+'.json'),state);time.sleep(20)
            for future in futures:future.result()
        state.update(status='passed' if all(load(root/'jobs'/(r['id']+'.json')).get('status')=='passed' for r in rows) else 'failed',
                     finished_at=time.time(),heartbeat=time.time(),jobs={r['id']:load(root/'jobs'/(r['id']+'.json')) for r in rows})
        save(root/(lane+'.json'),state)


def monitor(root,lane):
    config=load(root/'campaign.json');rows=selected(config,lane);sent=load(root/(lane+'_notified.json'))
    from iteration_monitor import send
    with (root/(lane+'_monitor.lock')).open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        while True:
            state=load(root/(lane+'.json'));events=[]
            for row in rows:
                result=load(root/'jobs'/(row['id']+'.json'))
                if result.get('status') in TERMINAL and not row.get('already_built'):
                    events.append((row['id'],result['status'],result.get('error','correctness, timing and bitstream complete')))
            terminal=state.get('status') in TERMINAL
            if terminal:events.append((lane+' queue',state['status'],'Selected builds finished. '+str(root)))
            elif state and not alive(state.get('pid'),'selected_builds.py'):
                events.append((lane+' controller','stopped','Controller stopped unexpectedly; existing workers may still be active. '+str(root)))
            for ident,outcome,detail in events:
                key=ident+':'+outcome
                if key not in sent:
                    event={'id':ident,'outcome':outcome,'message':f'hls4ml {ident}: {outcome}. {detail}. Builds only; no board programming.'}
                    if send(root,event):sent[key]=time.time();save(root/(lane+'_notified.json'),sent)
            save(root/(lane+'_monitor.json'),{'status':'complete' if terminal else 'monitoring','pid':os.getpid(),'heartbeat':time.time()})
            if terminal and all(ident+':'+outcome in sent for ident,outcome,_ in events):return
            time.sleep(30)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('command',choices=['setup','run','monitor']);p.add_argument('root',type=Path);p.add_argument('--lane',choices=['primary','nonstreaming'],default='primary');a=p.parse_args();root=a.root.resolve()
    if a.command=='setup':setup(root)
    elif a.command=='run':run(root,a.lane)
    else:monitor(root,a.lane)
