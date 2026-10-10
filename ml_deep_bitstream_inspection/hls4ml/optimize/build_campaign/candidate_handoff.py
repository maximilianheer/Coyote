#!/usr/bin/env python3
"""Launch R_SO_T after both standard-driver board prerequisites pass."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from production_candidate import prerequisites
from worker import save

HERE=Path(__file__).resolve().parent


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('specification',type=Path)
    parser.add_argument('output',type=Path)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--cases',type=Path,required=True)
    parser.add_argument('--boundary-reference',type=Path,required=True)
    parser.add_argument('--implementation-lock',type=Path,required=True)
    args=parser.parse_args()
    output=args.output.resolve();output.mkdir(parents=True,exist_ok=False)
    specification=args.specification.resolve()
    original=specification.read_bytes();spec=json.loads(original)
    state=dict(status='running',stage='waiting_board_parity',pid=os.getpid(),
               started_at=time.time(),target=str(args.root.resolve()),hardware_started=False)
    try:
        while True:
            gates={}
            for variant in ('R_O','R_S'):
                path=Path(spec[variant]['evidence'])/'status.json'
                gates[variant]=json.loads(path.read_text()).get('status') if path.exists() else 'pending'
            if any(value in ('failed','cancelled') for value in gates.values()):
                raise RuntimeError('Board prerequisite failed; R_SO_T left unlaunched')
            if all(value=='passed' for value in gates.values()):break
            if time.time()-state['started_at']>86400:
                raise TimeoutError('Board prerequisite deadline; existing builds left untouched')
            state.update(heartbeat=time.time(),gates=gates);save(output/'status.json',state);time.sleep(15)
        if specification.read_bytes()!=original:
            raise RuntimeError('Candidate prerequisite specification changed while waiting')
        evidence=prerequisites({'production_prerequisites':spec})
        save(output/'verified_prerequisites.json',evidence)
        state.update(stage='launching',heartbeat=time.time());save(output/'status.json',state)
        with (output/'launch.log').open('w') as log:
            subprocess.run([sys.executable,str(HERE/'launch_isolation.py'),
                '--variants','R_SO_T','--production-prerequisites',str(specification),
                '--root',str(args.root.resolve()),'--cases',str(args.cases.resolve()),
                '--boundary-reference',str(args.boundary_reference.resolve()),
                '--implementation-lock',str(args.implementation_lock.resolve())],
                stdout=log,stderr=subprocess.STDOUT,check=True)
        state.update(status='passed',stage='launched')
    except BaseException as error:
        state.update(status='failed',error=str(error));print(str(error),flush=True)
    state['finished_at']=time.time();save(output/'status.json',state)
    return int(state['status']!='passed')


if __name__=='__main__':raise SystemExit(main())
