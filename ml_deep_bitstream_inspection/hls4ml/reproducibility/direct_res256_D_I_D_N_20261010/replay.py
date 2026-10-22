#!/usr/bin/env python3
"""D_I/D_N/R_S checkpoint commands. No hardware operation is implicit in verify."""
import argparse,csv,fcntl,json,os,shlex,shutil,signal,socket,subprocess,sys,time
from pathlib import Path
sys.dont_write_bytecode=True
PACKAGE=Path(__file__).resolve().parent
sys.path.insert(0,str(PACKAGE/'scripts'))
from board_benchmark import sha,save


def verify():
    manifest=json.loads((PACKAGE/'manifest.json').read_text())
    for name,record in manifest['files'].items():
        p=PACKAGE/name
        if p.is_symlink() or not p.is_file() or p.stat().st_size!=record['bytes'] or sha(p)!=record['sha256']:
            raise ValueError('Missing/changed packaged file: '+name)
    identities=json.loads((PACKAGE/'identities.json').read_text())
    for variant,identity in identities.items():
        if sha(PACKAGE/identity['bitstream'])!=identity['bitstream_sha256']:
            raise ValueError('Measured image identity changed')
        if variant=='R_S':
            records=[json.loads(line) for line in (PACKAGE/'results/benchmarks/R_S/full.jsonl').read_text().splitlines()]
        else:
            records=list(csv.DictReader((PACKAGE/'results/benchmarks'/variant/'full.csv').open()))
        if len(records)!=2640 or sum(int(r['warmup']) for r in records)!=240:
            raise ValueError('Incomplete saved trial set: '+variant)
        if {str(r['variant']) for r in records}!={str(identity['variant_id'])}:
            raise ValueError('Wrong saved variant')
        groups={r['case_id'] for r in records}
        if len(groups)!=12:raise ValueError('Wrong saved size grid')
        for ident in groups:
            block=[r for r in records if r['case_id']==ident]
            if len(block)!=220 or sum(int(r['warmup']) for r in block)!=20:
                raise ValueError('Incomplete saved size block: '+ident)
    files=json.loads((PACKAGE/'inputs/files.json').read_text())
    import hashlib
    for digest,c in files.items():
        recipe=c['recipe']
        if recipe['kind']=='file':
            path=PACKAGE/recipe['path']
            actual=sha(path)
            if path.stat().st_size!=c['bytes']:raise ValueError('Input length mismatch')
        else:
            seed=(PACKAGE/files[recipe['seed_sha256']]['recipe']['path']).read_bytes()
            remaining=c['bytes'];h=hashlib.sha256()
            while remaining:
                part=seed[:remaining];h.update(part);remaining-=len(part)
            actual=h.hexdigest()
        if actual!=digest:raise ValueError('Packaged input/recipe mismatch: '+digest)
    total=0
    for name in ['sequential','alternating_a','alternating_b']:
        path=PACKAGE/'results/parity'/('runtime_D_I_admission_01_'+name)/'observations.csv'
        total+=sum(1 for _ in csv.DictReader(path.open()))
    if total!=520:raise ValueError('Incomplete historical D_I admission')
    rs_gate=[json.loads(line) for line in (PACKAGE/'results/benchmarks/R_S/gate.jsonl').read_text().splitlines()]
    if len(rs_gate)!=260 or any(r['validation']!='passed' for r in rs_gate):
        raise ValueError('Incomplete historical R_S admission')
    print('Verified',len(manifest['files']),'files; no hardware operations')


def output_root(path):
    root=Path(path).expanduser().resolve()
    if root==PACKAGE or root.is_relative_to(PACKAGE):raise ValueError('Outputs must be outside the immutable package')
    return root


def inputs(root):
    """Materialize a relocatable grid with byte-identical deterministic payloads."""
    root.mkdir(parents=True,exist_ok=True)
    records=json.loads((PACKAGE/'inputs/files.json').read_text())
    paths={}
    for digest,c in records.items():
        recipe=c['recipe']
        if recipe['kind']=='file':p=PACKAGE/recipe['path']
        else:
            seed=PACKAGE/records[recipe['seed_sha256']]['recipe']['path']
            p=root/'inputs'/(digest+'.bin');p.parent.mkdir(exist_ok=True)
            if not p.exists():
                raw=seed.read_bytes();remaining=c['bytes']
                with p.open('xb') as stream:
                    while remaining:
                        part=raw[:remaining];stream.write(part);remaining-=len(part)
        if p.stat().st_size!=c['bytes'] or sha(p)!=digest:raise ValueError('Input mismatch: '+digest)
        paths[digest]=str(p)
    grid=json.loads((PACKAGE/'inputs/grid.json').read_text())
    for group in ['cases','smoke','runtime_cases','alternating_1','alternating_2']:
        for c in grid[group]:c['path']=paths[c['sha256']]
    save(root/'inputs.json',grid)
    grid['pilot']=[c for c in grid['cases'] if c['bytes'] in (4194304,134217664)]
    for group in ['cases','smoke','pilot','runtime_cases','alternating_1','alternating_2']:
        with (root/(group+'.tsv')).open('w') as stream:
            for c in grid[group]:stream.write('\t'.join(str(c[k]) for k in ['id','sweep','path','bytes','sha256','expected_logit_hex'])+'\n')
    shutil.copy2(PACKAGE/'inputs/production_tolerances.json',root/'production_tolerances.json')
    return grid


def software(root,variant):
    from rebuild import command
    root.mkdir(parents=True,exist_ok=True)
    runtime=root/'software/runtime_build';runtime.mkdir(parents=True,exist_ok=True)
    source=PACKAGE/'sources/production_runtime' if variant=='R_S' else PACKAGE/'sources/runtime'
    sw=PACKAGE/'sources/coyote/sw'
    if variant=='R_S' and (PACKAGE/'sources/coyote_R_S_overlay/sw').exists():
        sw=root/'software/coyote_sw';shutil.copytree(PACKAGE/'sources/coyote/sw',sw)
        shutil.copytree(PACKAGE/'sources/coyote_R_S_overlay/sw',sw,dirs_exist_ok=True)
    command(['cmake','-S',source,'-B',runtime,'-DCOYOTE_SW='+str(sw),'-DCMAKE_BUILD_TYPE=Release'],root,root/'runtime_configure.log')
    command(['cmake','--build',runtime,'--parallel','4'],root,root/'runtime_build.log')
    driver=root/'software/driver'
    shutil.copytree(PACKAGE/'sources/driver',driver)
    command(['make'],driver,root/'driver_build.log',dict(os.environ,PWD=str(driver)))
    if variant=='R_S':
        project=root/'software/production_project/build/prod_res256_manualA_coyote_accel_cyt_sw'
        (project/'lib').mkdir(parents=True)
        (project/'lib/libCoyoteInference.so').symlink_to(runtime/'lib/libCoyoteInference.so')
        (project/'libCoyote.so').symlink_to(runtime/'coyote/libcoyote.so')


def process(args,root,name,limit=900):
    """Preserve terminal for sudo; terminate the entire subprocess group on errors."""
    log=root/(name+'.log')
    with log.open('w') as stream:
        p=subprocess.Popen(list(map(str,args)),stdout=stream,stderr=subprocess.STDOUT,preexec_fn=os.setpgrp)
        try:
            rc=p.wait(timeout=limit)
            if rc:raise RuntimeError(f'{name} failed ({rc}); {log}')
        except BaseException:
            if p.poll() is None:
                os.killpg(p.pid,signal.SIGTERM)
                try:p.wait(timeout=5)
                except subprocess.TimeoutExpired:os.killpg(p.pid,signal.SIGKILL);p.wait()
            raise


def selection(args):
    if args.build_root:
        identity=json.loads((Path(args.build_root).resolve()/args.variant/'identity.json').read_text())
        if identity.get('status')!='passed':raise ValueError('Build did not pass')
        return identity
    identity=json.loads((PACKAGE/'identities.json').read_text())[args.variant]
    return dict(identity,bitstream=str(PACKAGE/identity['bitstream']))


def board_preflight(root,config,identity):
    if socket.getfqdn()!=config['hostname']:raise ValueError('Board host differs from explicit configuration')
    if config.get('standard_driver') is not True:raise ValueError('Standard reset-enabled driver required')
    if config['cpu'] not in os.sched_getaffinity(0):raise ValueError('Configured CPU is unavailable')
    driver=root/'software/driver/build/coyote_driver.ko'
    kernel=os.uname().release
    vermagic=subprocess.check_output(['modinfo','-F','vermagic',str(driver)],text=True)
    if not vermagic.startswith(kernel+' '):raise ValueError('Driver/kernel mismatch; run software command')
    devices=list(Path('/dev').glob('coyote*'))
    if devices and subprocess.run(['fuser',*map(str,devices)],capture_output=True).returncode!=1:raise RuntimeError('Coyote device in use or ownership check failed')
    bit=Path(identity['bitstream'])
    if sha(bit)!=identity['bitstream_sha256']:raise ValueError('Image identity mismatch')
    return driver,bit


def program(root,config,identity,variant):
    driver,bit=board_preflight(root,config,identity)
    save(root/'installed_image.json',dict(status='programming',job=variant))
    process(['bash',PACKAGE/'scripts/program_hacc_local.sh',bit,driver,config['device']],root,'program_'+variant)
    pci=Path('/sys/bus/pci/devices')/config['bdf']
    if int((pci/'current_link_width').read_text())!=16 or not (pci/'current_link_speed').read_text().startswith('8.0 GT/s'):
        raise ValueError('Expected PCIe Gen3 x16 after programming')
    image=dict(status='ready',job=variant,bitstream=str(bit),sha256=sha(bit),driver=str(driver),driver_sha256=sha(driver),source_manifest_sha256=identity['source_manifest_sha256'],reset_diagnostic=False)
    save(root/'installed_image.json',image)
    return image


def collect(root,dest,config,variant,cases,trials,warmups):
    dest.mkdir(parents=True,exist_ok=False)
    process(['numactl','--physcpubind='+str(config['cpu']),'--membind='+str(config['numa_node']),sys.executable,
             PACKAGE/'scripts/runtime_benchmark.py',root/(cases+'.tsv'),dest/'observations.csv',dest/'clock.csv',
             7 if variant=='D_I' else 8,trials,warmups,'--library',root/'software/runtime_build/libCoyoteInferenceCampaign.so',
             '--tolerances',root/'production_tolerances.json','--image-manifest',root/'installed_image.json'],dest,'collector')


def admit(root,dest,config,variant):
    from board_benchmark import components,clock_model
    from parity_gate import load_tolerances
    grid=json.loads((root/'inputs.json').read_text())
    cases={c['sha256']:c for c in grid['runtime_cases']}
    tolerances=load_tolerances(root/'production_tolerances.json')
    total=0
    for label,trials in [('runtime_cases',10),('alternating_1',1),('alternating_2',1)]:
        out=dest/label;collect(root,out,config,variant,label,trials,0)
        rows=list(csv.DictReader((out/'observations.csv').open()));clocks=list(csv.DictReader((out/'clock.csv').open()))
        expected=len(grid[label])*trials
        if len(rows)!=expected:raise ValueError('Incomplete admission')
        for ident in dict.fromkeys(r['case_id'] for r in rows):
            mapped,detail=clock_model([r for r in clocks if r['case_id']==ident])
            for r in rows:
                if r['case_id']==ident:
                    c=cases[r['input_sha256']]
                    components(r,c,mapped,(detail['ns_per_tick_min']+detail['ns_per_tick_max'])/2,tolerances[c['sha256']] if variant=='D_I' else None)
        total+=len(rows)
    if total!=520:raise ValueError('Expected 520 admission checks')
    library=root/'software/runtime_build/libCoyoteInferenceCampaign.so'
    gate=dict(status='passed',checks=total,image=json.loads((root/'installed_image.json').read_text()),library_sha256=sha(library),coyote_library_sha256=sha(library.parent/'coyote/libcoyote.so'),tolerances_sha256=sha(root/'production_tolerances.json'))
    save(dest/'admission.json',gate)


def board(args,root):
    from board_benchmark import analyze
    from resources import attribute
    config=json.loads(Path(args.config).read_text())
    identity=selection(args)
    inputs(root)
    lock=Path(config['board_lock'])
    if not lock.is_absolute():raise ValueError('board_lock must be an absolute, shared host path')
    with lock.open('a') as lease:
        fcntl.flock(lease,fcntl.LOCK_EX|fcntl.LOCK_NB)
        attempt=root/args.variant/time.strftime('%Y%m%d_%H%M%S');attempt.mkdir(parents=True,exist_ok=False)
        program(root,config,identity,args.variant)
        if args.variant=='R_S':
            from rs_replay import collect
            collect(PACKAGE,root,attempt,config,args.action,process)
            if args.action=='benchmark':
                reports=(Path(args.build_root).resolve()/'R_S/build/reports') if args.build_root else PACKAGE/'artifacts/R_S'
                resources=attribute((reports/'shell_utilization_hierarchical.rpt').read_text(),(reports/'shell_utilization.rpt').read_text(),'R_S')
                save(attempt/'full.resources.json',dict(resources,hardware_identity=identity))
            return
        admit(root,attempt/'admission',config,args.variant)
        if args.action=='validate':return
        # Keep admission and the benchmark under one device lease.
        for mode,cases,trials,warmups in [('smoke','smoke',2,0),('pilot','pilot',10,2),('full','cases',200,20)]:
            raw=attempt/mode;collect(root,raw,config,args.variant,cases,trials,warmups)
            for old,new in [('observations.csv',mode+'.csv'),('clock.csv',mode+'.clock.csv'),('observations.status.json',mode+'.status.json'),('observations.environment.jsonl',mode+'.environment.jsonl')]:
                shutil.copy2(raw/old,attempt/new)
            analyze(root,attempt,mode)
        reports=(Path(args.build_root).resolve()/args.variant/'build/reports') if args.build_root else PACKAGE/'artifacts'/args.variant
        resources=attribute((reports/'shell_utilization_hierarchical.rpt').read_text(),(reports/'shell_utilization.rpt').read_text(),args.variant)
        save(attempt/'full.resources.json',dict(resources,hardware_identity=identity))
        save(attempt/'status.json',dict(status='passed',variant=args.variant,rows=2640))


def analyze_saved(root):
    from board_benchmark import analyze,plots
    inputs(root);attempts=[]
    for variant in ['D_I','D_N']:
        dest=root/variant;shutil.copytree(PACKAGE/'results/benchmarks'/variant,dest)
        for mode in ['smoke','pilot','full']:analyze(root,dest,mode)
        attempts.append(dest)
    plots(root,attempts)
    from rs_replay import analyze_saved as analyze_rs
    analyze_rs(PACKAGE,root)


def notify(root,message):
    p=subprocess.run(['curl','--fail','--silent','--show-error','--connect-timeout','10','--max-time','30','--data-binary',message,'https://ntfy.sh/coyote-build-sdeheredia'],capture_output=True,text=True)
    with (root/'notifications.jsonl').open('a') as f:f.write(json.dumps(dict(time=time.time(),sent=p.returncode==0,message=message))+'\n')
    return p.returncode==0


def launch(args,root):
    root.mkdir(parents=True,exist_ok=True)
    # Dedicated output root per launched job prevents source/output collisions.
    session='checkpoint_'+args.action+'_'+args.variant+'_'+str(int(time.time()))
    command=[sys.executable,str(PACKAGE/'replay.py'),args.action,'--output',str(root),'--variant',args.variant]
    for name in ['config','build_root']:
        value=getattr(args,name,None)
        if value:command+=['--'+name.replace('_','-'),str(Path(value).resolve())]
    save(root/'launch.json',dict(session=session,action=args.action,variant=args.variant,command=command))
    save(root/'job_status.json',dict(status='pending',action=args.action,variant=args.variant))
    subprocess.run(['tmux','new-session','-d','-s',session,'exec '+shlex.join(command)+' > '+shlex.quote(str(root/'job.log'))+' 2>&1'],check=True)
    monitor=[sys.executable,str(PACKAGE/'replay.py'),'monitor','--output',str(root)]
    subprocess.run(['tmux','new-session','-d','-s',session+'_monitor',shlex.join(monitor)],check=True)
    print('Started tmux',session,'and completion monitor')


def monitor(root):
    launch=json.loads((root/'launch.json').read_text());sent=root/'notified.json'
    if sent.exists():return
    while True:
        status=root/'job_status.json'
        state=json.loads(status.read_text()) if status.exists() else {}
        if state.get('status') in ('passed','failed'):
            message=f"{launch['action']} {launch['variant']} {state['status']}: {root}"
        elif subprocess.run(['tmux','has-session','-t',launch['session']],capture_output=True).returncode:
            message=f"{launch['action']} {launch['variant']} terminated unexpectedly: {root}"
        else:time.sleep(10);continue
        if notify(root,message):save(sent,dict(message=message));return
        time.sleep(30)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['verify','prepare','software','build','validate','benchmark','analyze','monitor'])
    parser.add_argument('--output',type=Path)
    parser.add_argument('--variant',choices=['D_I','D_N','R_S'],default='D_I')
    parser.add_argument('--config',type=Path,help='Explicit board host configuration')
    parser.add_argument('--build-root',type=Path,help='Use a fresh rebuild instead of packaged measured images')
    parser.add_argument('--tmux',action='store_true',help='Launch build/benchmark and outcome monitor')
    args=parser.parse_args()
    if args.action=='verify':verify();return
    if not args.output:parser.error('--output is required')
    root=output_root(args.output)
    if args.action=='monitor':monitor(root);return
    verify()
    if args.action in ('validate','benchmark') and not args.config:parser.error('--config is required')
    if args.tmux:
        if args.action not in ('build','benchmark'):parser.error('--tmux is for actual builds or benchmarks only')
        if (root/'launch.json').exists():raise ValueError('Use a fresh launch output root')
        launch(args,root);return
    root.mkdir(parents=True,exist_ok=True)
    state=dict(status='running',action=args.action,variant=args.variant,pid=os.getpid(),started_at=time.time())
    save(root/'job_status.json',state)
    def stop(signum,frame):raise InterruptedError('signal '+str(signum))
    signal.signal(signal.SIGTERM,stop)
    try:
        if args.action=='prepare':inputs(root)
        elif args.action=='software':software(root,args.variant)
        elif args.action=='build':
            if args.variant=='R_S':
                inputs(root)
                from rs_rebuild import build
                build(PACKAGE,root)
            else:
                from rebuild import build
                build(PACKAGE,root,args.variant)
        elif args.action in ('validate','benchmark'):board(args,root)
        elif args.action=='analyze':analyze_saved(root)
        state['status']='passed'
    except BaseException as e:
        state.update(status='failed',error=str(e));raise
    finally:
        state['finished_at']=time.time();save(root/'job_status.json',state)

if __name__=='__main__':main()
