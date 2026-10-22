#!/usr/bin/env python3
"""Sequential, image-bound OPT board admission and benchmarking; explicit board lease."""
import argparse, fcntl, json, os, shlex, shutil, signal, socket, subprocess, sys, time
from pathlib import Path
from board_benchmark import sha, save
from fifo_sweep_results import artifact_summary
from implementation_permits import alive
from iteration_monitor import send
HERE=Path(__file__).resolve().parent
REPO=HERE.parents[2]
ORDER=['OPT_1_STREAMING','OPT_0_NONSTREAMING','OPT_3_BRAM_FIFO_A','OPT_FIFO_A_P1024','OPT_FIFO_A_P16384','OPT_2_DSP_RESOURCES_B2','OPT_4_DSP_B2_CONV34_RF72','OPT_5_DSP_B2_RF72_RF288']

def load(path):return json.loads(path.read_text()) if path.exists() else {}

def verify_tools(root):
    for name,digest in load(root/'campaign.json')['software_files'].items():
        if sha(root/name)!=digest:raise RuntimeError('Changed campaign software: '+name)

def setup(root):
    if root.exists():raise FileExistsError('Fresh benchmark root required')
    root.mkdir(parents=True);(root/'logs').mkdir();(root/'jobs').mkdir();(root/'software').mkdir();tools=root/'tooling';tools.mkdir()
    old=REPO/'hls4ml/optimize/runs/board_benchmark_u55c02_20261009_2345'
    selected=load(REPO/'hls4ml/optimize/runs/selected_builds_20261012/campaign.json');images={}
    for row in selected['jobs']:
        job=Path(row['job']);artifact=artifact_summary(job);c=load(job/'config/iteration.json')
        images[row['id']]=dict(job=str(job),bitstream=artifact['bitstream'],bitstream_sha256=sha(Path(artifact['bitstream'])),
            artifact_manifest_sha256=artifact['artifact_manifest_sha256'],source_manifest_sha256=artifact['source_manifest_sha256'],
            fifo_depth=c['interface']['external_fifo_depth'],pipeline_mode=c['interface'].get('pipeline_mode','streaming'),resources=artifact['resources'])
    for name in ['opt_benchmark.py','opt_benchmark_collect.py','board_benchmark.py','parity_gate.py','prepare.py','worker.py','hbm_clock.py','fifo_sweep_results.py','resource_attribution.py','board_target.py','host_environment.py','implementation_permits.py','iteration_monitor.py']:
        shutil.copy2(HERE/name,tools/name)
    shutil.copy2(REPO/'hls4ml/pipeline/coyote_accelerator/direct_session.py',tools/'direct_session.py')
    shutil.copytree(HERE/'runtime',root/'software/runtime');(root/'software/templates').mkdir()
    shutil.copy2(HERE/'templates/direct_abi.hpp',root/'software/templates/direct_abi.hpp')
    baseline=Path(images['OPT_1_STREAMING']['job']);shutil.copytree(baseline/'coyote/sw',root/'software/coyote_sw')
    driver=root/'software/coyote_driver.ko';shutil.copy2(old/'software/driver/build/coyote_driver.ko',driver)
    shutil.copy2(REPO.parent/'util/program_hacc_local.sh',root/'software/program_hacc_local.sh')
    for name in ['cases.tsv','pilot.tsv']:shutil.copy2(old/name,root/name)
    shutil.copy2(old/'diagnostics/runtime_cases.tsv',root/'admission.tsv')
    lines=(root/'cases.tsv').read_text().splitlines()
    for line in (old/'smoke.tsv').read_text().splitlines():
        fields=line.split('\t')
        if fields[3] in ('4194240','4194241','4194242'):lines.append(line)
    (root/'cases.tsv').write_text('\n'.join(lines)+'\n')
    cfg=dict(schema=1,repo=str(REPO),created_at=time.time(),hostname='hacc-u55c-02.inf.ethz.ch',device=1,pci_bdf='0000:c4:00.0',cpu=2,numa_node=0,
        driver=str(driver),driver_sha256=sha(driver),board_lock=str(old/'board_device.lock'),images=images,
        order=[dict(label=n,id=n) for n in ORDER]+[dict(label='OPT_1_STREAMING_REPEAT',id='OPT_1_STREAMING')],
        warmups=20,trials=200,full_cases=15,exact_logits=True,board_operations=True,software_files={})
    save(root/'campaign.json',cfg)
    print('SETUP',root,flush=True)

def seal(root):
    cfg=load(root/'campaign.json')
    cfg['software_files']={str(p.relative_to(root)):sha(p) for folder in ['tooling','software/runtime','software/templates','software/coyote_sw'] for p in (root/folder).rglob('*') if p.is_file()}
    for p in [root/'software/coyote_driver.ko',root/'software/program_hacc_local.sh',root/'software/runtime_build/libCoyoteInferenceCampaign.so',root/'software/runtime_build/coyote/libcoyote.so',root/'cases.tsv',root/'pilot.tsv',root/'admission.tsv']:
        cfg['software_files'][str(p.relative_to(root))]=sha(p)
    save(root/'campaign.json',cfg)

def run(root):
    cfg=load(root/'campaign.json');verify_tools(root)
    if socket.gethostname()!=cfg['hostname']:raise RuntimeError('Wrong FPGA host')
    driver=Path(cfg['driver']);kernel=os.uname().release
    if not subprocess.check_output(['modinfo','-F','vermagic',str(driver)],text=True).startswith(kernel+' '):raise RuntimeError('Driver kernel mismatch')
    env=dict(os.environ,OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',COYOTE_ALLOC_TYPE='HPF')
    env['PATH']='/tools/Xilinx/Vivado/2024.2/bin:'+env['PATH']
    python=Path(cfg['repo'])/'ml_baseline/.venv_hls4ml/bin/python'
    state=dict(status='running',stage='waiting_board',pid=os.getpid(),started_at=time.time(),heartbeat=time.time())
    save(root/'status.json',state);active=None;jobstate=None
    def update(**kw):
        state.update(heartbeat=time.time(),**kw);save(root/'status.json',state)
        if jobstate is not None:
            jobstate.update(heartbeat=time.time(),stage=state['stage']);save(active/'status.json',jobstate)
    def command(stage,args,limit=1800,terminal=False,cwd=None):
        update(stage=stage,stage_started_at=time.time())
        if terminal:args=['script','--quiet','--return','--command',shlex.join(args),'/dev/null']
        with (active/(stage+'.log')).open('w') as log:
            p=subprocess.Popen(args,cwd=cwd or cfg['repo'],env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            update(child_pid=p.pid)
            try:
                while p.poll() is None:
                    if time.time()-state['stage_started_at']>limit:raise TimeoutError(stage+' exceeded deadline')
                    update();time.sleep(2)
            except BaseException:
                os.killpg(p.pid,signal.SIGTERM)
                try:p.wait(timeout=10)
                except subprocess.TimeoutExpired:os.killpg(p.pid,signal.SIGKILL);p.wait()
                raise
            if p.returncode:raise RuntimeError(stage+' failed: '+str(active/(stage+'.log')))
    def interrupted(signum,frame):raise InterruptedError('Signal '+str(signum))
    signal.signal(signal.SIGTERM,interrupted);signal.signal(signal.SIGINT,interrupted)
    try:
        with (root/'controller.lock').open('a') as controller,Path(cfg['board_lock']).open('a') as lease:
            fcntl.flock(controller,fcntl.LOCK_EX|fcntl.LOCK_NB)
            while True:
                try:fcntl.flock(lease,fcntl.LOCK_EX|fcntl.LOCK_NB);break
                except BlockingIOError:update();time.sleep(10)
            # One lease spans all programming and measurements. Never overlap images.
            for row in cfg['order']:
                label,ident=row['label'],row['id'];folder=root/'jobs'/label;folder.mkdir(exist_ok=True)
                attempts=sorted(folder.glob('attempt_*/status.json'))
                if attempts and load(attempts[-1]).get('status')=='passed':
                    prior=attempts[-1].parent
                    for phase in ('admission','pilot','full'):
                        result=load(prior/phase/'result.json')
                        if result.get('status')!='passed':raise RuntimeError('Incomplete prior benchmark')
                        for name,digest in result['files'].items():
                            if sha(prior/phase/name)!=digest:raise RuntimeError('Changed prior measurement')
                    continue
                active=folder/f'attempt_{len(attempts)+1:02d}';active.mkdir();jobstate=dict(status='running',id=ident,label=label,started_at=time.time())
                update(stage='preflight',active=label,attempt=str(active))
                verify_tools(root);image=cfg['images'][ident];artifact=artifact_summary(Path(image['job']))
                if artifact['artifact_manifest_sha256']!=image['artifact_manifest_sha256']:raise RuntimeError('Selected hardware changed')
                devices=[str(p) for pattern in ('coyote*','xclmgmt*','dri/renderD*') for p in Path('/dev').glob(pattern)]
                if devices and subprocess.run(['fuser',*devices],capture_output=True).returncode!=1:raise RuntimeError('FPGA is in use or ownership check failed')
                save(root/'installed_image.json',dict(status='programming',id=ident))
                command('program',['bash',str(root/'software/program_hacc_local.sh'),image['bitstream'],str(driver),str(cfg['device'])],terminal=True,cwd=str(Path(cfg['repo']).parent/'util'))
                pci=Path('/sys/bus/pci/devices')/cfg['pci_bdf']
                if (pci/'current_link_width').read_text().strip()!='16' or not (pci/'current_link_speed').read_text().startswith('8.0 GT/s'):raise RuntimeError('Unexpected PCIe link')
                if not list(Path('/dev').glob('coyote*')):raise RuntimeError('Coyote device missing after programming')
                save(root/'installed_image.json',dict(status='ready',id=ident,**image,driver_sha256=cfg['driver_sha256'],reset_diagnostic=False,installed_at=time.time()))
                # The standard driver performs the second reset after configuration/startup idle.
                for mode in ['admission','pilot','full']:
                    command(mode,['numactl','--physcpubind=2','--membind=0',str(python),str(root/'tooling/opt_benchmark_collect.py'),str(root),ident,str(active/mode),mode],limit=3600)
                    if load(active/mode/'result.json').get('status')!='passed':raise RuntimeError('Missing '+mode+' evidence')
                jobstate.update(status='passed',stage='complete',finished_at=time.time());save(active/'status.json',jobstate);jobstate=None
                update(stage='variant_complete')
            update(status='passed',stage='complete',finished_at=time.time())
    except BaseException as error:
        if jobstate is not None:jobstate.update(status='failed',error=str(error),finished_at=time.time());save(active/'status.json',jobstate)
        jobstate=None;update(status='failed',stage='needs_diagnosis',error=str(error),finished_at=time.time());return 1
    return 0

def monitor(root):
    path=root/'monitor.json';book=load(path);book.setdefault('sent',[])
    with (root/'monitor.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        while True:
            events=[]
            for p in sorted((root/'jobs').glob('*/attempt_*/status.json')):
                d=load(p)
                if d.get('status') in ('passed','failed'):
                    events.append((str(p.relative_to(root))+':'+d['status'],f"OPT benchmarks {d['label']}: {d['status']}. "+d.get('error','Exact parity, resident-input and file-read-to-verdict measurements complete.')))
            state=load(root/'status.json');terminal=state.get('status') in ('passed','failed')
            if terminal:events.append(('campaign:'+str(state['started_at'])+state['status'],'OPT benchmark campaign '+state['status']+'. '+state.get('error',str(root))))
            elif state and not alive(state.get('pid'),'opt_benchmark.py'):events.append(('stopped:'+str(state.get('pid')),'OPT benchmark controller stopped unexpectedly; inspect before programming again. '+str(root)))
            for key,message in events:
                if key not in book['sent'] and send(root,dict(id=key,outcome='status',message=message)):
                    book['sent'].append(key)
            book.update(status='monitoring',pid=os.getpid(),heartbeat=time.time());save(path,book)
            if state.get('status')=='passed' and all(k in book['sent'] for k,_ in events):
                book.update(status='complete');save(path,book);return
            time.sleep(15)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('command',choices=['setup','seal','run','monitor']);p.add_argument('root',type=Path);a=p.parse_args();root=a.root.resolve()
    if a.command=='setup':setup(root)
    elif a.command=='seal':seal(root)
    elif a.command=='monitor':monitor(root)
    else:raise SystemExit(run(root))
