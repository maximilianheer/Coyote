"""Fresh D_I/D_N builds and their mandatory C-simulation/RTL gates."""
import csv,json,os,shutil,subprocess,signal
from pathlib import Path
from board_benchmark import sha,save
from timing import validate_timing_report
from resources import attribute

def command(args,cwd,log,env=None):
    print('RUN',args,flush=True)
    with Path(log).open('w') as stream:
        child=subprocess.Popen(list(map(str,args)),cwd=cwd,env=env,stdout=stream,stderr=subprocess.STDOUT,preexec_fn=os.setpgrp)
        try:
            if child.wait(timeout=86400):raise RuntimeError('Command failed; inspect '+str(log))
        except BaseException:
            if child.poll() is None:
                os.killpg(child.pid,signal.SIGTERM)
                try:child.wait(timeout=10)
                except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL);child.wait()
            raise

def csim(package,job):
    for tag,kernel in [('reference',job/'reference'),('candidate',job/'hw/src/hls/cnn_wrapper')]:
        output=job/(tag+'_simulation');output.mkdir()
        pp=job/'reference/preprocess_wrapper.cpp' if tag=='reference' else job/'hw/src/hls/preprocess_wrapper/preprocess_wrapper.cpp'
        include=Path(os.environ['HLS_INCLUDE'])
        command(['g++','-O1','-std=c++14','-Wno-unknown-pragmas','-I'+str(include),'-I'+str(kernel),
                 '-DWEIGHTS_DIR="'+str(kernel/'firmware/weights')+'"',package/'checks/direct_csim.cpp',pp,
                 kernel/'cnn_wrapper.cpp',kernel/'firmware/prod_res256_manualA_coyote_accel.cpp',
                 '-lgmp','-pthread','-o',output/'parity'],job,output/'compile.log')
        command([output/'parity'],output,output/'csim.log')
    expected=(package/'inputs/rtl_expected.txt').read_bytes()
    for tag in ['reference','candidate']:
        if (job/(tag+'_simulation/direct_expected.txt')).read_bytes()!=expected:
            raise RuntimeError('Preprocessing/CNN boundary parity failed: '+tag)

def rtl(package,job):
    env=dict(os.environ,DIRECT_JOB=str(job),DRIVER_RESETS='1',DIRECT_STARTUP_IDLE='20000',DIRECT_ALWAYS_READY='0')
    command(['vitis_hls','-f',package/'checks/cnn_reference_synth.tcl'],job,job/'reference_hls.log',env)
    pp=list((job/'build').rglob('solution1/syn/verilog/preprocess_wrapper.v'))
    cnn=list((job/'build').rglob('solution1/syn/verilog/cnn_wrapper.v'))
    if len(pp)!=1 or len(cnn)!=1:raise RuntimeError('Expected unique actual build RTL for each core')
    for label,core in [('reference',job/'reference_hls/solution1/syn/verilog'),('candidate',cnn[0].parent)]:
        sim=job/('rtl_'+label);sim.mkdir()
        shutil.copytree(pp[0].parent,sim/'pp');shutil.copytree(core,sim/'cnn')
        for name in ['direct_pipe_tb.sv','direct_sim.tcl']:shutil.copy2(package/'checks'/name,sim/name)
        shutil.copy2(package/'inputs/rtl_expected.txt',sim/'direct_expected.txt')
        shutil.copy2(job/'hw/src/hdl/elastic_fifo.sv',sim/'elastic_fifo.sv')
        command(['vivado','-mode','batch','-source',sim/'direct_sim.tcl'],sim,sim/'check.log',env)
        text=(sim/'check.log').read_text()
        if 'PASS direct synthesized RTL parity: frames=11' not in text or 'Fatal:' in text:
            raise RuntimeError('Incomplete second-reset/stalled/consecutive-frame RTL gate')
    baseline=list(csv.DictReader((job/'rtl_reference/cycles.csv').open()))
    candidate=list(csv.DictReader((job/'rtl_candidate/cycles.csv').open()))
    if len(baseline)!=11 or [r['bytes'] for r in baseline]!=[r['bytes'] for r in candidate]:
        raise RuntimeError('Incomplete paired CNN cycle cases')
    if any(not 0<int(b['cnn_cycles'])<int(a['cnn_cycles']) for a,b in zip(baseline,candidate)):
        raise RuntimeError('CNN cycle-reduction gate failed')
    save(job/'rtl_gate.json',dict(status='passed',frames=11,startup_idle_cycles=20000,driver_resets=1))

def build(package,root,variant):
    job=root/variant;shutil.copytree(package/'sources/designs'/variant,job)
    cy=job/'coyote';shutil.copytree(package/'sources/coyote',cy)
    overlay=package/'sources/coyote_D_N_overlay'
    if variant=='D_N' and overlay.exists():shutil.copytree(overlay,cy,dirs_exist_ok=True)
    config=job/'hw/CMakeLists.txt'
    config.write_text(config.read_text().replace('${CMAKE_CURRENT_SOURCE_DIR}/../../coyote',str(cy)))
    # Freeze replay identities separately from the original measured source identities.
    sources={str(p.relative_to(job)):sha(p) for p in job.rglob('*') if p.is_file()}
    save(job/'source_manifest.json',sources)
    control=job/'control';control.mkdir()
    command(['xvlog','--sv',job/'hw/src/hdl/direct_control.sv',job/'hw/src/hdl/elastic_fifo.sv',package/'checks/direct_control_tb.sv'],control,control/'compile.log')
    v='7' if variant=='D_I' else '8'
    command(['xelab','direct_control_tb','-s','control','-generic_top','VARIANT='+v],control,control/'elaborate.log')
    command(['xsim','control','-runall'],control,control/'simulate.log')
    if 'PASS direct control' not in (control/'simulate.log').read_text():raise RuntimeError('Control RTL gate failed')
    if variant=='D_I':csim(package,job)
    b=job/'build';b.mkdir()
    command(['cmake','-S',job/'hw','-B',b,'-DVITIS_HLS_MODE=vitis_hls','-DCOMP_CORES=8'],job,job/'configure.log')
    if variant=='D_I':
        # Replay the successful physical recipe on this fresh attempt's netlist.
        script=b/'pnr_shell.tcl'
        if not script.exists():
            candidates=list(b.glob('*shell*.tcl'))
            candidates=[p for p in candidates if 'open_checkpoint "$dcp_dir/shell_linked.dcp"' in p.read_text()]
            if len(candidates)!=1:raise RuntimeError('Cannot locate generated shell implementation script')
            script=candidates[0]
        script.write_text((package/'scripts/di_implementation.tcl').read_text().replace('@BASE@',str(b/'base.tcl')))
    for stage in ['project','synth','link','shell','bitgen']:
        command(['make','-j1',stage],b,job/(stage+'.log'))
        if stage=='project' and variant=='D_I':rtl(package,job)
        if stage=='shell':validate_timing_report(b/'reports/shell_timing_summary.rpt')
    if any(sha(job/name)!=digest for name,digest in sources.items()):raise RuntimeError('Build sources changed')
    bit=b/'bitstreams/cyt_top.bit'
    if not bit.is_file() or not bit.stat().st_size:raise RuntimeError('Missing bitstream')
    result=dict(variant_id=int(v),bitstream=str(bit),bitstream_sha256=sha(bit),source_manifest_sha256=sha(job/'source_manifest.json'),status='passed',board_validated=False)
    save(job/'identity.json',result)
    resources=attribute((b/'reports/shell_utilization_hierarchical.rpt').read_text(),(b/'reports/shell_utilization.rpt').read_text(),variant)
    save(job/'resources.json',resources)
    return result
