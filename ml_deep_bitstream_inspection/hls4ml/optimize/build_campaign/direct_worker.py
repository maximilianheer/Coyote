"""Validated host-stream builds; no board programming or benchmark execution."""
import fcntl,json,os,subprocess,sys,time
from pathlib import Path
from prepare import verify_sources,sha,HERE
from worker import save,collect_artifacts,final_timing_reports,seal_artifacts
from direct_prepare import DIRECT

def run_direct(jobdir,job,validate_only=False):
    env=os.environ.copy();env['PATH']='/tools/Xilinx/Vivado/2024.2/bin:/tools/Xilinx/Vitis_HLS/2024.2/bin:'+env['PATH']
    env.update(OMP_NUM_THREADS='8',OPENBLAS_NUM_THREADS='1',TMPDIR=str(jobdir/'tmp'))
    (jobdir/'tmp').mkdir(exist_ok=True)
    state=dict(status='running',stage='validation',pid=os.getpid(),started_at=time.time(),hardware_started=False)
    output=jobdir/('validation_progress.json' if validate_only else 'progress.json');save(output,state)
    def cmd(stage,args,cwd=jobdir):
        state.update(stage=stage,stage_started_at=time.time());save(output,state)
        print(stage,args,flush=True)
        with (jobdir/(stage+'.log')).open('w') as log:
            subprocess.run(args,cwd=cwd,env=env,stdout=log,stderr=subprocess.STDOUT,check=True)
    try:
        digest=verify_sources(jobdir);src=jobdir/'hw/src'
        cmd('host_configure',['cmake','-S',str(jobdir/'host'),'-B',str(jobdir/'host_build'),'-DCOYOTE_SW='+str(jobdir/'coyote/sw')])
        cmd('host_compile',['cmake','--build',str(jobdir/'host_build'),'--parallel','2'])
        rtl=jobdir/'control_validation';rtl.mkdir(exist_ok=True)
        cmd('control_compile',['xvlog','--sv',str(src/'hdl/direct_control.sv'),str(src/'hdl/elastic_fifo.sv'),str(jobdir/'tests/direct_control_tb.sv')],rtl)
        for variant in [7,8,9]:
            cmd('control_elaborate_'+str(variant),['xelab','direct_control_tb','-s','direct_'+str(variant),'-generic_top','VARIANT='+str(variant)],rtl)
            cmd('control_simulate_'+str(variant),['xsim','direct_'+str(variant),'-runall'],rtl)
            if 'PASS direct control' not in (jobdir/('control_simulate_'+str(variant)+'.log')).read_text():raise RuntimeError('Direct control RTL did not pass')
        if job['id']=='D_I':
            for tag,kr in [('reference',jobdir/'reference'),('candidate',src/'hls/cnn_wrapper')]:
                pp=jobdir/'reference/preprocess_wrapper.cpp' if tag=='reference' else src/'hls/preprocess_wrapper/preprocess_wrapper.cpp'
                flags=['g++','-O1','-std=c++14','-Wno-unknown-pragmas','-I/tools/Xilinx/Vitis/2024.2/include','-I'+str(kr),
                    '-DWEIGHTS_DIR="'+str(kr/'firmware/weights')+'"']
                cmd(tag+'_compile',flags+[str(jobdir/'tests/direct_csim.cpp'),str(pp),str(kr/'cnn_wrapper.cpp'),
                    str(kr/'firmware/prod_res256_manualA_coyote_accel.cpp'),'/usr/lib/x86_64-linux-gnu/libgmp.so.10','-pthread','-o',str(jobdir/(tag+'_csim'))])
                where=jobdir/(tag+'_simulation');where.mkdir(exist_ok=True)
                cmd(tag+'_csim',[str(jobdir/(tag+'_csim'))],where)
            baseline=jobdir/'reference_simulation/direct_expected.txt';candidate=jobdir/'candidate_simulation/direct_expected.txt'
            if baseline.read_bytes()!=candidate.read_bytes():raise RuntimeError('Full CNN logits differ from pristine production')
        if verify_sources(jobdir)!=digest:raise RuntimeError('Sources changed during validation')
        save(jobdir/'validation.json',dict(status='passed',source_manifest_sha256=digest,validated_at=time.time(),variant=job['id']))
        if validate_only:
            state.update(status='passed',stage='validated');save(output,state);return 0
        build=jobdir/'build';build.mkdir(exist_ok=True)
        # Actual hardware-job notifications begin here, not for preparatory tests.
        state['hardware_started']=True;state['hardware_started_at']=time.time();save(output,state)
        cmd('configure',['cmake','-S',str(jobdir/'hw'),'-B',str(build),'-DVITIS_HLS_MODE=vitis_hls','-DCOMP_CORES=8',
            '-DVIVADO_ROOT_DIR=/tools/Xilinx/Vivado/2024.2','-DVITIS_HLS_ROOT_DIR=/tools/Xilinx/Vitis_HLS/2024.2'])
        for stage in ['project','synth','link','shell','bitgen']:
            if stage=='project':
                cmd(stage,['make','-j1',stage],build)
            else:
                # Share the isolation campaign's whole-device memory permit.
                # HLS/IP preparation remains parallel; full-device stages can
                # otherwise exhaust this 62-GiB host's available memory.
                state.update(stage='waiting_memory_'+stage);save(output,state)
                with (jobdir.parents[1]/'implementation.lock').open('a') as lock:
                    fcntl.flock(lock,fcntl.LOCK_EX)
                    while True:
                        mem=dict(line.split(':',1) for line in Path('/proc/meminfo').read_text().splitlines())
                        available=int(mem['MemAvailable'].split()[0])*1024
                        if available>=18*2**30:break
                        state.update(available_memory_bytes=available);save(output,state);time.sleep(30)
                    cmd(stage,['make','-j1',stage],build)
            if stage=='project' and job['id']=='D_I':
                cmd('direct_rtl',[sys.executable,str(HERE/'check_direct_rtl.py'),str(jobdir)])
            if stage=='shell':final_timing_reports(build,job['id'])
        if verify_sources(jobdir)!=digest:raise RuntimeError('Source changed during build')
        artifacts=collect_artifacts(build,job['id']);seal_artifacts(jobdir,artifacts)
        state.update(status='passed',stage='complete',artifacts=artifacts,hardware_validated=False)
    except Exception as error:
        state.update(status='failed',error=str(error));print(str(error),flush=True)
    state['finished_at']=time.time();save(output,state)
    if state.get('hardware_started'):
        entry=dict(key=f"{job['id']}:{job.get('attempt',1)}:{job.get('timing_recovery',0)}:{state['status']}",
            message=f"Hardware build {job['id']} attempt {job.get('attempt',1)} {state['status']}: {state.get('error','bitstreams and routed timing passed')}. Logs: {jobdir}")
        with (jobdir.parents[1]/'hardware_outcomes.jsonl').open('a') as f:f.write(json.dumps(entry)+'\n')
    return 0 if state['status']=='passed' else 1
