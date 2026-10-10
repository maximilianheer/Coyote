"""Preparation for direct-host variants; only isolated copies are patched."""
import json, shutil
from prepare import HERE, MODEL, HARDWARE, copy_coyote, source_manifest, sha
DIRECT={'D_I':7,'D_N':8,'D_G':9}

def prepare_direct(root,job,state):
    if job['id']=='D_I':
        gate=json.loads((root/'conv0_gate.json').read_text())
        if gate.get('status')!='passed' or gate.get('source_sha256')!=sha(HARDWARE/'common/conv0_dataflow.hpp'):
            raise RuntimeError('conv0 parity/synthesis gate does not match maintained helper')
    dst=root/'jobs'/job['id'];dst.mkdir(parents=True,exist_ok=False)
    coyote=dst/'coyote';copy_coyote(coyote)
    src=dst/'hw/src';(src/'hdl').mkdir(parents=True)
    for name in ['direct_control.sv','elastic_fifo.sv']:
        shutil.copy2(HARDWARE/'direct'/name,src/'hdl'/name)
    variant={'D_I':'checker','D_N':'sink','D_G':'gpu_bridge'}[job['id']]
    shutil.copy2(HARDWARE/'direct'/f'{variant}.svh',src/'hdl/direct_variant.svh')
    shutil.copy2(HARDWARE/'direct/vfpga_top.svh',src/'vfpga_top.svh')
    shutil.copy2(HARDWARE/'debug_probe.svh',src/'hdl/debug_probe.svh')
    shutil.copy2(HARDWARE/'init_ip.tcl',src/'init_ip.tcl')
    if job['id']=='D_I':
        for kernel in ['preprocess_wrapper','cnn_wrapper']:
            target=src/'hls'/kernel;target.mkdir(parents=True)
            shutil.copytree(MODEL/'firmware',target/'firmware')
            for header in (HARDWARE/'common').glob('*.hpp'):shutil.copy2(header,target/header.name)
            shutil.copy2(HARDWARE/'variants'/f'{kernel}.cpp',target/f'{kernel}.cpp')
            if kernel=='cnn_wrapper':
                model=target/'firmware/prod_res256_manualA_coyote_accel.cpp'
                original=model.read_text()
                call='nnet::conv_2d_cl<layer2_t, conv0_result_t, config3>'
                if original.count(call)!=1:raise RuntimeError('Production conv0 call is not unique')
                model.write_text(original.replace('#include "parameters.h"','#include "parameters.h"\n#include "../conv0_dataflow.hpp"').replace(call,'benchmark::conv0_dataflow<layer2_t, conv0_result_t, config3>'))
        reference=dst/'reference';reference.mkdir()
        shutil.copytree(MODEL/'firmware',reference/'firmware')
        for header in (HARDWARE/'common').glob('*.hpp'):shutil.copy2(header,reference/header.name)
        for kernel in ['preprocess_wrapper','cnn_wrapper']:shutil.copy2(HARDWARE/'variants'/f'{kernel}.cpp',reference/f'{kernel}.cpp')
    shutil.copytree(HERE/'tests',dst/'tests',ignore=shutil.ignore_patterns('__pycache__'))
    host=dst/'host';host.mkdir()
    for name in ['direct_host.cpp','direct_abi.hpp','gpu_backend.hpp','direct_CMakeLists.txt']:
        shutil.copy2(HERE/'templates'/name,host/('CMakeLists.txt' if name=='direct_CMakeLists.txt' else name))
    project='opt_'+job['id'].lower()
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
set(N_STRM_AXI 2)
set(EN_MEM 0)
set(COMP_CORES 8)
set(BUILD_OPT 1)
validation_checks_hw()
load_apps(VFPGA_C0_0 "src")
create_hw()
''')
    manifest=dict(files=source_manifest(dst),variant=job['id'],attempt=job.get('attempt',1),
        conv0_dataflow=job['id']=='D_I',transport='host',hbm_enabled=False,
        maintained_hardware={str(p.relative_to(HARDWARE)):sha(p) for p in HARDWARE.rglob('*') if p.is_file()},
        build_scripts={str(p.relative_to(coyote)):sha(p) for folder in ['scripts','cmake'] for p in (coyote/folder).rglob('*') if p.is_file()})
    (dst/'source_manifest.json').write_text(json.dumps(manifest,indent=2))
    job.update(project=project,prepared=True)
    return dst
