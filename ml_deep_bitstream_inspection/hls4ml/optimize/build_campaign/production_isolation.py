"""Fresh production-interface isolation builds; never modify frozen sources."""
import fcntl, json, os, shutil, subprocess, sys, time
from pathlib import Path
from prepare import HERE, MODEL, PACKAGE, HARDWARE, copy_coyote, source_manifest, sha, verify_sources
from worker import save, collect_artifacts, final_timing_reports

VARIANTS = {'R_O': 'production_optimized', 'R_S': 'production_streaming',
            'R_SO_T': 'production_streaming'}

def parallel_memory_required(stage, other_running, other_rss=0, other_peak_gib=24):
    """Reserve the other build's future growth, not only its current allocation."""
    gib=2**30
    # Synthesis uses two concurrent runs, each limited to one tool thread.
    own_peak={'synth':12,'link':12,'bitgen':12}[stage]*gib
    other_growth=max(0,other_peak_gib*gib-other_rss) if other_running else 0
    return max(24*gib,own_peak+other_growth+8*gib)

def other_build_memory(jobdir):
    other='R_O' if jobdir.name=='R_S' else 'R_S'
    path=jobdir.parent/other/'progress.json'
    state=json.loads(path.read_text())
    if state.get('status')!='running':return False,0,0
    group=state['pid'];rss=0
    for proc in Path('/proc').iterdir():
        if not proc.name.isdecimal():continue
        try:
            # Following the final ')' avoids spaces inside Linux task names.
            fields=(proc/'stat').read_text().rsplit(')',1)[1].split()
            if int(fields[2])==group:rss+=int(fields[21])*os.sysconf('SC_PAGE_SIZE')
        except (FileNotFoundError,ProcessLookupError,PermissionError):pass
    # R_O measured ~19 GiB across synthesis forks; previous implementation
    # peaked ~16 GiB. Reserve 24/20 GiB respectively, plus the shared margin.
    stage=state.get('stage','')
    peak=20 if any(name in stage for name in ('link','shell','bitgen')) else 24
    return True,rss,peak

def prepare_isolation(root, job, state):
    evidence = None
    if job['id'] == 'R_SO_T':
        from production_candidate import prerequisites
        evidence = prerequisites(state)
    dst = root/'jobs'/job['id']; dst.mkdir(parents=True, exist_ok=False)
    coyote = dst/'coyote'; copy_coyote(coyote)
    # Same production shell settings, with reduced tool concurrency on this host.
    base = coyote/'scripts/base.tcl.in'
    base.write_text(base.read_text().replace('set_param general.maxThreads 8', 'set_param general.maxThreads 4'))
    src = dst/'hw/src'; src.mkdir(parents=True)
    kr = src/'hls/model_wrapper'; shutil.copytree(MODEL, kr)
    shutil.copy2(HARDWARE/'variants'/(VARIANTS[job['id']]+'.cpp'), kr/'model_wrapper.cpp')
    shutil.copy2(HARDWARE/'production/vfpga_top.svh', src/'vfpga_top.svh')
    (src/'hdl').mkdir()
    shutil.copy2(HARDWARE/'debug_probe.svh', src/'hdl/debug_probe.svh')
    shutil.copy2(HARDWARE/'init_ip.tcl', src/'init_ip.tcl')
    if job['id'] in ('R_O', 'R_SO_T'):
        shutil.copy2(HARDWARE/'common/conv0_dataflow.hpp', kr/'conv0_dataflow.hpp')
        model = kr/'firmware/prod_res256_manualA_coyote_accel.cpp'
        text = model.read_text(); call = 'nnet::conv_2d_cl<layer2_t, conv0_result_t, config3>'
        if text.count(call) != 1: raise RuntimeError('Production conv0 call not unique')
        model.write_text(text.replace('#include "parameters.h"', '#include "parameters.h"\n#include "../conv0_dataflow.hpp"').replace(call, 'benchmark::conv0_dataflow<layer2_t, conv0_result_t, config3>'))
    if job['id'] in ('R_S', 'R_SO_T'):
        shutil.copy2(HARDWARE/'common/production_inference.hpp', kr/'production_inference.hpp')
        shutil.copy2(HARDWARE/'common/frame_start.hpp', kr/'frame_start.hpp')
    host = dst/'host'; host.mkdir()
    for name in ['host_libs.cpp', 'host_libs.hpp']:
        shutil.copy2(PACKAGE/'sources/generated_project/src'/name, host/name)
    shutil.copy2(HERE/'templates/production_runtime_CMakeLists.txt', host/'CMakeLists.txt')
    tests = dst/'tests'; tests.mkdir()
    for name in ['production_wrapper_csim.cpp', 'production_wrapper_tb.sv', 'production_wrapper_sim.tcl']:
        shutil.copy2(HERE/'tests'/name, tests/name)
    cases = Path(state['parity_cases'])
    shutil.copy2(cases, tests/'cases.tsv')
    shutil.copy2(Path(state['boundary_reference']), tests/'boundary_reference.txt')
    for line in cases.read_text().splitlines():
        fields = line.split('\t')
        if sha(Path(fields[2])) != fields[4]: raise RuntimeError('Parity input hash changed')
    project = 'isolate_'+job['id'].lower()
    (dst/'hw/CMakeLists.txt').write_text(f'''cmake_minimum_required(VERSION 3.5)
set(CYT_DIR "{coyote}")
set(CMAKE_MODULE_PATH "${{CYT_DIR}}/cmake")
find_package(CoyoteHW REQUIRED)
project({project})
set(FDEV_NAME "u55c")
set(N_REGIONS 1)
set(N_CONFIG 1)
set(EN_PR 0)
set(EN_STRM 1)
set(N_STRM_AXI 1)
set(EN_MEM 0)
set(COMP_CORES 4)
set(BUILD_OPT 1)
validation_checks_hw()
load_apps(VFPGA_C0_0 "src")
create_hw()
''')
    frozen = PACKAGE/'sources/generated_project/src'
    assert (host/'host_libs.cpp').read_bytes() == (frozen/'host_libs.cpp').read_bytes()
    assert (kr/'firmware/zero_in_raw_downsample.hpp').read_bytes() == (MODEL/'firmware/zero_in_raw_downsample.hpp').read_bytes()
    if job['id'] == 'R_O':
        assert (kr/'model_wrapper.cpp').read_bytes() == (MODEL/'model_wrapper.cpp').read_bytes()
    elif job['id']=='R_S':
        assert (kr/'firmware/prod_res256_manualA_coyote_accel.cpp').read_bytes() == (MODEL/'firmware/prod_res256_manualA_coyote_accel.cpp').read_bytes()
    if job['id'] == 'R_SO_T':
        from production_candidate import configure
        configure(dst, evidence)
    save(dst/'source_manifest.json', dict(files=source_manifest(dst), variant=job['id'],
        attempt=job.get('attempt',1), production_input_and_result_dma=True,
        input_format='64-byte length header + exact raw byte count; no aligned transfer padding',
        runtime='Unmodified production host_libs.cpp, rebuilt against current Coyote',
        build_scripts={str(p.relative_to(coyote)):sha(p) for folder in ['scripts','cmake'] for p in (coyote/folder).rglob('*') if p.is_file()}))
    job.update(prepared=True, project=project)
    return dst

def run_isolation(jobdir, job, validate_only=False):
    resume_stage = os.environ.get('ISOLATION_RESUME_STAGE')
    if resume_stage not in (None, 'synth'):
        raise ValueError('Only the validated project-to-synthesis boundary can resume')
    env = os.environ.copy()
    env['PATH'] = '/tools/Xilinx/Vivado/2024.2/bin:/tools/Xilinx/Vitis_HLS/2024.2/bin:'+env['PATH']
    env.update(OMP_NUM_THREADS='4', OPENBLAS_NUM_THREADS='1', TMPDIR=str(jobdir/'tmp'), DRIVER_RESETS='1')
    (jobdir/'tmp').mkdir(exist_ok=True)
    previous = json.loads((jobdir/'progress.json').read_text()) if resume_stage else {}
    state = dict(previous) if resume_stage else dict(started_at=time.time(), hardware_started=False)
    state.update(status='running', stage='validation', pid=os.getpid())
    output = jobdir/('validation_progress.json' if validate_only else 'progress.json'); save(output,state)
    def cmd(stage, args, cwd=jobdir):
        state.update(stage=stage, stage_started_at=time.time()); save(output,state)
        print(stage,args,flush=True)
        with (jobdir/(stage+'.log')).open('w') as log:
            subprocess.run(args,cwd=cwd,env=env,stdout=log,stderr=subprocess.STDOUT,check=True)
    try:
        digest = verify_sources(jobdir); kr = jobdir/'hw/src/hls/model_wrapper'
        if resume_stage:
            validation = json.loads((jobdir/'validation.json').read_text())
            if previous.get('stage') != 'waiting_memory_synth' or validation.get('status') != 'passed' or validation.get('source_manifest_sha256') != digest:
                raise RuntimeError('Resume requires the unchanged, validated pre-synthesis boundary')
            if 'PASS production wrapper frames=8' not in (jobdir/'wrapper_rtl.log').read_text():
                raise RuntimeError('Resume requires all eight wrapper RTL frames')
            state.update(resumed_at=time.time(), resumed_from_pid=previous['pid'], parallel_synthesis=True)
            save(output,state)
        else:
            cmd('host_configure',['cmake','-S',str(jobdir/'host'),'-B',str(jobdir/'host_build'),'-DCOYOTE_SW='+str(jobdir/'coyote/sw')])
            cmd('host_compile',['cmake','--build',str(jobdir/'host_build'),'--parallel','2'])
            cmd('parity_compile',['g++','-O1','-std=c++14','-Wno-unknown-pragmas','-I/tools/Xilinx/Vitis/2024.2/include','-I'+str(kr),'-DWEIGHTS_DIR="'+str(kr/'firmware/weights')+'"', str(jobdir/'tests/production_wrapper_csim.cpp'),str(kr/'model_wrapper.cpp'),str(kr/'firmware/prod_res256_manualA_coyote_accel.cpp'),'/usr/lib/x86_64-linux-gnu/libgmp.so.10','-pthread','-o',str(jobdir/'parity')])
            cmd('parity',[str(jobdir/'parity'),str(jobdir/'tests/cases.tsv'),str(jobdir/'tests/boundary_reference.txt')])
            if verify_sources(jobdir)!=digest: raise RuntimeError('Sources changed during validation')
            save(jobdir/'validation.json',dict(status='passed',source_manifest_sha256=digest,validated_at=time.time(),cases=26,repetitions=2,scope='C-simulation; production input framing, pixels, logits, result LAST=0 (KEEP unspecified); forward/reverse cases'))
        if validate_only:
            state.update(status='passed',stage='validated'); save(output,state); return 0
        build=jobdir/'build';build.mkdir(exist_ok=True)
        if not resume_stage:
            state.update(hardware_started=True,hardware_started_at=time.time());save(output,state)
            cmd('configure',['cmake','-S',str(jobdir/'hw'),'-B',str(build),'-DVITIS_HLS_MODE=vitis_hls','-DCOMP_CORES=4','-DVIVADO_ROOT_DIR=/tools/Xilinx/Vivado/2024.2','-DVITIS_HLS_ROOT_DIR=/tools/Xilinx/Vitis_HLS/2024.2'])
        stages = ['synth','link','shell','bitgen'] if resume_stage else ['project','synth','link','shell','bitgen']
        for stage in stages:
            # HLS/IP preparation overlaps; memory-heavy whole-device jobs share
            # one permit on the 62-GiB board host (16 GiB reserved hugepages).
            if state.get('parallel_synthesis') and stage in ('synth','link','bitgen'):
                # These stages may overlap the existing worker's implementation.
                # Keep two full-device place/route runs mutually exclusive below.
                state.update(stage='waiting_parallel_memory_'+stage);save(output,state)
                while True:
                    mem=dict(line.split(':',1) for line in Path('/proc/meminfo').read_text().splitlines())
                    available=int(mem['MemAvailable'].split()[0])*1024
                    other_running,other_rss,other_peak=other_build_memory(jobdir)
                    required=parallel_memory_required(stage,other_running,other_rss,other_peak)
                    state.update(available_memory_bytes=available,required_memory_bytes=required,
                                 other_build_rss_bytes=other_rss,other_build_peak_gib=other_peak);save(output,state)
                    if available>=required:break
                    time.sleep(30)
                cmd(stage,['make','-j1',stage],build)
            elif stage in ('synth','link','shell','bitgen'):
                state.update(stage='waiting_memory_'+stage);save(output,state)
                with (jobdir.parents[1]/'implementation.lock').open('w') as lock:
                    fcntl.flock(lock,fcntl.LOCK_EX)
                    while True:
                        mem=dict(line.split(':',1) for line in Path('/proc/meminfo').read_text().splitlines())
                        available=int(mem['MemAvailable'].split()[0])*1024
                        if available>=18*2**30:break
                        state.update(available_memory_bytes=available);save(output,state);time.sleep(30)
                    cmd(stage,['make','-j1',stage],build)
            else:
                cmd(stage,['make','-j1',stage],build)
            if stage=='project':
                found=list(build.rglob('solution1/syn/verilog/model_wrapper.v'))
                if len(found)!=1: raise RuntimeError('Cannot identify fresh model_wrapper RTL')
                rtl=jobdir/'rtl_validation';rtl.mkdir()
                shutil.copytree(found[0].parent,rtl/'core')
                for name in ['production_wrapper_tb.sv','production_wrapper_sim.tcl']:
                    shutil.copy2(jobdir/'tests'/name,rtl/name)
                shutil.copy2(jobdir/'rtl_expected.txt',rtl/'rtl_expected.txt')
                if job['id']=='R_SO_T':
                    from production_candidate import rtl_inputs
                    rtl_inputs(jobdir,rtl)
                cmd('wrapper_rtl',['vivado','-mode','batch','-source',str(rtl/'production_wrapper_sim.tcl')],rtl)
                if 'PASS production wrapper frames=8' not in (jobdir/'wrapper_rtl.log').read_text():
                    raise RuntimeError('Wrapper RTL gate did not pass')
                if job['id']=='R_SO_T':
                    from production_candidate import verify_rtl
                    verify_rtl(jobdir,rtl)
            if stage=='shell':final_timing_reports(build,job['id'])
        if verify_sources(jobdir)!=digest:raise RuntimeError('Sources changed during build')
        artifacts=collect_artifacts(build,job['id'])
        artifacts['sha256']={p:sha(Path(p)) for p in artifacts['bitstreams']}
        if job['id']=='R_SO_T':
            from worker import seal_artifacts
            seal_artifacts(jobdir,artifacts)
        state.update(status='passed',stage='complete',artifacts=artifacts,hardware_validated=False)
    except Exception as error:
        state.update(status='failed',error=str(error));print(str(error),flush=True)
    state['finished_at']=time.time();save(output,state)
    if state.get('hardware_started'):
        event=dict(key=f"{job['id']}:{job.get('attempt',1)}:0:{state['status']}",message=f"Hardware build {job['id']} {state['status']}: {state.get('error','routed timing and bitstreams passed; board parity pending')}. Logs: {jobdir}")
        with (jobdir.parents[1]/'hardware_outcomes.jsonl').open('a') as f:f.write(json.dumps(event)+'\n')
    return 0 if state['status']=='passed' else 1
