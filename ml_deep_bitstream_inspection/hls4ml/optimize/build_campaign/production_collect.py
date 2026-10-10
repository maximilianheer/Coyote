#!/usr/bin/env python3
"""Collect admitted R_SO_T timing through the production runtime/result DMA."""
import argparse
import ctypes
from pathlib import Path
import sys
import time

from benchmark_identity import installed_identity
from board_benchmark import sha, save
from parity_gate import load_tolerances
from production_benchmark import collect_session
from runtime_benchmark import read_cases

HERE=Path(__file__).resolve().parent


def collect(cases_file, output, clock_output, project, image, tolerances_file, trials, warmups):
    sys.path.insert(0,str(HERE.parents[1]))
    from pipeline.coyote_accelerator.raw_overlay import RawCoyoteOverlay
    hardware=installed_identity(image,'R_SO_T')
    build=project/'build/prod_res256_manualA_coyote_accel_cyt_sw'
    library=build/'lib/libCoyoteInference.so';coyote=build/'libCoyote.so'
    software=[HERE/name for name in ('production_collect.py','production_benchmark.py',
              'production_timestamps.py','benchmark_identity.py','parity_gate.py','host_environment.py')]
    software += [HERE.parents[1]/'pipeline/coyote_accelerator'/name
                 for name in ('production_session.py','raw_overlay.py')]
    identities={str(path.resolve()):sha(path) for path in [library,coyote,cases_file,tolerances_file,*software]}
    meta=dict(status='running',started_at=time.time(),hardware_identity=hardware,
              input_and_runtime_hashes=identities,trials=trials,warmups=warmups)
    sidecar=output.with_suffix('.meta.json');save(sidecar,meta)
    try:
        cases=read_cases(cases_file);tolerances=load_tolerances(tolerances_file)
        ctypes.CDLL(str(coyote),mode=ctypes.RTLD_GLOBAL)
        overlay=RawCoyoteOverlay(project,'prod_res256_manualA_coyote_accel')
        environment_file=output.with_suffix('.environment.jsonl')
        with output.open('x') as observations, clock_output.open('x') as calibration,environment_file.open('x') as environment:
            with overlay.open_production_session(max(case['bytes'] for case in cases)) as session:
                count=collect_session(session,cases,tolerances,observations,calibration,trials=trials,warmups=warmups,environment=environment)
        if hardware!=installed_identity(image,'R_SO_T') or any(sha(path)!=digest for path,digest in identities.items()):
            raise RuntimeError('Measurement hardware/runtime/input identity changed')
        meta.update(status='passed',calls=count,environment_snapshots=dict(path=str(environment_file),sha256=sha(environment_file),
                    scope='before/after each case, outside measured calls'))
    except BaseException as error:
        meta.update(status='failed',error=str(error));raise
    finally:
        meta['finished_at']=time.time();save(sidecar,meta)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('cases','output','clock_output','project','image','tolerances'):
        parser.add_argument(name,type=Path)
    parser.add_argument('--trials',type=int,default=200)
    parser.add_argument('--warmups',type=int,default=20)
    args=parser.parse_args()
    collect(*(getattr(args,name).resolve() for name in ('cases','output','clock_output','project','image','tolerances')),
            args.trials,args.warmups)
