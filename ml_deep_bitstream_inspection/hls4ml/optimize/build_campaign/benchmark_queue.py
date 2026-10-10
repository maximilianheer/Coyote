#!/usr/bin/env python3
"""Local board deployment/benchmark workers and persistent outcome-only monitor."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import time
from board_target import verify_host
from board_benchmark import REPO,save,sha,analyze,plots
from benchmark_identity import selected_hardware

HERE=Path(__file__).resolve().parent
SOCKET='coyote-benchmark'

def notify(root,message):
    p=subprocess.run(['curl','--fail','--silent','--show-error','--connect-timeout','10','--max-time','30',
        '-H','Title: Coyote benchmarks','--data-binary',message,'https://ntfy.sh/coyote-build-sdeheredia'],capture_output=True,text=True)
    with (root/'notifications.jsonl').open('a') as f:
        f.write(json.dumps(dict(time=time.time(),sent=p.returncode==0,message=message,response=p.stdout if p.returncode==0 else p.stderr))+'\n')
    return p.returncode==0

def worker(root,job,number):
    attempt=root/job/f'attempt_{number:02d}';attempt.mkdir(exist_ok=False)
    state=dict(job=job,attempt=number,status='running',stage='preflight',pid=os.getpid(),started_at=time.time(),heartbeat=time.time())
    path=attempt/'status.json';save(path,state)
    env=os.environ.copy();env.update(MPLCONFIGDIR=str(root/'software/matplotlib'),OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1')
    env['PATH']='/tools/Xilinx/Vivado/2024.2/bin:'+env.get('PATH','')
    board_lock=None
    def command(stage,args,cwd=None,limit=900):
        state.update(stage=stage,stage_started_at=time.time(),heartbeat=time.time());save(path,state)
        print(stage,shlex.join(args),flush=True)
        with (attempt/(stage+'.log')).open('w') as log:
            p=subprocess.Popen(args,cwd=cwd or REPO,env=env,stdout=log,stderr=subprocess.STDOUT,preexec_fn=os.setpgrp)
            state['child_pid']=p.pid;save(path,state)
            while p.poll() is None:
                state['heartbeat']=time.time();save(path,state)
                if time.time()-state['stage_started_at']>limit:
                    os.killpg(p.pid,signal.SIGTERM)
                    try:p.wait(timeout=5)
                    except subprocess.TimeoutExpired:os.killpg(p.pid,signal.SIGKILL);p.wait()
                    raise RuntimeError(f'{stage} exceeded {limit}s; inspect process tree before reset')
                time.sleep(2)
            if p.returncode:raise RuntimeError(f'{stage} exited {p.returncode}; see {attempt/stage}.log')
    try:
        verify_host(root)
        library=root/'software/runtime_build/libCoyoteInferenceCampaign.so'
        validation=json.loads((root/'runtime_validation.json').read_text())
        if validation['status']!='passed' or validation['library_sha256']!=sha(library):
            raise RuntimeError('adapted runtime has not passed correctness validation')
        if validation['coyote_library_sha256']!=sha(library.parent/'coyote/libcoyote.so'):
            raise RuntimeError('Coyote library changed since validation')
        if validation['tolerances_sha256']!=sha(root/'production_tolerances.json'):
            raise RuntimeError('production tolerances changed since validation')
        source,bitstream,hardware=selected_hardware(root,job)
        driver=root/'software/driver/build/coyote_driver.ko'
        parity_hardware=validation.get('hardware_identity',{})
        if parity_hardware.get('driver_sha256')!=sha(driver) or parity_hardware.get('job')!='D_I':
            raise RuntimeError('Runtime parity is not bound to the selected standard driver/checker')
        if job=='D_I' and any(parity_hardware.get(key)!=hardware[key] for key in ('job','bitstream_sha256','source_manifest_sha256')):
            raise RuntimeError('Runtime parity belongs to a different checker build')
        kernel=subprocess.check_output(['uname','-r'],text=True).strip()
        if not subprocess.check_output(['modinfo','-F','vermagic',str(driver)],text=True).startswith(kernel+' '):raise RuntimeError('driver kernel mismatch')
        board_lock=(root/'board_device.lock').open('a')
        lease_started=time.time()
        while True:
            try:
                fcntl.flock(board_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.time()-lease_started>3600:
                    raise TimeoutError('Board lease unavailable for one hour; existing owner left untouched')
                state.update(stage='waiting_board',heartbeat=time.time());save(path,state);time.sleep(5)
        devices=[p for pattern in ['/dev/coyote*','/dev/xclmgmt*','/dev/dri/renderD128'] for p in __import__('glob').glob(pattern)]
        if devices:
            busy=subprocess.run(['fuser',*devices],capture_output=True,text=True)
            if busy.returncode!=1:raise RuntimeError('board device is in use or ownership check failed: '+busy.stdout.strip())
        # Programming includes PCIe re-enumeration; never rely on its exit status alone.
        save(root/'installed_image.json',dict(status='programming',job=job,started_at=time.time()))
        command('program',['bash',str(REPO.parent/'util/program_hacc_local.sh'),str(bitstream),str(driver),'1'],cwd=REPO.parent/'util')
        command('board_state',['bash','-c','ls -l /dev/coyote*; lspci -Dnn; lsmod | grep coyote; sudo -n dmesg | tail -n 100'])
        # Confirm PCIe width/speed at the original physical slot after hotplug.
        pci=Path('/sys/bus/pci/devices/0000:c4:00.0')
        if (pci/'current_link_width').read_text().strip()!='16' or not (pci/'current_link_speed').read_text().startswith('8.0 GT/s'):
            raise RuntimeError('unexpected PCIe speed/width after programming')
        save(root/'installed_image.json',dict(status='ready',job=job,bitstream=str(bitstream),sha256=hardware['bitstream_sha256'],
            source_manifest_sha256=hardware['source_manifest_sha256'],driver=str(driver),driver_sha256=sha(driver),
            installed_at=time.time(),reset_diagnostic=False,diagnostic=False))
        variant='7' if job=='D_I' else '8'
        executable=HERE/'runtime_benchmark.py'
        python=REPO/'ml_baseline/.venv_hls4ml/bin/python'
        for mode,count,warm in [('smoke','2','0'),('pilot','10','2'),('full','200','20')]:
            command(mode,['numactl','--physcpubind=2','--membind=0',str(python),str(executable),str(root/('cases.tsv' if mode=='full' else mode+'.tsv')),
                str(attempt/(mode+'.csv')),str(attempt/(mode+'.clock.csv')),variant,count,warm,
                '--library',str(library),'--tolerances',str(root/'production_tolerances.json'),
                '--image-manifest',str(root/'installed_image.json')],limit=900)
            state.update(stage=mode+'_analysis',heartbeat=time.time());save(path,state)
            result=analyze(root,attempt,mode)
            print(mode,'validated',result['trials'],'trials',flush=True)
        state.update(status='passed',stage='complete',artifact_manifest_sha256=sha(source/'artifact_manifest.json'),
            bitstream_sha256=sha(bitstream),driver_sha256=sha(driver),runner_sha256=sha(executable),
            library_sha256=sha(library),tolerances_sha256=sha(root/'production_tolerances.json'),allocation='HPF')
    except BaseException as e:
        state.update(status='failed',error=str(e));print('BENCHMARK_FAILED',e,flush=True)
    finally:
        if board_lock is not None:board_lock.close()
    state.update(finished_at=time.time(),heartbeat=time.time());save(path,state)
    return 0 if state['status']=='passed' else 1

def queue(root):
    session='benchmark_'+root.name
    state=dict(phase='running',pid=os.getpid(),tmux_session=session,heartbeat=time.time(),jobs=[])
    save(root/'status.json',state)
    for job in ['D_I','D_N']:
        # A new queue invocation resumes successful jobs; failed attempts are preserved.
        attempts=sorted((root/job).glob('attempt_*/status.json'))
        latest=json.loads(attempts[-1].read_text()) if attempts else None
        if latest and latest['status']=='passed':state['jobs'].append(latest);continue
        number=(latest['attempt']+1) if latest else 1
        log=root/'logs'/f'{job}_{number:02d}.log'
        args=[sys.executable,str(HERE/'benchmark_queue.py'),'worker',str(root),'--job',job,'--attempt',str(number)]
        cmd='exec '+shlex.join(args)+' > '+shlex.quote(str(log))+' 2>&1'
        subprocess.run(['tmux','-L',SOCKET,'new-window','-t',session,'-n',job,cmd],check=True)
        path=root/job/f'attempt_{number:02d}/status.json'
        started=time.time()
        while True:
            state['heartbeat']=time.time()
            if path.exists():
                try:current=json.loads(path.read_text())
                except json.JSONDecodeError:time.sleep(1);continue
                state['jobs']=[j for j in state['jobs'] if j['job']!=job]+[current]
                if current['status'] in ['passed','failed']:break
                if not Path('/proc/'+str(current['pid'])).exists():
                    current.update(status='failed',error='benchmark worker disappeared',finished_at=time.time());save(path,current)
                    state['jobs']=[j for j in state['jobs'] if j['job']!=job]+[current];break
            elif time.time()-started>30:
                raise RuntimeError('benchmark worker did not start')
            save(root/'status.json',state);time.sleep(2)
        if current['status']=='failed':
            state['phase']='needs_diagnosis';save(root/'status.json',state);return 1
    attempts=[root/j['job']/f"attempt_{j['attempt']:02d}" for j in state['jobs']]
    plots(root,attempts)
    state.update(phase='finished',heartbeat=time.time());save(root/'status.json',state)
    return 0

def monitor(root):
    path=root/'monitor_state.json';book=json.loads(path.read_text()) if path.exists() else dict(sent=[])
    while True:
        for p in sorted(root.glob('D_*/attempt_*/status.json')):
            try:s=json.loads(p.read_text())
            except json.JSONDecodeError:continue
            if s['status'] not in ['passed','failed']:continue
            key=f"{s['job']}:{s['attempt']}:{s['status']}"
            if key not in book['sent']:
                detail='all 12 cases passed parity/event/clock checks; 2,400 measured + 240 warm-ups' if s['status']=='passed' else s.get('error','inspect logs')
                message=f"{root.name}: benchmark {s['job']} attempt {s['attempt']} {s['status']}. {detail}. Results: {p.parent}"
                if notify(root,message):book['sent'].append(key);save(path,book)
        try:s=json.loads((root/'status.json').read_text())
        except (FileNotFoundError,json.JSONDecodeError):time.sleep(5);continue
        if s['phase']=='running' and time.time()-s['heartbeat']>120 and not Path('/proc/'+str(s['pid'])).exists():
            key='queue_stopped:'+str(s['pid'])
            if key not in book['sent'] and notify(root,f'{root.name}: benchmark queue terminated unexpectedly; inspecting before continuation.'):
                book['sent'].append(key);save(path,book)
        if s['phase']=='finished':
            keys=[f"{j['job']}:{j['attempt']}:{j['status']}" for j in s['jobs']]
            if all(k in book['sent'] for k in keys):return
        time.sleep(5)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['queue','worker','monitor']);p.add_argument('root',type=Path);p.add_argument('--job',choices=['D_I','D_N']);p.add_argument('--attempt',type=int)
    a=p.parse_args();root=a.root.resolve()
    if a.action=='worker':sys.exit(worker(root,a.job,a.attempt))
    elif a.action=='queue':sys.exit(queue(root))
    else:monitor(root)
