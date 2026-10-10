#!/usr/bin/env python3
"""Wait for a corrected D_I build, then run standard-driver board admission."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import time

from benchmark_identity import installed_identity, selected_hardware
from board_target import verify_host
from board_benchmark import REPO, save, sha

HERE=Path(__file__).resolve().parent


def validate(campaign, board, sink, output, launch_state=None):
    output.mkdir(parents=True,exist_ok=False)
    state=dict(status='running',stage='waiting_build',pid=os.getpid(),started_at=time.time(),
               job='D_I',diagnostic=True,benchmark_admitted=False)
    path=output/'status.json';save(path,state)
    env=dict(os.environ,OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',COYOTE_ALLOC_TYPE='HPF')
    env['PATH']='/tools/Xilinx/Vivado/2024.2/bin:'+env.get('PATH','')

    def command(stage,args):
        state.update(stage=stage,stage_started_at=time.time());save(path,state)
        with (output/(stage+'.log')).open('w') as log:
            child=subprocess.Popen(args,cwd=REPO,env=env,stdout=log,stderr=subprocess.STDOUT,preexec_fn=os.setpgrp)
            state['child_pid']=child.pid
            try:
                while child.poll() is None:
                    state['heartbeat']=time.time();save(path,state)
                    if time.time()-state['stage_started_at']>900:raise TimeoutError(stage+' timeout')
                    time.sleep(2)
            except BaseException:
                if child.poll() is None:
                    os.killpg(child.pid,signal.SIGTERM)
                    try:child.wait(timeout=5)
                    except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL);child.wait()
                raise
            if child.returncode:raise RuntimeError(f'{stage} exited {child.returncode}')

    def interrupted(signum,frame):raise InterruptedError(f'signal {signum}')
    signal.signal(signal.SIGTERM,interrupted);signal.signal(signal.SIGINT,interrupted)
    try:
        verify_host(board)
        while True:
            if launch_state and launch_state.exists():
                launch=json.loads(launch_state.read_text())
                if launch.get('status')=='failed':raise RuntimeError('Build launch gate failed')
            queue_path=campaign/'status.json'
            if queue_path.exists():
                queue=json.loads(queue_path.read_text());job=next(j for j in queue['jobs'] if j['id']=='D_I')
                state.update(build_status=job['status'],build_stage=job.get('stage'))
                if job['status']=='passed':break
                if queue.get('phase') in ('finished','needs_diagnosis') and job['status'] in ('failed','blocked'):
                    raise RuntimeError('D_I hardware build failed')
            if time.time()-state['started_at']>86400:raise TimeoutError('Board handoff deadline; build left untouched')
            state['heartbeat']=time.time();save(path,state);time.sleep(15)
        selection={name:dict(jobdir=str(directory),artifact_manifest_sha256=sha(directory/'artifact_manifest.json'))
                   for name,directory in [('D_I',campaign/'jobs/D_I'),('D_N',sink)]}
        save(output/'hardware_selection.json',selection)
        source,bit,hardware=selected_hardware(output,'D_I')
        selected_hardware(output,'D_N')
        driver=board/'software/driver/build/coyote_driver.ko'
        kernel=subprocess.check_output(['uname','-r'],text=True).strip()
        if not subprocess.check_output(['modinfo','-F','vermagic',str(driver)],text=True).startswith(kernel+' '):
            raise RuntimeError('Driver/kernel mismatch')
        state.update(bitstream_sha256=sha(bit),source_manifest_sha256=hardware['source_manifest_sha256'],
                     driver_sha256=sha(driver),stage='waiting_board');save(path,state)
        with (board/'board_device.lock').open('a') as lock:
            while True:
                try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);break
                except BlockingIOError:
                    if time.time()-state['started_at']>86400:raise TimeoutError('Board lease deadline')
                    state['heartbeat']=time.time();save(path,state);time.sleep(5)
            devices=list(Path('/dev').glob('coyote*'))
            if devices and subprocess.run(['fuser',*map(str,devices)],capture_output=True).returncode!=1:
                raise RuntimeError('Board is in use or ownership check failed')
            image=board/'installed_image.json'
            save(image,dict(status='programming',job='D_I',started_at=time.time()))
            command('program',['bash',str(REPO.parent/'util/program_hacc_local.sh'),str(bit),str(driver),'1'])
            pci=Path('/sys/bus/pci/devices/0000:c4:00.0')
            if (pci/'current_link_width').read_text().strip()!='16' or not (pci/'current_link_speed').read_text().startswith('8.0 GT/s'):
                raise RuntimeError('Unexpected PCIe speed/width')
            save(image,dict(status='ready',job='D_I',bitstream=str(bit),sha256=sha(bit),
                source_manifest_sha256=hardware['source_manifest_sha256'],driver=str(driver),driver_sha256=sha(driver),
                installed_at=time.time(),reset_diagnostic=False,diagnostic=True))
            expected=installed_identity(image,7)
            command('parity',['numactl','--physcpubind=2','--membind=0',
                str(REPO/'ml_baseline/.venv_hls4ml/bin/python'),str(HERE/'runtime_recovery.py'),str(board),'--attempt',output.name])
            result=json.loads((board/'runtime_validation.json').read_text())
            if result.get('status')!='passed' or result.get('diagnostic_inputs')!=26 or result.get('hardware_identity')!=expected:
                raise RuntimeError('Incomplete/mismatched runtime admission')
            target=board/'hardware_selection.json'
            if target.exists():
                history=board/'hardware_selection_history';history.mkdir(exist_ok=True)
                preserved=history/(sha(target)+'.json')
                if not preserved.exists():preserved.write_bytes(target.read_bytes())
            save(target,selection)
            save(output/'runtime_validation.json',result)
            state.update(status='passed',stage='complete',board_calls=520,
                         runtime_validation_sha256=sha(board/'runtime_validation.json'))
    except BaseException as error:
        state.update(status='failed',error=str(error));print(str(error),flush=True)
    state['finished_at']=time.time();save(path,state)
    return int(state['status']!='passed')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('campaign',type=Path);p.add_argument('board',type=Path)
    p.add_argument('sink',type=Path);p.add_argument('output',type=Path);p.add_argument('--launch-state',type=Path)
    a=p.parse_args();raise SystemExit(validate(a.campaign.resolve(),a.board.resolve(),a.sink.resolve(),a.output.resolve(),a.launch_state))
