#!/usr/bin/env python3
"""Validate completed isolation builds on the board through production result DMA.

Diagnostic only: never opens the D_I/D_N benchmark correctness gate. Run in tmux;
the hardware campaign monitor owns build-outcome notifications.
"""
import argparse
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from board_target import verify_host
from board_benchmark import REPO, save, sha
from prepare import verify_sources
from prepare_production_runtime import prepare
from worker import validate_timing_report
from parity_gate import load_tolerances

HERE=Path(__file__).resolve().parent

def verified_bitstream(jobdir):
    state=json.loads((jobdir/'progress.json').read_text())
    if state.get('status')!='passed' or state.get('stage')!='complete':
        raise RuntimeError('Hardware build is not complete')
    source_hash=verify_sources(jobdir)
    validation=json.loads((jobdir/'validation.json').read_text())
    if validation.get('status')!='passed' or validation.get('source_manifest_sha256')!=source_hash:
        raise RuntimeError('Source validation mismatch')
    artifacts=state['artifacts']
    bits=[Path(p) for p in artifacts['bitstreams'] if Path(p).name=='cyt_top.bit']
    if len(bits)!=1:raise RuntimeError('Expected one full-device bitstream')
    bit=bits[0].resolve()
    if not bit.is_relative_to(jobdir.resolve()) or sha(bit)!=artifacts.get('sha256',{}).get(str(bits[0])):
        raise RuntimeError('Bitstream identity/hash mismatch')
    if not artifacts.get('timing_reports'):raise RuntimeError('Missing timing reports')
    for report in artifacts['timing_reports']:validate_timing_report(Path(report))
    if 'PASS production wrapper frames=8' not in (jobdir/'wrapper_rtl.log').read_text():
        raise RuntimeError('Full wrapper RTL gate is missing')
    if ((jobdir/'hw/src/hls/model_wrapper/frame_start.hpp').exists()
            and 'PASS production wrapper frames=8 driver_resets=1' not in (jobdir/'wrapper_rtl.log').read_text()):
        raise RuntimeError('First-pixel launch fix requires the second-reset RTL gate')
    if jobdir.name=='R_SO_T':
        from production_candidate import verify_rtl
        verify_rtl(jobdir,jobdir/'rtl_validation')
    return bit,source_hash

def validate(campaign,board,ident,output,wait=False,launch_state=None,priority_status=None):
    jobdir=campaign/'jobs'/ident
    output.mkdir(parents=True,exist_ok=False)
    state=dict(status='running',stage='waiting_build',job=ident,pid=os.getpid(),started_at=time.time())
    path=output/'status.json';save(path,state)
    env=dict(os.environ,OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',COYOTE_ALLOC_TYPE='HPF')
    env['PATH']='/tools/Xilinx/Vivado/2024.2/bin:'+env.get('PATH','')
    def command(stage,args,timeout=900):
        state.update(stage=stage,stage_started_at=time.time());save(path,state)
        with (output/(stage+'.log')).open('w') as log:
            proc=subprocess.Popen(args,cwd=REPO,env=env,stdout=log,stderr=subprocess.STDOUT,preexec_fn=os.setpgrp)
            state['child_pid']=proc.pid;save(path,state)
            try:
                while proc.poll() is None:
                    state['heartbeat']=time.time();save(path,state)
                    if time.time()-state['stage_started_at']>timeout:raise TimeoutError(stage+' timeout')
                    time.sleep(2)
            except BaseException:
                os.killpg(proc.pid,signal.SIGTERM)
                try:proc.wait(timeout=5)
                except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGKILL);proc.wait()
                raise
            if proc.returncode:raise RuntimeError(f'{stage} exited {proc.returncode}; inspect {output}')
    try:
        verify_host(board)
        while wait:
            if time.time()-state['started_at']>86400:raise TimeoutError('Build-to-board handoff deadline; build left untouched')
            if launch_state and launch_state.exists() and json.loads(launch_state.read_text()).get('status')=='failed':
                raise RuntimeError('Build launch gate failed')
            if not (campaign/'status.json').exists():
                state['heartbeat']=time.time();save(path,state);time.sleep(15);continue
            queue=json.loads((campaign/'status.json').read_text())
            job=next(j for j in queue['jobs'] if j['id']==ident)
            if job['status']=='passed':
                priority=next((j for j in queue['jobs'] if j['id']=='D_I'),{})
                if priority_status and priority.get('status')=='passed':
                    previous=json.loads(priority_status.read_text()) if priority_status.exists() else {}
                    if previous.get('status') not in ('passed','failed'):
                        state.update(stage='waiting_priority_board',heartbeat=time.time());save(path,state);time.sleep(5);continue
                break
            if queue.get('phase') in ('finished','needs_diagnosis') and job['status'] in ('failed','blocked'):
                raise RuntimeError('Hardware build failed; preserve this board attempt and inspect campaign')
            state.update(heartbeat=time.time(),build_status=job['status'],build_stage=job.get('stage'))
            save(path,state);time.sleep(30)
        bit,source_hash=verified_bitstream(jobdir)
        if ident=='R_SO_T':
            from production_candidate import prerequisites
            prerequisites(json.loads((campaign/'status.json').read_text()))
        project=prepare(jobdir,bit)
        tolerance_file=board/'production_tolerances.json'
        if len(load_tolerances(tolerance_file))!=26:raise RuntimeError('Incomplete production reference')
        expected=dict(bitstream_sha256=sha(bit),
            library_sha256=sha(jobdir/'host_build/lib/libCoyoteInference.so'),
            coyote_library_sha256=sha(jobdir/'host_build/coyote/libcoyote.so'),
            cases_sha256=sha(board/'diagnostics/runtime_cases.tsv'),
            acceptance_tolerances_sha256=sha(tolerance_file))
        driver=board/'software/driver/build/coyote_driver.ko'
        kernel=subprocess.check_output(['uname','-r'],text=True).strip()
        if not subprocess.check_output(['modinfo','-F','vermagic',str(driver)],text=True).startswith(kernel+' '):
            raise RuntimeError('Driver/kernel mismatch')
        state.update(bitstream=str(bit),bitstream_sha256=sha(bit),source_manifest_sha256=source_hash,
            driver_sha256=sha(driver),project=str(project))
        save(path,state)
        with (board/'board_device.lock').open('a') as lock:
            while True:
                try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);break
                except BlockingIOError:
                    if time.time()-state['started_at']>86400:raise TimeoutError('Board lease deadline')
                    state.update(stage='waiting_board',heartbeat=time.time());save(path,state);time.sleep(5)
            devices=list(Path('/dev').glob('coyote*'))
            if devices:
                ownership=subprocess.run(['fuser',*map(str,devices)],capture_output=True)
                if ownership.returncode!=1:raise RuntimeError('Board is in use or ownership check failed; no programming attempted')
            save(board/'installed_image.json',dict(status='programming',job=ident,started_at=time.time()))
            command('program',['bash',str(REPO.parent/'util/program_hacc_local.sh'),str(bit),str(driver),'1'])
            pci=Path('/sys/bus/pci/devices/0000:c4:00.0')
            if (pci/'current_link_width').read_text().strip()!='16' or not (pci/'current_link_speed').read_text().startswith('8.0 GT/s'):
                raise RuntimeError('Unexpected PCIe speed/width')
            save(board/'installed_image.json',dict(status='ready',job=ident,bitstream=str(bit),sha256=sha(bit),
                source_manifest_sha256=source_hash,driver=str(driver),driver_sha256=sha(driver),
                installed_at=time.time(),diagnostic=True,reset_diagnostic=False))
            command('parity',['numactl','--physcpubind=2','--membind=0',str(REPO/'ml_baseline/.venv_hls4ml/bin/python'),
                str(HERE/'production_control.py'),str(board/'diagnostics/runtime_cases.tsv'),str(output),
                '--project',str(project),'--acceptance-tolerances',str(board/'production_tolerances.json')]
                + (['--persistent','--passive-monitor'] if ident=='R_SO_T' else []))
            result=json.loads((output/'isolation_validation.json').read_text())
            if (result['status']!='passed' or len(result['inputs'])!=26 or
                result['policy']!='isolation validation against frozen production tolerances' or
                any(result.get(k)!=v for k,v in expected.items())):
                raise RuntimeError('Isolation validation incomplete or mismatched')
            if ident=='R_SO_T':
                monitor=result.get('passive_timestamps',{})
                if monitor.get('status')!='passed' or monitor.get('frames')!=260:
                    raise RuntimeError('Candidate requires 260 valid passive captures')
            state.update(status='passed',stage='complete',board_calls=260)
    except Exception as error:
        state.update(status='failed',error=str(error));print(str(error),flush=True)
    state['finished_at']=time.time();save(path,state)
    return 0 if state['status']=='passed' else 1

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('campaign',type=Path);p.add_argument('board',type=Path)
    p.add_argument('job',choices=['R_O','R_S','R_SO_T','both']);p.add_argument('output',type=Path);p.add_argument('--wait',action='store_true')
    p.add_argument('--launch-state',type=Path);p.add_argument('--priority-status',type=Path)
    a=p.parse_args()
    if a.job=='both':
        a.output.mkdir(parents=True,exist_ok=False)
        # Separate attempts; a numerical failure in R_O does not skip R_S.
        results=[validate(a.campaign.resolve(),a.board.resolve(),job,(a.output/job).resolve(),a.wait,a.launch_state,a.priority_status) for job in ['R_O','R_S']]
        sys.exit(max(results))
    sys.exit(validate(a.campaign.resolve(),a.board.resolve(),a.job,a.output.resolve(),a.wait,a.launch_state,a.priority_status))
