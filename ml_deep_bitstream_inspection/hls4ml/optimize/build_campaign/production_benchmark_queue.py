#!/usr/bin/env python3
"""Admitted R_SO_T benchmark queue; preserve attempts and restore the D_N sink."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from benchmark_identity import installed_identity
from benchmark_queue import notify
from board_benchmark import REPO, save, sha
from isolation_evidence import verified_board_parity
from prepare_production_runtime import prepare
from worker import verify_sources, validate_timing_report

HERE=Path(__file__).resolve().parent


def verified_sink(job):
    manifest=json.loads((job/'artifact_manifest.json').read_text())
    if job.name!='D_N' or manifest.get('status')!='passed' or manifest['source_manifest_sha256']!=verify_sources(job):
        raise RuntimeError('Sink source/artifact gate failed')
    bits=[];reports=[]
    for name,record in manifest['files'].items():
        path=(job/name).resolve()
        if not path.is_relative_to(job) or path.stat().st_size!=record['bytes'] or sha(path)!=record['sha256']:
            raise RuntimeError('Sink artifact changed')
        if path.name=='cyt_top.bit':bits.append(path)
        if path.name=='shell_timing_summary.rpt':reports.append(path)
    if len(bits)!=1 or not reports:raise RuntimeError('Missing sink image/timing')
    for path in reports:validate_timing_report(path)
    return bits[0],manifest['source_manifest_sha256']


def worker(board, job, admission, sink, attempt):
    attempt.mkdir(parents=True,exist_ok=False)
    state=dict(status='running',stage='admission',job='R_SO_T',pid=os.getpid(),started_at=time.time())
    path=attempt/'status.json';save(path,state)
    env=dict(os.environ,OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1')
    env['PATH']='/tools/Xilinx/Vivado/2024.2/bin:'+env.get('PATH','')
    def command(stage,args):
        state.update(stage=stage,stage_started_at=time.time(),heartbeat=time.time());save(path,state)
        with (attempt/(stage+'.log')).open('w') as log:
            child=subprocess.Popen(args,cwd=REPO,env=env,stdout=log,stderr=subprocess.STDOUT,preexec_fn=os.setpgrp)
            state['child_pid']=child.pid
            try:
                while child.poll() is None:
                    state['heartbeat']=time.time();save(path,state)
                    if time.time()-state['stage_started_at']>900:raise TimeoutError(stage+' exceeded 900 seconds')
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
    lock=None;changed=False;program_started=False
    try:
        if subprocess.check_output(['hostname'],text=True).strip()!='hacc-u55c-03.inf.ethz.ch':
            raise RuntimeError('Wrong board host')
        evidence=verified_board_parity(job,board,admission)
        save(attempt/'board_admission.json',evidence)
        from isolation_board import verified_bitstream
        bit,source_hash=verified_bitstream(job)
        sink_bit,sink_source=verified_sink(sink)
        project=prepare(job,bit)
        driver=board/'software/driver/build/coyote_driver.ko'
        if sha(driver)!=json.loads((admission/'status.json').read_text())['driver_sha256']:
            raise RuntimeError('Standard driver changed after board validation')
        kernel=subprocess.check_output(['uname','-r'],text=True).strip()
        if not subprocess.check_output(['modinfo','-F','vermagic',str(driver)],text=True).startswith(kernel+' '):
            raise RuntimeError('Driver/kernel mismatch')
        lock=(board/'board_device.lock').open('a')
        state['stage']='waiting_board'
        while True:
            try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);break
            except BlockingIOError:
                if time.time()-state['started_at']>3600:raise TimeoutError('Board lease unavailable for one hour')
                state['heartbeat']=time.time();save(path,state);time.sleep(5)
        devices=list(Path('/dev').glob('coyote*'))
        if devices and subprocess.run(['fuser',*map(str,devices)],capture_output=True).returncode!=1:
            raise RuntimeError('Board in use or ownership check failed')
        def program(variant,bitstream,digest,stage):
            save(board/'installed_image.json',dict(status='programming',job=variant,started_at=time.time()))
            command(stage,['bash',str(REPO.parent/'util/program_hacc_local.sh'),str(bitstream),str(driver),'1'])
            pci=Path('/sys/bus/pci/devices/0000:c4:00.0')
            if (pci/'current_link_width').read_text().strip()!='16' or not (pci/'current_link_speed').read_text().startswith('8.0 GT/s'):
                raise RuntimeError('Unexpected PCIe speed/width')
            save(board/'installed_image.json',dict(status='ready',job=variant,bitstream=str(bitstream),sha256=sha(bitstream),
                source_manifest_sha256=digest,driver=str(driver),driver_sha256=sha(driver),
                installed_at=time.time(),diagnostic=False,reset_diagnostic=False))
        program_started=True
        program('R_SO_T',bit,source_hash,'program')
        changed=True
        hardware=installed_identity(board/'installed_image.json','R_SO_T')
        for mode,trials,warmups in [('smoke',2,0),('pilot',10,2),('full',200,20)]:
            command(mode,['numactl','--physcpubind=2','--membind=0',str(REPO/'ml_baseline/.venv_hls4ml/bin/python'),
                str(HERE/'production_collect.py'),str(board/('cases.tsv' if mode=='full' else mode+'.tsv')),
                str(attempt/(mode+'.jsonl')),str(attempt/(mode+'.clock.jsonl')),str(project),
                str(board/'installed_image.json'),str(board/'production_tolerances.json'),
                '--trials',str(trials),'--warmups',str(warmups)])
            metadata=json.loads((attempt/(mode+'.meta.json')).read_text())
            if metadata.get('status')!='passed' or metadata['hardware_identity']!=hardware:
                raise RuntimeError('Candidate collection identity/gate failed')
            # Analysis needs NumPy: execute it in the existing compatible environment.
            command(mode+'_analysis',[str(REPO/'ml_baseline/.venv_hls4ml/bin/python'),
                str(HERE/'production_benchmark.py'),str(board),str(attempt),'--mode',mode])
        state.update(measurements_passed=True,hardware_identity=hardware,
                     runner_sha256=sha(HERE/'production_collect.py'),analyzer_sha256=sha(HERE/'production_benchmark.py'))
        program('D_N',sink_bit,sink_source,'restore_sink')
        changed=False
        state.update(status='passed',stage='complete',sink_restored=True)
    except BaseException as error:
        state.update(status='failed',error=str(error));print(str(error),flush=True)
        # Do not reprogram automatically after an uncertain programming failure.
        # A failed collection has exited its whole supervised process group first.
        if changed and state.get('stage') not in ('program','restore_sink'):
            try:
                program('D_N',sink_bit,sink_source,'restore_sink_after_failure')
                state['sink_restored']=True
            except BaseException as restore_error:
                state['sink_restore_error']=str(restore_error)
        elif program_started:
            state['sink_restored']=False
    finally:
        if lock is not None:lock.close()
    state.update(finished_at=time.time(),heartbeat=time.time());save(path,state)
    return int(state['status']!='passed')


def priority_allows_candidate(priority, priority_admission):
    """Give a ready D_I priority; an unavailable checker cannot block fallback."""
    earlier=json.loads(priority.read_text()) if priority.exists() else {}
    if earlier.get('status') in ('passed','failed'):
        return True
    gate=json.loads(priority_admission.read_text()) if priority_admission.exists() else {}
    if gate.get('status') in ('failed','cancelled'):
        return True
    if gate.get('status')=='passed' or earlier.get('stage')=='benchmark_queue':
        return False
    # The board handoff publishes waiting_build only while hardware is unready.
    # Once it acquires a passed image it changes to waiting_board/program/parity.
    return (gate.get('status')=='running' and gate.get('stage')=='waiting_build'
            and gate.get('build_status') not in ('passed',None))


def queue(board,job,admission,sink,priority,priority_admission):
    root=board/'R_SO_T';root.mkdir(exist_ok=True)
    state=dict(status='running',stage='waiting_admission',pid=os.getpid(),started_at=time.time())
    path=root/'handoff.json'
    try:
        while True:
            gate=json.loads((admission/'status.json').read_text()) if (admission/'status.json').exists() else {}
            earlier=json.loads(priority.read_text()) if priority.exists() else {}
            if gate.get('status') in ('failed','cancelled'):raise RuntimeError('R_SO_T board gate failed')
            if gate.get('status')=='passed' and priority_allows_candidate(priority,priority_admission):break
            if time.time()-state['started_at']>172800:raise TimeoutError('Candidate benchmark handoff deadline')
            state.update(heartbeat=time.time(),admission=gate.get('stage'),priority=earlier.get('stage'))
            save(path,state);time.sleep(15)
        attempts=sorted(root.glob('attempt_*/status.json'))
        number=max([int(p.parent.name.removeprefix('attempt_')) for p in attempts],default=0)+1
        attempt=root/f'attempt_{number:02d}'
        state.update(stage='benchmark',attempt=str(attempt));save(path,state)
        result=worker(board,job,admission,sink,attempt)
        state.update(status='failed' if result else 'passed',stage='complete')
    except BaseException as error:
        state.update(status='failed',error=str(error));print(str(error),flush=True)
    state['finished_at']=time.time();save(path,state)
    return int(state['status']!='passed')


def monitor(board):
    root=board/'R_SO_T';root.mkdir(exist_ok=True)
    book_path=root/'notifications_state.json'
    book=json.loads(book_path.read_text()) if book_path.exists() else {'sent':[]}
    while True:
        pending=False
        for path in sorted(root.glob('attempt_*/status.json')):
            state=json.loads(path.read_text())
            if state['status']=='running' and not Path('/proc/'+str(state['pid'])).exists():
                state.update(status='failed',error='Benchmark process terminated unexpectedly',finished_at=time.time());save(path,state)
            if state['status'] not in ('passed','failed'):continue
            key=path.parent.name+':'+state['status']
            if key not in book['sent']:
                detail='2,400 measured + 240 warm-ups; clock/parity/capture checks passed; D_N restored' if state['status']=='passed' else state.get('error','inspect logs')
                if notify(board,f'R_SO_T benchmark {key}: {detail}. Results: {path.parent}'):
                    book['sent'].append(key);save(book_path,book)
                else:pending=True
        handoff=root/'handoff.json'
        if handoff.exists() and json.loads(handoff.read_text()).get('status') in ('passed','failed') and not pending:return
        time.sleep(5)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['queue','monitor']);parser.add_argument('board',type=Path)
    parser.add_argument('--job',type=Path);parser.add_argument('--admission',type=Path)
    parser.add_argument('--sink',type=Path);parser.add_argument('--priority',type=Path)
    parser.add_argument('--priority-admission',type=Path)
    args=parser.parse_args()
    if args.action=='monitor':monitor(args.board.resolve())
    else:
        if not all((args.job,args.admission,args.sink,args.priority,args.priority_admission)):
            parser.error('queue requires job, admission, sink, priority and priority-admission')
        raise SystemExit(queue(*(p.resolve() for p in (args.board,args.job,args.admission,args.sink,args.priority,args.priority_admission))))
