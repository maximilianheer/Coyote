#!/usr/bin/env python3
"""Resume D_I then D_N benchmarks after exact-build runtime admission passes."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from benchmark_identity import selected_hardware
from board_benchmark import sha, save

HERE=Path(__file__).resolve().parent


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('board',type=Path)
    parser.add_argument('admission',type=Path)
    parser.add_argument('output',type=Path)
    args=parser.parse_args()
    board,admission,output=(p.resolve() for p in (args.board,args.admission,args.output))
    output.mkdir(parents=True,exist_ok=False)
    state=dict(status='running',stage='waiting_runtime_admission',pid=os.getpid(),started_at=time.time())
    try:
        while True:
            path=admission/'status.json'
            gate=json.loads(path.read_text()) if path.exists() else {'status':'pending'}
            if gate.get('status') in ('failed','cancelled'):
                raise RuntimeError('D_I board admission failed; no benchmark launch')
            if gate.get('status')=='passed':break
            if time.time()-state['started_at']>86400:
                raise TimeoutError('Runtime admission deadline; hardware builds left untouched')
            state.update(heartbeat=time.time(),admission_stage=gate.get('stage'))
            save(output/'status.json',state);time.sleep(15)
        if gate.get('board_calls')!=520 or gate.get('runtime_validation_sha256')!=sha(board/'runtime_validation.json'):
            raise RuntimeError('Runtime admission evidence changed or is incomplete')
        if (admission/'hardware_selection.json').read_bytes()!=(board/'hardware_selection.json').read_bytes():
            raise RuntimeError('Selected hardware differs from admitted hardware')
        for variant in ('D_I','D_N'):selected_hardware(board,variant)
        queue=json.loads((board/'status.json').read_text())
        if queue.get('phase')=='running':
            raise RuntimeError('Another benchmark queue is already running')
        state.update(stage='benchmark_queue',heartbeat=time.time(),
                     runtime_validation_sha256=sha(board/'runtime_validation.json'))
        save(output/'status.json',state)
        with (output/'queue.log').open('w') as log:
            child=subprocess.Popen([sys.executable,str(HERE/'benchmark_queue.py'),'queue',str(board)],
                                   stdout=log,stderr=subprocess.STDOUT)
            state['queue_pid']=child.pid
            while child.poll() is None:
                state['heartbeat']=time.time();save(output/'status.json',state);time.sleep(10)
            if child.returncode:raise RuntimeError('Benchmark queue failed; preserve attempts and diagnose')
        state.update(status='passed',stage='complete')
    except BaseException as error:
        state.update(status='failed',error=str(error));print(str(error),flush=True)
    state['finished_at']=time.time();save(output/'status.json',state)
    return int(state['status']!='passed')


if __name__=='__main__':raise SystemExit(main())
