#!/usr/bin/env python3
"""One isolated job; no programming or network operations in the worker."""
import argparse
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import time
from prepare import VARIANTS, verify_sources, sha, configure_refinement

def save(path, data):
    tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(data,indent=2));tmp.replace(path)

def validate_timing_report(path):
    text = path.read_text(errors='replace')
    # Vivado 2024.2 writes "All user specified timing constraints are met."
    if re.search(r'timing constraints are not met|not all user specified timing constraints are met', text, re.I):
        raise RuntimeError('Timing failure: '+str(path))
    if not re.search(r'^\s*(?:All user specified )?Timing constraints are met\.?\s*$', text, re.I | re.M):
        raise RuntimeError('Cannot verify timing: '+str(path))

def final_timing_reports(build, ident):
    # PR app routing supersedes the preliminary, empty shell implementation.
    # Diagnostic designs have EN_PR=0 and use the shell checkpoint directly.
    paths = ([build/'reports/config_0/shell_timing_summary_c0.rpt']
             if ident.startswith('H') else [build/'reports/shell_timing_summary.rpt'])
    for path in paths:
        if not path.is_file(): raise RuntimeError('Missing final timing report: '+str(path))
        validate_timing_report(path)
    return paths

def collect_artifacts(build, ident):
    reports = final_timing_reports(build, ident)
    bits = list((build/'bitstreams').rglob('*.bit'))
    bins = list((build/'bitstreams').rglob('*.bin'))
    if not bits or any(p.stat().st_size == 0 for p in bits+bins):
        raise RuntimeError('Missing or empty bitstream')
    artifacts = dict(utilization_reports=[str(p) for p in (build/'reports').rglob('*utilization*.rpt')],
        shared_debug_overhead='ila_benchmark_keepalive: one 1-bit probe, depth 1024',
        bitstreams=[str(p) for p in bits+bins], timing_reports=[str(p) for p in reports])
    if ident.startswith('H'):
        partial = [p for p in bins if p.name.startswith('vfpga_')]
        if len(partial) != 1: raise RuntimeError(f'Expected one partial .bin, found {len(partial)}')
        artifacts.update(partial=str(partial[0]), partial_bytes=partial[0].stat().st_size)
    return artifacts

def run(jobdir, job, validate_only=False):
    env=os.environ.copy()
    env['PATH']='/tools/Xilinx/Vivado/2024.2/bin:/tools/Xilinx/Vitis_HLS/2024.2/bin:'+env['PATH']
    env.update(OMP_NUM_THREADS='8',OPENBLAS_NUM_THREADS='1')
    # Tools may write user caches; keep those in the campaign, not the frozen repo.
    env['TMPDIR']=str(jobdir/'tmp');(jobdir/'tmp').mkdir(exist_ok=True)
    progress={'status':'running','stage':'init','started_at':time.time(),'pid':os.getpid()}
    progress_path=jobdir/('validation_progress.json' if validate_only else 'progress.json')
    def command(stage,argv,cwd):
        progress.update(stage=stage,stage_started_at=time.time());save(progress_path,progress)
        print(f'[{time.ctime()}] {stage}: {argv}',flush=True)
        with (jobdir/f'{stage}.log').open('w') as log:
            result=subprocess.run(argv,cwd=cwd,env=env,stdout=log,stderr=subprocess.STDOUT)
        if result.returncode: raise RuntimeError(f'{stage} exited {result.returncode}; see {stage}.log')
    try:
        hw=jobdir/'hw';build=jobdir/'build';build.mkdir(exist_ok=True)
        manifest_hash = verify_sources(jobdir)
        validation_path = jobdir/'validation.json'
        validation = json.loads(validation_path.read_text()) if validation_path.exists() else {}
        if job['id'] in VARIANTS and (validate_only or validation.get('status') != 'passed'
                                    or validation.get('source_manifest_sha256') != manifest_hash):
            command('host_configure',['cmake','-S',str(jobdir/'host'),'-B',str(jobdir/'host_build'),
                '-DCOYOTE_SW='+str(jobdir/'coyote/sw')],jobdir)
            command('host_build',['cmake','--build',str(jobdir/'host_build'),'--parallel','2'],jobdir)
            kr=hw/'src/hls/model_wrapper'
            common=['g++','-O1','-std=c++14','-Wno-unknown-pragmas',
                    '-I/tools/Xilinx/Vitis/2024.2/include','-I'+str(kr),
                    '-DWEIGHTS_DIR="'+str(kr/'firmware/weights')+'"']
            command('csim_baseline_compile',common+['-Dmodel_wrapper=baseline_wrapper','-c',str(jobdir/'reference/model_wrapper.cpp'),'-o','baseline.o'],jobdir)
            defs=['-DBENCH_VARIANT='+str(VARIANTS[job['id']])]
            if job['id'] not in ('U','S_I'):defs+=['-DBENCH_PHASE']
            command('csim_compile',common+defs+[str(jobdir/'csim.cpp'),str(kr/'model_wrapper.cpp'),
                str(kr/'firmware/prod_res256_manualA_coyote_accel.cpp'),'baseline.o',
                '/usr/lib/x86_64-linux-gnu/libgmp.so.10','-pthread','-o','csim'],jobdir)
            command('csim',[str(jobdir/'csim')],jobdir)
            rtl = jobdir/'rtl_validation';rtl.mkdir(exist_ok=True)
            command('rtl_compile',['xvlog','--sv',str(hw/'src/hdl/benchmark_control.sv'),
                    str(jobdir/'tests/control_tb.sv')],rtl)
            command('rtl_elaborate',['xelab','control_tb','-s','control_test',
                    '-generic_top','VARIANT='+str(VARIANTS[job['id']])],rtl)
            command('rtl_simulate',['xsim','control_test','-runall'],rtl)
            if 'PASS variant=' not in (jobdir/'rtl_simulate.log').read_text():
                raise RuntimeError('RTL simulation did not report a pass')
            if job['id']=='S_I':
                command('streaming_control_compile',['xvlog','--sv',str(jobdir/'tests/streaming_control_tb.sv')],rtl)
                command('streaming_control_elaborate',['xelab','streaming_control_tb','-s','streaming_control'],rtl)
                command('streaming_control_simulate',['xsim','streaming_control','-runall'],rtl)
                if 'PASS streaming counters' not in (jobdir/'streaming_control_simulate.log').read_text():
                    raise RuntimeError('Streaming control simulation did not pass')
            if verify_sources(jobdir) != manifest_hash:
                raise RuntimeError('Sources changed during validation')
            save(validation_path,dict(status='passed',source_manifest_sha256=manifest_hash,
                 validated_at=time.time(),variant=job['id'],
                 logs={name:sha(jobdir/name) for name in ['csim.log','rtl_simulate.log','host_build.log']}))
        if validate_only:
            progress.update(status='pending',stage='validated',validation=str(validation_path))
            save(progress_path,progress)
            return 0
        command('configure',['cmake','-S',str(hw),'-B',str(build),'-DVITIS_HLS_MODE=vitis_hls','-DCOMP_CORES=8',
            '-DVIVADO_ROOT_DIR=/tools/Xilinx/Vivado/2024.2','-DVITIS_HLS_ROOT_DIR=/tools/Xilinx/Vitis_HLS/2024.2'],jobdir)
        stages = ['project','synth','link','shell']
        if job['id'].startswith('H'): stages.append('app')
        from reuse_hello import try_reuse
        reused_shell = try_reuse(jobdir, job)
        if reused_shell:stages=['app']
        for stage in stages+['bitgen']:
            if stage == 'app' and job.get('narrow'):
                configure_refinement(jobdir)
            argv = (['vivado','-mode','batch','-source',str(build/('flow_dyn.tcl' if stage=='app' else 'bitgen.tcl'))]
                    if reused_shell else ['make','-j1',stage])
            command(stage,argv,build)
            if job.get('hbm_axi_mhz') and stage == 'project':
                from hbm_clock import verify_generated_hbm_clock
                clock_inputs = verify_generated_hbm_clock(build, job['hbm_axi_mhz'])
                save(jobdir/'hbm_generated_validation.json',dict(hbm_axi_mhz=job['hbm_axi_mhz'],
                    generated_ip_hashes=clock_inputs,validated_at=time.time()))
            if stage == 'app':
                app_log = (jobdir/'app.log').read_text(errors='replace')
                if 'not supported in the xdc constraint file' in app_log:
                    raise RuntimeError('Unsupported XDC command; cannot validate intended floorplan')
                if job.get('narrow') and 'FLOORPLAN_REFINEMENT_APPLIED' not in app_log:
                    raise RuntimeError('Missing verified post-link floorplan refinement')
            if stage == ('app' if job['id'].startswith('H') else 'shell'):
                final_timing_reports(build, job['id'])
                if job.get('hbm_axi_mhz'):
                    from hbm_clock import verify_report_hbm_clock
                    verify_report_hbm_clock(build/'reports/shell_timing_summary.rpt', job['hbm_axi_mhz'])
            if stage=='project' and job['id']=='S_I':
                # Gate expensive implementation on actual synthesized RTL behavior.
                command('streaming_rtl_simulate',[sys.executable,
                    str(Path(__file__).with_name('check_streaming_rtl.py')),str(jobdir)],jobdir)
                if 'PASS synthesized streaming RTL' not in (jobdir/'streaming_rtl_simulate.log').read_text():
                    raise RuntimeError('Synthesized streaming RTL did not pass')

        artifacts = collect_artifacts(build, job['id'])
        if job['id']=='S_I':
            bitlog=(jobdir/'bitgen.log').read_text(errors='replace')
            if 'open_checkpoint' not in bitlog or 'write_bitstream' not in bitlog or 'Chipscope 16-320' in bitlog:
                raise RuntimeError('Missing successful real-IP checkpoint reopening/bitgen evidence')
            if verify_sources(jobdir)!=manifest_hash: raise RuntimeError('Sources changed during build')
        progress.update(status='passed',stage='complete',artifacts=artifacts,
                        hardware_validated=False,finished_at=time.time())
    except Exception as error:
        progress.update(status='failed',error=str(error),finished_at=time.time())
        print(str(error),file=sys.stderr,flush=True)
    save(progress_path,progress)
    return 0 if progress['status']=='passed' else 1

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('jobdir',type=Path)
    ap.add_argument('--validate-only',action='store_true');a=ap.parse_args()
    sys.exit(run(a.jobdir.resolve(),json.loads((a.jobdir/'job.json').read_text()),a.validate_only))
