#!/usr/bin/env python3
"""Bounded parity check of a persistent production context on installed R_O/R_S.

No programming, benchmark-gate changes, or notifications. The build monitor
owns hardware-outcome notifications. Run under tmux on the board host.
"""
import argparse
import fcntl
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

from board_benchmark import REPO, save, sha
from isolation_board import verified_bitstream

HERE = Path(__file__).resolve().parent


def run(campaign, board, job, output, wait_for_validation=None):
    output.mkdir(parents=True, exist_ok=False)
    state = dict(status='running', stage='verify', pid=os.getpid(),
                 started_at=time.time(), diagnostic=True, benchmark_gate_unchanged=True)
    def record(**values):
        state.update(values)
        save(output/'status.json', state)
    record()
    try:
        if subprocess.check_output(['hostname'], text=True).strip() != 'hacc-u55c-03.inf.ethz.ch':
            raise RuntimeError('Wrong board host')
        while wait_for_validation is not None:
            if wait_for_validation.exists():
                validation=json.loads(wait_for_validation.read_text())
                if validation.get('job')!=job:
                    raise RuntimeError('Wrong prerequisite board validation')
                if validation.get('status')=='passed':break
                if validation.get('status')=='failed':
                    raise RuntimeError('Prerequisite board parity failed; do not run persistent test')
            progress=campaign/'jobs'/job/'progress.json'
            if progress.exists() and json.loads(progress.read_text()).get('status')=='failed':
                raise RuntimeError('Prerequisite hardware build failed')
            record(stage='waiting_board_validation',heartbeat=time.time(),
                   prerequisite=str(wait_for_validation))
            time.sleep(15)
        bit, digest = verified_bitstream(campaign/'jobs'/job)
        project = campaign/'jobs'/job/'runtime_project'
        cases = board/'diagnostics/runtime_cases.tsv'
        tolerances = board/'production_tolerances.json'
        sources = output/'sources'; sources.mkdir()
        paths = [Path(__file__), HERE/'production_control.py',
                 REPO/'hls4ml/pipeline/coyote_accelerator/raw_overlay.py',
                 REPO/'hls4ml/pipeline/coyote_accelerator/production_session.py']
        for path in paths: shutil.copy2(path, sources/path.name)
        save(output/'source_manifest.json', {str(p):sha(p) for p in paths})
        record(bitstream_sha256=sha(bit), source_manifest_sha256=digest,
               cases_sha256=sha(cases), tolerances_sha256=sha(tolerances))
        with (board/'board_device.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX|fcntl.LOCK_NB)
            installed=json.loads((board/'installed_image.json').read_text())
            if installed['job']!=job or installed['sha256']!=sha(bit):
                raise RuntimeError('Installed image changed; no inference attempted')
            devices=list(Path('/dev').glob('coyote*'))
            if not devices or subprocess.run(['fuser',*map(str,devices)],capture_output=True).returncode!=1:
                raise RuntimeError('Board ownership check failed')
            args=[str(REPO/'ml_baseline/.venv_hls4ml/bin/python'),str(HERE/'production_control.py'),
                  str(cases),str(output),'--project',str(project),
                  '--acceptance-tolerances',str(tolerances),'--persistent']
            env=dict(os.environ,OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',COYOTE_ALLOC_TYPE='HPF')
            with (output/'parity.log').open('w') as log:
                proc=subprocess.Popen(['numactl','--physcpubind=2','--membind=0',*args],
                    cwd=REPO,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
                record(stage='parity',child_pid=proc.pid)
                try:
                    deadline=time.monotonic()+300
                    while proc.poll() is None:
                        record(heartbeat=time.time())
                        if time.monotonic()>deadline:raise TimeoutError('Production parity exceeded 300 seconds')
                        time.sleep(1)
                except BaseException:
                    os.killpg(proc.pid,signal.SIGTERM)
                    try:proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGKILL);proc.wait()
                    raise
                if proc.returncode:raise RuntimeError(f'Parity exited {proc.returncode}')
            result=json.loads((output/'isolation_validation.json').read_text())
            if (result['status']!='passed' or result['failures'] or len(result['inputs'])!=26 or
                any(v['repetitions']!=10 for v in result['inputs'].values()) or
                result['bitstream_sha256']!=state['bitstream_sha256'] or
                result['cases_sha256']!=state['cases_sha256'] or
                result['acceptance_tolerances_sha256']!=state['tolerances_sha256'] or
                result['runtime_lifecycle']!='one persistent production context'):
                raise RuntimeError('Incomplete or mismatched persistent parity evidence')
            record(status='passed',stage='complete',calls=260,
                   max_abs_error=max(v['max_abs_error'] for v in result['inputs'].values()))
    except Exception as error:
        record(status='failed',error=str(error)); print(str(error),flush=True)
    record(finished_at=time.time())
    return int(state['status']!='passed')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('campaign',type=Path);p.add_argument('board',type=Path)
    p.add_argument('job',choices=['R_O','R_S']);p.add_argument('output',type=Path)
    p.add_argument('--wait-for-validation',type=Path)
    a=p.parse_args();sys.exit(run(a.campaign.resolve(),a.board.resolve(),a.job,a.output.resolve(),
        a.wait_for_validation.resolve() if a.wait_for_validation else None))
