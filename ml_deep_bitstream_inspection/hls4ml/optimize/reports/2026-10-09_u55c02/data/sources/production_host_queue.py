#!/usr/bin/env python3
"""Supervise production R_O/R_S host benchmarks and restore the sink."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from board_benchmark import REPO,save,sha
from board_target import verify_host
from isolation_board import validate,verified_bitstream
from benchmark_identity import selected_hardware
from benchmark_queue import notify

HERE=Path(__file__).resolve().parent


def run(board,output,original=False):
    verify_host(board)
    state=dict(status='running',pid=os.getpid(),started_at=time.time(),jobs=[])
    save(output/'status.json',state)
    env=dict(os.environ,OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',COYOTE_ALLOC_TYPE='HPF')
    env['PATH']='/tools/Xilinx/Vivado/2024.2/bin:'+env.get('PATH','')
    def command(stage,args,folder):
        state.update(stage=stage,heartbeat=time.time());save(output/'status.json',state)
        with (folder/(stage+'.log')).open('w') as log:
            child=subprocess.Popen(args,cwd=REPO,env=env,stdout=log,stderr=subprocess.STDOUT,preexec_fn=os.setpgrp)
            try:
                start=time.monotonic()
                while child.poll() is None:
                    if time.monotonic()-start>900:raise TimeoutError(stage)
                    state.update(child_pid=child.pid,heartbeat=time.time());save(output/'status.json',state);time.sleep(2)
                if child.returncode:raise RuntimeError(f'{stage} exited {child.returncode}')
            except BaseException:
                if child.poll() is None:
                    os.killpg(child.pid,signal.SIGTERM)
                    try:child.wait(timeout=5)
                    except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL);child.wait()
                raise
    python=str(REPO/'ml_baseline/.venv_hls4ml/bin/python')
    try:
        for ident,campaign in ([('ORIGINAL',None)] if original else [('R_O','production_isolation_20261008_132304'),('R_S','parallel_resume_20261009_1550')]):
            folder=output/ident;folder.mkdir();jobdir=board.parent/campaign/'jobs'/ident if campaign else None
            item=dict(job=ident,status='running',stage='board_parity');state['jobs'].append(item);save(output/'status.json',state)
            try:
                if ident=='ORIGINAL':
                    frozen=REPO/'hls4ml/reproducibility/prod_res256_coyote_accel_downsampler_hls4ml_e2e_20260524'
                    project=board.parent/'board_benchmark_20261008_130137/software/production_current_project'
                    bit=(project/'build/prod_res256_manualA_coyote_accel_cyt_hw/bitstreams/cyt_top.bit').resolve()
                    manifest=json.loads((frozen/'manifest.json').read_text())
                    record=next(r for r in manifest['files'] if (frozen/r['path']).resolve()==bit)
                    if sha(bit)!=record['sha256'] or bit.stat().st_size!=record['bytes']:raise RuntimeError('Frozen image identity mismatch')
                    previous=json.loads((board.parent/'board_benchmark_20261008_130137/diagnostics/production_control_current_stack_01/production_tolerances.json').read_text())
                    sw=project/'build/prod_res256_manualA_coyote_accel_cyt_sw'
                    if (sha(bit)!=previous['bitstream_sha256'] or sha(sw/'lib/libCoyoteInference.so')!=previous['library_sha256'] or sha(sw/'libCoyote.so')!=previous['coyote_library_sha256']):raise RuntimeError('Production reference identity mismatch')
                    digest=sha(frozen/'manifest.json');save(folder/'original_identity.json',dict(bitstream=str(bit),bitstream_sha256=sha(bit),package_manifest_sha256=digest,project=str(project),previous_control=previous['status']))
                else:
                    command(ident+'_admission',['python3',str(HERE/'isolation_board.py'),str(jobdir.parent.parent),str(board),ident,str(folder/'admission')],folder)
                    bit,digest=verified_bitstream(jobdir);project=jobdir/'runtime_project'
                with (board/'board_device.lock').open('a') as lock:
                    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                    if ident=='ORIGINAL':
                        devices=list(Path('/dev').glob('coyote*'))
                        if not devices or subprocess.run(['fuser',*map(str,devices)],capture_output=True).returncode!=1:raise RuntimeError('Device ownership check failed')
                        driver=board/'software/driver/build/coyote_driver.ko'
                        kernel=subprocess.check_output(['uname','-r'],text=True).strip()
                        if not subprocess.check_output(['modinfo','-F','vermagic',str(driver)],text=True).startswith(kernel+' '):raise RuntimeError('Driver kernel mismatch')
                        save(board/'installed_image.json',dict(status='programming',job=ident))
                        command('program_original',['bash',str(REPO.parent/'util/program_hacc_local.sh'),str(bit),str(driver),'1'],folder)
                        pci=Path('/sys/bus/pci/devices/0000:c4:00.0')
                        if (pci/'current_link_width').read_text().strip()!='16' or not (pci/'current_link_speed').read_text().startswith('8.0 GT/s'):raise RuntimeError('PCIe link mismatch')
                        save(board/'installed_image.json',dict(status='ready',job=ident,bitstream=str(bit),sha256=sha(bit),source_manifest_sha256=digest,driver=str(driver),driver_sha256=sha(driver),installed_at=time.time(),reset_diagnostic=False))
                    image=json.loads((board/'installed_image.json').read_text())
                    if image['job']!=ident or image['sha256']!=sha(bit):raise RuntimeError('Image changed after admission')
                    devices=list(Path('/dev').glob('coyote*'))
                    if not devices or subprocess.run(['fuser',*map(str,devices)],capture_output=True).returncode!=1:raise RuntimeError('Device ownership check failed')
                    for mode in ['gate','smoke','pilot','full']:
                        item['stage']=mode
                        command(ident+'_'+mode,['numactl','--physcpubind=2','--membind=0',python,str(HERE/'production_host_benchmark.py'),str(board),ident,str(project),str(folder),mode],folder)
                        result=json.loads((folder/(mode+'.analysis.json')).read_text())
                        expected={'gate':260,'smoke':30,'pilot':24,'full':2640}[mode]
                        if result['status']!='passed' or result['trials']!=expected:raise RuntimeError('Incomplete collection')
                    item.update(status='passed',stage='complete',finished_at=time.time(),calls=2640)
            except BaseException as error:
                item.update(status='failed',error=str(error),finished_at=time.time());raise
            finally:save(output/'status.json',state)
        with (board/'board_device.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            source,bit,hardware=selected_hardware(board,'D_N');driver=board/'software/driver/build/coyote_driver.ko'
            save(board/'installed_image.json',dict(status='programming',job='D_N'))
            command('restore_sink',['bash',str(REPO.parent/'util/program_hacc_local.sh'),str(bit),str(driver),'1'],output)
            pci=Path('/sys/bus/pci/devices/0000:c4:00.0')
            if (pci/'current_link_width').read_text().strip()!='16' or not (pci/'current_link_speed').read_text().startswith('8.0 GT/s'):raise RuntimeError('PCIe link mismatch')
            save(board/'installed_image.json',dict(status='ready',job='D_N',bitstream=str(bit),sha256=sha(bit),source_manifest_sha256=hardware['source_manifest_sha256'],driver=str(driver),driver_sha256=sha(driver),installed_at=time.time(),reset_diagnostic=False))
        state.update(status='passed',stage='complete',sink_restored=True)
    except BaseException as error:state.update(status='failed',error=str(error));print(error,flush=True)
    state['finished_at']=time.time();save(output/'status.json',state)
    return state['status']!='passed'


def monitor(board,output):
    sent=set()
    while True:
        path=output/'status.json'
        if not path.exists():time.sleep(2);continue
        state=json.loads(path.read_text())
        if state['status']=='running' and not Path('/proc/'+str(state['pid'])).exists():
            state.update(status='failed',error='Worker terminated')
            for j in state['jobs']:
                if j['status']=='running':j.update(status='failed',error='Worker terminated')
            save(path,state)
        for j in state['jobs']:
            key=(j['job'],j['status'])
            if j['status'] in ('passed','failed') and key not in sent:
                detail='2,400 measured + 240 warmups; production result DMA; all logits passed' if j['status']=='passed' else j.get('error','inspect logs')
                if notify(board,f"{j['job']} benchmark {j['status']}: {detail}. Results: {output/j['job']}"):
                    sent.add(key);save(output/'notifications_state.json',dict(sent=sorted(sent)))
        if state['status']!='running' and all((j['job'],j['status']) in sent for j in state['jobs']):return
        time.sleep(3)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['run','monitor']);p.add_argument('board',type=Path);p.add_argument('output',type=Path);p.add_argument('--original',action='store_true');a=p.parse_args()
    if a.action=='run':sys.exit(run(a.board.resolve(),a.output.resolve(),a.original))
    else:monitor(a.board.resolve(),a.output.resolve())
