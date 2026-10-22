"""R_S fresh monolithic streaming-wrapper build; original production CNN."""
import os,shutil
from pathlib import Path
from rebuild import command
from board_benchmark import save,sha
from timing import validate_timing_report
from resources import attribute


def build(package,root):
    job=root/'R_S';shutil.copytree(package/'sources/designs/R_S',job)
    cy=job/'coyote';shutil.copytree(package/'sources/coyote',cy)
    overlay=package/'sources/coyote_R_S_overlay'
    if overlay.exists():shutil.copytree(overlay,cy,dirs_exist_ok=True)
    config=job/'hw/CMakeLists.txt';config.write_text(config.read_text().replace('${CMAKE_CURRENT_SOURCE_DIR}/../../coyote',str(cy)))
    sources={str(p.relative_to(job)):sha(p) for p in job.rglob('*') if p.is_file()}
    save(job/'source_manifest.json',sources)
    kernel=job/'hw/src/hls/model_wrapper';sim=job/'csim';sim.mkdir()
    command(['g++','-O1','-std=c++14','-Wno-unknown-pragmas','-I'+os.environ['HLS_INCLUDE'],'-I'+str(kernel),
             '-DWEIGHTS_DIR="'+str(kernel/'firmware/weights')+'"',package/'checks/production_wrapper_csim.cpp',kernel/'model_wrapper.cpp',kernel/'firmware/prod_res256_manualA_coyote_accel.cpp','-lgmp','-pthread','-o',sim/'parity'],job,sim/'compile.log')
    command([sim/'parity',root/'runtime_cases.tsv',package/'inputs/rtl_expected.txt'],sim,sim/'csim.log')
    if 'PASS production framing/pixels/logits: 52 corpus calls + 8 RTL references' not in (sim/'csim.log').read_text():raise RuntimeError('R_S C-simulation incomplete')
    b=job/'build';b.mkdir()
    command(['cmake','-S',job/'hw','-B',b,'-DVITIS_HLS_MODE=vitis_hls','-DCOMP_CORES=4'],job,job/'configure.log')
    # Successful route_03: own fresh linked/optimized netlist, no historical DCP seed.
    (b/'pnr_shell.tcl').write_text((package/'scripts/rs_implementation.tcl').read_text().replace('@BASE@',str(b/'base.tcl')))
    for stage in ['project','synth','link','shell','bitgen']:
        command(['make','-j1',stage],b,job/(stage+'.log'))
        if stage=='project':
            cores=list(b.rglob('solution1/syn/verilog/model_wrapper.v'))
            if len(cores)!=1:raise RuntimeError('Expected unique actual R_S HLS core')
            rtl=job/'rtl';rtl.mkdir();shutil.copytree(cores[0].parent,rtl/'core')
            for name in ['production_wrapper_tb.sv','production_wrapper_sim.tcl']:shutil.copy2(package/'checks'/name,rtl/name)
            shutil.copy2(sim/'rtl_expected.txt',rtl/'rtl_expected.txt')
            command(['vivado','-mode','batch','-source',rtl/'production_wrapper_sim.tcl'],rtl,rtl/'check.log',dict(os.environ,DRIVER_RESETS='1'))
            text=(rtl/'check.log').read_text()
            if 'PASS production wrapper frames=8' not in text or 'Fatal:' in text:raise RuntimeError('R_S RTL gate incomplete')
            save(job/'rtl_gate.json',dict(status='passed',frames=8,driver_resets=1,startup_idle_cycles=20000))
        if stage=='shell':validate_timing_report(b/'reports/shell_timing_summary.rpt')
    if any(sha(job/name)!=digest for name,digest in sources.items()):raise RuntimeError('R_S build sources changed')
    bit=b/'bitstreams/cyt_top.bit'
    if not bit.is_file() or not bit.stat().st_size:raise RuntimeError('Missing R_S image')
    save(job/'identity.json',dict(variant_id='R_S',bitstream=str(bit),bitstream_sha256=sha(bit),source_manifest_sha256=sha(job/'source_manifest.json'),status='passed',board_validated=False))
    save(job/'resources.json',attribute((b/'reports/shell_utilization_hierarchical.rpt').read_text(),(b/'reports/shell_utilization.rpt').read_text(),'R_S'))
