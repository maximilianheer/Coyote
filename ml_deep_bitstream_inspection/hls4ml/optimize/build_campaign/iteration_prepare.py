"""Prepare independent iteration attempts. Never consume another iteration's firmware."""
import json, shutil
from pathlib import Path
from prepare import HERE, REPO, HARDWARE, copy_coyote, sha, source_manifest
from worker import save
ITERATIONS=HERE.parent/'iterations'

def snapshot(config, job):
    c=json.loads(config.read_text())
    required={'abi_version':3,'variant':7,'external_fifo_depth':32,'preprocessing':'R_S','first_pixel_guard':True}
    interface=dict(c['interface']);mode=interface.pop('pipeline_mode','streaming')
    if mode=='nonstreaming':required['external_fifo_depth']=65536
    if mode not in ('streaming','nonstreaming') or interface!=required:raise ValueError('Unsupported interface configuration')
    if c['model']['threshold']!=0.0:raise ValueError('This ABI requires the frozen zero threshold')
    if c['validation']['performance_admission']:raise ValueError('Performance cannot gate correctness')
    if c['build']['threads']!=4:raise ValueError('This campaign requires four implementation threads')
    if job.exists():raise FileExistsError('Attempt already exists: '+str(job))
    job.mkdir(parents=True)
    shutil.copytree(config.parent,job/'config')
    shutil.copytree(ITERATIONS/'common',job/'fixtures')
    tools=job/'tooling';tools.mkdir()
    for name in ['iteration_generate.py','iteration_cosim.py','iteration_prepare.py','iteration_worker.py','implementation_permits.py','prepare.py','worker.py','hbm_clock.py']:
        shutil.copy2(HERE/name,tools/name)
    shutil.copytree(HERE/'iteration_templates',tools/'iteration_templates')
    # Snapshot only the integration components this iteration uses.
    hardware=tools/'hardware';hardware.mkdir()
    for name in ['direct','common']:
        (hardware/name).mkdir()
    for name in ['direct_control.sv','elastic_fifo.sv','frame_buffer.sv','checker.svh','vfpga_top.svh','vfpga_top_nonstreaming.svh']:
        shutil.copy2(HARDWARE/'direct'/name,hardware/'direct'/name)
    shutil.copy2(HARDWARE/'common/frame_start.hpp',hardware/'common/frame_start.hpp')
    for name in ['debug_probe.svh','init_ip.tcl']:shutil.copy2(HARDWARE/name,hardware/name)
    (tools/'templates').mkdir()
    for name in ['direct_host.cpp','direct_abi.hpp','gpu_backend.hpp','direct_CMakeLists.txt']:
        shutil.copy2(HERE/'templates'/name,tools/'templates'/name)
    (tools/'tests').mkdir()
    for name in ['direct_control_tb.sv','direct_csim.cpp','direct_sim.tcl','frame_buffer_tb.sv','frame_buffer_synth.tcl']:
        shutil.copy2(HERE/'tests'/name,tools/'tests'/name)
    shutil.copy2(REPO/'hls4ml/pipeline/coyote_accelerator/templates/zero_in_raw_downsample.hpp.in',tools/'zero_in_raw_downsample.hpp.in')
    c=json.loads(config.read_text())
    save(job/'attempt.json',{'id':c['id'],'repo':str(REPO),'config_sha256':sha(job/'config/iteration.json'),
         'model_weights_sha256':c['model']['weights_sha256'],
         'inputs':{str(p.relative_to(job)):sha(p) for folder in ['config','fixtures','tooling'] for p in (job/folder).rglob('*') if p.is_file()}})

def package(job):
    c=json.loads((job/'config/iteration.json').read_text()); t=job/'tooling'; hw=t/'hardware'
    coyote=job/'coyote';copy_coyote(coyote)
    p=coyote/'scripts/base.tcl.in';p.write_text(p.read_text().replace('general.maxThreads 8','general.maxThreads 4'))
    src=job/'hw/src';(src/'hdl').mkdir(parents=True)
    for name in ['direct_control.sv','elastic_fifo.sv']:shutil.copy2(hw/'direct'/name,src/'hdl'/name)
    shutil.copy2(hw/'direct/checker.svh',src/'hdl/direct_variant.svh')
    nonstream=c['interface'].get('pipeline_mode','streaming')=='nonstreaming'
    if nonstream:shutil.copy2(hw/'direct/frame_buffer.sv',src/'hdl/frame_buffer.sv')
    shutil.copy2(hw/'direct'/('vfpga_top_nonstreaming.svh' if nonstream else 'vfpga_top.svh'),src/'vfpga_top.svh')
    shutil.copy2(hw/'debug_probe.svh',src/'hdl/debug_probe.svh');shutil.copy2(hw/'init_ip.tcl',src/'init_ip.tcl')
    for kernel in ['preprocess_wrapper','cnn_wrapper']:
        target=src/'hls'/kernel;target.mkdir(parents=True)
        shutil.copytree(job/'generated/firmware',target/'firmware')
        for name in ['model_types.hpp','nnet_axi_utils_stream.h',kernel+'.cpp']:
            shutil.copy2(t/'iteration_templates'/name,target/name)
        shutil.copy2(hw/'common/frame_start.hpp',target/'frame_start.hpp')
        (target/'firmware/zero_in_raw_downsample.hpp').write_text((t/'zero_in_raw_downsample.hpp.in').read_text().replace('{{ZERO_IN_PIXELS}}','65536'))
    shutil.copytree(t/'tests',job/'tests')
    for name in ['direct_pipe_tb.sv','direct_sim.tcl']:
        shutil.copy2(t/'iteration_templates'/name,job/'tests'/name)
    if nonstream:shutil.copy2(t/'iteration_templates/nonstream_pipe_tb.sv',job/'tests/direct_pipe_tb.sv')
    host=job/'host';host.mkdir()
    for name in ['direct_host.cpp','direct_abi.hpp','gpu_backend.hpp','direct_CMakeLists.txt']:
        shutil.copy2(t/'templates'/name,host/('CMakeLists.txt' if name=='direct_CMakeLists.txt' else name))
    (job/'hw/CMakeLists.txt').write_text(f'''cmake_minimum_required(VERSION 3.5)
set(CYT_DIR "{coyote}")
set(CMAKE_MODULE_PATH "${{CYT_DIR}}/cmake")
find_package(CoyoteHW REQUIRED)
project({c['id'].lower()})
set(FDEV_NAME "u55c")
set(N_REGIONS 1)
set(N_CONFIG 1)
set(EN_PR 0)
set(EN_STRM 1)
set(N_STRM_AXI 2)
set(EN_MEM 0)
set(COMP_CORES 4)
set(BUILD_OPT 1)
validation_checks_hw()
load_apps(VFPGA_C0_0 "src")
create_hw()
''')
    files=source_manifest(job)
    if any('conv0_dataflow' in p for p in files):raise RuntimeError('Custom conv0 kernel prohibited')
    save(job/'source_manifest.json',{'files':files,'variant':c['id'],'conv0_dataflow':False,
        'transport':'host','hbm_enabled':False,'pipeline_mode':'nonstreaming' if nonstream else 'streaming',
        'frame_buffer_bits':65536*16 if nonstream else 0,'generator_config_sha256':sha(job/'hls_config.json'),
        'build_scripts':{str(p.relative_to(coyote)):sha(p) for f in ['scripts','cmake'] for p in (coyote/f).rglob('*') if p.is_file()}})
