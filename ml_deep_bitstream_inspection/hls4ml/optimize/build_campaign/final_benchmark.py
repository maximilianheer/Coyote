#!/usr/bin/env python3
"""Image-bound final FPGA/GPU comparison, with one programming/measurement lease."""
import argparse, fcntl, json, os, re, shutil, socket, subprocess, sys, time
from pathlib import Path
HERE = Path(__file__).resolve().parent
REPO = next(p for p in HERE.parents if (p/'ML_Based_Deep_Bitstream_Inspection_for_Serverless_FPGAs_Report.pdf').exists())
sys.path.append(str(REPO/'hls4ml/optimize/build_campaign'))
from board_benchmark import sha, save
from prepare import verify_sources
from fifo_sweep_results import artifact_summary
from iteration_monitor import send
GPU = REPO/'hls4ml/optimize/runs/gpu_fp32_20261018'
OLD = REPO/'hls4ml/optimize/runs/opt_benchmarks_u55c02_20261013'
OPT6 = 'OPT_6_BRAM_FIFO1024_DSP_B2_RF72_RF288'
ORDER = ['OPT_1_STREAMING','OPT_0_NONSTREAMING',OPT6,'OPT_7_GPU_HOST','OPT_8_GPU_P2P','OPT_1_STREAMING_REPEAT']
def read(p): return json.loads(Path(p).read_text())

def setup(root,device=2):
    root.mkdir(exist_ok=False); (root/'jobs').mkdir(); (root/'logs').mkdir()
    tools=root/'tooling'; tools.mkdir(); software=root/'software'; software.mkdir()
    old=read(OLD/'campaign.json'); images={}
    for name in ORDER[:3]:
        job=Path(old['images'][name]['job']) if name!=OPT6 else REPO/f'hls4ml/optimize/runs/combined_fifo1024_b2_20261013/{OPT6}/attempt_01'
        a=artifact_summary(job); c=read(job/'config/iteration.json')
        images[name]=dict(job=str(job),kind='fpga',bitstream=a['bitstream'],bitstream_sha256=sha(a['bitstream']),
            source_manifest_sha256=a['source_manifest_sha256'],artifact_manifest_sha256=a['artifact_manifest_sha256'],
            fifo_depth=c['interface']['external_fifo_depth'],pipeline_mode=c['interface'].get('pipeline_mode','streaming'),resources=a['resources'])
    for name in ORDER[3:5]:
        job=GPU/'jobs'/name; s=read(job/'status.json'); m=read(job/'artifact_manifest.json')
        assert s['status']=='passed' and verify_sources(job)==m['source_manifest_sha256']
        for p,v in m['files'].items(): assert sha(job/p)==v['sha256'],p
        image=next(p for p in s['artifacts']['bitstreams'] if p.endswith('.bit'))
        images[name]=dict(job=str(job),kind='gpu',transport='host' if name.endswith('HOST') else 'p2p',bitstream=image,
            bitstream_sha256=sha(image),source_manifest_sha256=m['source_manifest_sha256'],artifact_manifest_sha256=sha(job/'artifact_manifest.json'))
    for name in ['opt_benchmark_collect.py','board_benchmark.py','parity_gate.py','host_environment.py','final_benchmark.py','final_benchmark_gpu.py',
                 'prepare.py','worker.py','fifo_sweep_results.py','resource_attribution.py','iteration_monitor.py']:
        shutil.copy2(REPO/'hls4ml/optimize/build_campaign'/name,tools/name)
    shutil.copy2(REPO/'hls4ml/pipeline/coyote_accelerator/direct_session.py',tools/'direct_session.py')
    for name in ['runtime','templates','coyote_sw']:
        shutil.copytree(OLD/'software'/name,software/name)
    shutil.copy2(GPU/'preflight/driver/build/coyote_driver.ko',software/'coyote_driver.ko')
    shutil.copy2(REPO.parent/'util/program_hacc_local.sh',software/'program_hacc_local.sh')
    shutil.copytree(GPU/'jobs/OPT_7_GPU_HOST/runtime',software/'gpu_runtime')
    # Keep the model snapshot, but use the validated HPF transport adapter.
    shutil.copy2(REPO/'hls4ml/optimize/build_campaign/gpu/transport.cpp',software/'gpu_runtime/transport.cpp')
    shutil.copy2(REPO/'hls4ml/optimize/build_campaign/gpu/fp32_model.py',software/'gpu_runtime/fp32_model.py')
    shutil.copytree(GPU/'jobs/OPT_7_GPU_HOST/coyote/sw',software/'gpu_coyote_sw')
    for name in ['cases.tsv','pilot.tsv','admission.tsv']:shutil.copy2(OLD/name,root/name)
    assert (root/'cases.tsv').read_bytes()==(GPU/'cases.tsv').read_bytes()
    driver=software/'coyote_driver.ko'
    bdf,serial={1:('0000:a1:00.0','XFL1BE3ESRZ4A'),2:('0000:81:00.0','XFL13BA4HVZYA')}[device]
    cfg=dict(schema=1,repo=str(REPO),hostname=socket.gethostname(),device=device,pci_bdf=bdf,board_serial=serial,
        gpu=0,gpu_bdf='0000:03:00.0',cpu=64,numa_node=1,board_lock=str(GPU/'board_device.lock'),images=images,
        driver=str(driver),driver_sha256=sha(driver),order=ORDER,warmups=20,trials=200,full_cases=15,
        host_buffer_capacity_bytes=134217728,host_runtime_revision='hpf_matching_pack_calibration20',
        python=str(GPU/'venv/bin/python'),software_files={},created_at=time.time())
    save(root/'campaign.json',cfg); save(root/'status.json',dict(status='prepared',stage='runtime_preparation'))
    print(root,flush=True)

def seal(root):
    c=read(root/'campaign.json'); c['software_files']={}
    for folder in ['tooling','software/runtime','software/templates','software/coyote_sw','software/gpu_runtime','software/gpu_coyote_sw']:
        for p in (root/folder).rglob('*'):
            if p.is_file() and '__pycache__' not in p.parts:c['software_files'][str(p.relative_to(root))]=sha(p)
    for pattern in ['software/coyote_driver.ko','software/program_hacc_local.sh','software/runtime_build/*.so','software/runtime_build/coyote/*.so','software/gpu_build/*.so','software/gpu_build/coyote/*.so','*.tsv']:
        for p in root.glob(pattern):c['software_files'][str(p.relative_to(root))]=sha(p)
    save(root/'campaign.json',c)

def verify(root):
    c=read(root/'campaign.json')
    assert c['software_files'],'Unsealed software'
    for p,h in c['software_files'].items():assert sha(root/p)==h,'Changed campaign software: '+p
    for name,i in c['images'].items():
        assert sha(i['bitstream'])==i['bitstream_sha256'],name
        assert sha(Path(i['job'])/'artifact_manifest.json')==i['artifact_manifest_sha256'],name
    return c

def run(root):
    c=verify(root); assert socket.gethostname()==c['hostname']
    assert subprocess.check_output(['modinfo','-F','vermagic',c['driver']],text=True).startswith(os.uname().release+' ')
    state=dict(status='running',stage='waiting_board',pid=os.getpid(),started_at=time.time());save(root/'status.json',state)
    env=dict(os.environ,OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',TF_NUM_INTRAOP_THREADS='1',TF_NUM_INTEROP_THREADS='1',
        HIP_VISIBLE_DEVICES='0',TF_FORCE_GPU_ALLOW_GROWTH='true',COYOTE_ALLOC_TYPE='HPF',COYOTE_BENCH_PCI_BDF=c['pci_bdf'])
    env['PATH']='/tools/Xilinx/Vivado/2024.2/bin:'+env['PATH'];env['LD_LIBRARY_PATH']='/opt/rocm/lib:'+env.get('LD_LIBRARY_PATH','')
    env['PYTHONPATH']=str(root/'software/gpu_build')+':'+str(root/'software/gpu_runtime')+':'+str(root/'tooling')
    active=None; js=None
    def update(**kw):
        state.update(heartbeat=time.time(),**kw);save(root/'status.json',state)
        if js is not None:js.update(stage=state['stage'],heartbeat=time.time());save(active/'status.json',js)
    def command(stage,args,timeout=3600,cwd=None):
        update(stage=stage,stage_started_at=time.time())
        with (active/(stage+'.log')).open('w') as log:
            p=subprocess.Popen(args,cwd=cwd or REPO,env=env,stdout=log,stderr=subprocess.STDOUT)
            update(child_pid=p.pid)
            while p.poll() is None:
                update()
                if time.time()-state['stage_started_at']>timeout:
                    p.terminate(); raise TimeoutError(stage+' timed out; inspect and recover board before resuming')
                time.sleep(2)
            if p.returncode:raise RuntimeError(stage+' failed; see '+str(active/(stage+'.log')))
    try:
        with (root/'controller.lock').open('a') as lock,Path(c['board_lock']).open('a') as lease:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);fcntl.flock(lease,fcntl.LOCK_EX|fcntl.LOCK_NB)
            for label in c['order']:
                ident='OPT_1_STREAMING' if label.endswith('_REPEAT') else label;i=c['images'][ident]
                parent=root/'jobs'/label;parent.mkdir(exist_ok=True)
                attempts=sorted(parent.glob('attempt_*/status.json'))
                if attempts and read(attempts[-1])['status']=='passed':
                    for result in attempts[-1].parent.glob('*/result.json'):
                        r=read(result);assert r['status']=='passed'
                        for p,h in r['files'].items():assert sha(result.parent/p)==h,'Changed completed evidence'
                    continue
                active=parent/f'attempt_{len(attempts)+1:02d}';active.mkdir()
                js=dict(id=ident,label=label,status='running',started_at=time.time());update(active=label,attempt=str(active),stage='preflight')
                verify(root)
                users=subprocess.run(['fuser','/dev/coyote_fpga_0_v0'],capture_output=True,text=True)
                if users.returncode==0:raise RuntimeError('Board has active users: '+users.stdout)
                save(root/'installed_image.json',dict(status='programming',id=ident))
                import shlex
                # ROCm/XRT libraries belong to runners, not Vivado's bundled tools.
                cmd=['env','-u','LD_LIBRARY_PATH','bash',str(root/'software/program_hacc_local.sh'),i['bitstream'],c['driver'],str(c['device'])]
                command('program',['script','--quiet','--return','--command',shlex.join(cmd),'/dev/null'],timeout=900,cwd=REPO.parent/'util')
                program_log=(active/'program.log').read_text()
                if re.search(r'(?m)^ERROR:',program_log) or 'program_hw_devices: Time' not in program_log:
                    save(root/'installed_image.json',dict(status='unverified',requested_id=ident,reason='Vivado programming did not pass'))
                    raise RuntimeError('Programming log failed validation despite helper exit status; see '+str(active/'program.log'))
                if 'Opening hw_target localhost:3121/xilinx_tcf/Xilinx/'+c['board_serial'] not in program_log:
                    raise RuntimeError('Programming log does not identify the selected board serial')
                pci=Path('/sys/bus/pci/devices')/c['pci_bdf']
                assert (pci/'vendor').read_text().strip()=='0x10ee','Target is not Xilinx'
                assert (pci/'current_link_width').read_text().strip()=='16'
                assert (pci/'current_link_speed').read_text().startswith('8.0 GT/s')
                assert Path('/dev/coyote_fpga_0_v0').exists()
                save(root/'installed_image.json',dict(status='ready',id=ident,**i,driver_sha256=c['driver_sha256'],reset_diagnostic=False,installed_at=time.time()))
                prefix=['numactl','--physcpubind=64','--membind=1',c['python']]
                modes=['admission','pilot','full']+(['profile'] if i['kind']=='gpu' else [])
                collector='opt_benchmark_collect.py' if i['kind']=='fpga' else 'final_benchmark_gpu.py'
                for mode in modes:
                    command(mode,prefix+[str(root/'tooling'/collector),str(root),ident,str(active/mode),mode])
                    assert read(active/mode/'result.json')['status']=='passed'
                js.update(status='passed',stage='complete',finished_at=time.time());save(active/'status.json',js);js=None
            update(stage='analysis')
            summarize(root)
            update(status='passed',stage='complete',finished_at=time.time())
    except BaseException as e:
        if js is not None:js.update(status='failed',error=str(e),finished_at=time.time());save(active/'status.json',js)
        js=None;update(status='failed',stage='needs_diagnosis',error=str(e),finished_at=time.time());return 1
    return 0

def summarize(root):
    rows=[]; results={}
    for label in read(root/'campaign.json')['order']:
        p=sorted((root/'jobs'/label).glob('attempt_*/full/result.json'))[-1];r=read(p);results[label]=r
        for s in r['summaries']:
            rows.append(dict(iteration=label,case_id=s['case_id'],scope=s['scope'],input_bytes=s['input_bytes'],**s['metrics']))
    def med(label):
        return {(r['case_id'],r['scope']):r['metrics']['file_e2e_ms' if r['scope']=='file' else 'host_observed_ms']['median'] for r in results[label]['summaries']}
    before=med('OPT_1_STREAMING');after=med('OPT_1_STREAMING_REPEAT')
    drift=[dict(case_id=k[0],scope=k[1],relative_change=after[k]/v-1) for k,v in before.items()]
    cfg=read(root/'campaign.json');resources={}
    from resource_attribution import attribute
    for ident,image in cfg['images'].items():
        if 'resources' in image:resources[ident]=dict(image['resources'],variant=ident)
        else:
            reports=read(Path(image['job'])/'status.json')['artifacts']['utilization_reports']
            h=next(Path(p) for p in reports if p.endswith('shell_utilization_hierarchical.rpt'))
            s=next(Path(p) for p in reports if p.endswith('shell_utilization.rpt'))
            resources[ident]=attribute(h.read_text(),s.read_text(),ident)
    speedups=[dict(iteration=label,case_id=k[0],scope=k[1],speedup_vs_streaming=before[k]/v) for label in cfg['images'] for k,v in med(label).items()]
    profiles={}
    import statistics
    from board_benchmark import percentile
    for ident,image in cfg['images'].items():
        if image['kind']!='gpu':continue
        p=sorted((root/'jobs'/ident).glob('attempt_*/profile/device_profile.json'))[-1]
        data=read(p);assert data['status']=='passed';groups={}
        for row in data['rows']:groups.setdefault((row['case_id'],row['phase']),[]).append(row)
        profiles[ident]=[dict(case_id=key[0],phase=key[1],trials=len(values),
            device_span_ms=dict(median=statistics.median(v['device_span_ms'] for v in values),p95=percentile([v['device_span_ms'] for v in values],.95)),
            kernel_sum_ms=dict(median=statistics.median(v['kernel_sum_ms'] for v in values),p95=percentile([v['kernel_sum_ms'] for v in values],.95)),
            host_synchronized_phase_ms=dict(median=statistics.median(v['host_synchronized_phase_ms'] for v in values),p95=percentile([v['host_synchronized_phase_ms'] for v in values],.95)),
            kernel_count_range=[min(v['kernels'] for v in values),max(v['kernels'] for v in values)]) for key,values in groups.items()]
    save(root/'summary.json',dict(status='passed' if all(abs(x['relative_change'])<=.05 for x in drift) else 'drift_review_required',rows=rows,baseline_drift=drift,speedups=speedups,resources=resources,
        gpu_device_profiles=profiles,profile_scope='Separate synchronized diagnostics; do not add these medians to overlapping unprofiled intervals',
        inference_scope='FPGA first CNN input to score includes streaming stalls. GPU kernel sum excludes gaps; device span includes gaps in a profiled diagnostic.',
        target={k:cfg[k] for k in ['hostname','device','pci_bdf','board_serial','gpu','gpu_bdf','cpu','numa_node']},
        precision={ident:('float32' if image['kind']=='gpu' else 'quantized W8A8') for ident,image in cfg['images'].items()}))
    import csv
    flat=[dict(iteration=r['iteration'],case_id=r['case_id'],scope=r['scope'],input_bytes=r['input_bytes'],metric=k,**v) for r in rows for k,v in r.items() if isinstance(v,dict)]
    with (root/'summary.csv').open('w') as f:
        w=csv.DictWriter(f,fieldnames=list(flat[0]));w.writeheader();w.writerows(flat)
    if any(abs(x['relative_change'])>.05 for x in drift):raise RuntimeError('Baseline drift exceeds 5%; inspect summary.json before accepting comparisons')

def monitor(root):
    delivered=set();path=root/'monitor.json'
    if path.exists():delivered=set(read(path).get('delivered',[]))
    with (root/'monitor.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        while True:
            s=read(root/'status.json');events={}
            for p in (root/'jobs').glob('*/attempt_*/status.json'):
                j=read(p)
                if j['status'] in ('passed','failed'):events[str(p)+j['status']]=f"Final benchmarks {j['label']}: {j['status']}. "+j.get('error','Admission and measurements complete.')
            if s['status'] in ('passed','failed'):events[str(s.get('started_at'))+s['status']]='Final FPGA/GPU benchmark campaign '+s['status']+'. '+s.get('error',str(root))
            elif s.get('pid') and not Path('/proc/'+str(s['pid'])).exists():events['exit'+str(s['pid'])]='Final benchmark controller exited unexpectedly; inspect '+str(root)
            for key,msg in events.items():
                if key not in delivered and send(root,dict(id=key,message=msg)):delivered.add(key)
            save(path,dict(status='watching',pid=os.getpid(),heartbeat=time.time(),delivered=sorted(delivered)))
            if s['status']=='passed' and all(k in delivered for k in events):return
            time.sleep(15)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('command',choices=['setup','seal','run','monitor','summarize']);p.add_argument('root',type=Path)
    p.add_argument('--device',type=int,choices=[1,2],default=2,help='Setup only; device2 is the currently healthy U55C')
    a=p.parse_args();result=setup(a.root.resolve(),a.device) if a.command=='setup' else globals()[a.command](a.root.resolve())
    sys.exit(result if isinstance(result,int) else 0)
