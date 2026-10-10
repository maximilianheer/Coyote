#!/usr/bin/env python3
"""Same-input control using the frozen production library and RawCoyoteOverlay."""
import argparse
import csv
import ctypes
from contextlib import ExitStack
import json
from pathlib import Path
import sys
import numpy as np

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parents[1]))
from pipeline.coyote_accelerator.raw_overlay import RawCoyoteOverlay
from runtime_benchmark import read_cases
from parity_gate import as_float, check_logit, load_tolerances
from board_benchmark import save,sha
from production_timestamps import ABI as PASSIVE_ABI, read_snapshot

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('cases',type=Path);p.add_argument('output',type=Path)
    p.add_argument('--acceptance-tolerances',type=Path,
        help='Validate an isolation build against frozen production errors; do not derive new acceptance limits')
    p.add_argument('--persistent',action='store_true',
        help='Reuse one production context across all cases; diagnostic host timing only')
    p.add_argument('--passive-monitor',action='store_true',
        help='Also require valid R_SO_T captures after every production result DMA; requires --persistent')
    p.add_argument('--project',type=Path,required=True);a=p.parse_args()
    if a.passive_monitor and not a.persistent:p.error('--passive-monitor requires --persistent')
    tolerances=load_tolerances(a.acceptance_tolerances) if a.acceptance_tolerances else None
    build=a.project/'build/prod_res256_manualA_coyote_accel_cyt_sw'
    ctypes.CDLL(str(build/'libCoyote.so'),mode=ctypes.RTLD_GLOBAL)
    overlay=RawCoyoteOverlay(a.project,'prod_res256_manualA_coyote_accel')
    entries={};failures=[]
    cases=read_cases(a.cases)
    with ExitStack() as stack, (a.output/'production.csv').open('x') as f:
        session=stack.enter_context(overlay.open_production_session(max(c['bytes'] for c in cases))) if a.persistent else None
        timing=stack.enter_context((a.output/'host_observed.jsonl').open('x')) if session else None
        previous_frame=None;captured_frames=0
        if a.passive_monitor:
            if session.read_csr(0)!=PASSIVE_ABI:raise RuntimeError('R_SO_T passive timestamp ABI mismatch')
            previous_frame=session.read_csr(2)
        writer=csv.writer(f);writer.writerow(['case_id','sha256','trial','expected_logit_hex','logit_hex','logit','verdict','abs_error'])
        for c in cases:
            raw=np.fromfile(c['path'],dtype=np.uint8)
            # Exactly the production allocation/set_raw_data/flush/predict/readback lifecycle.
            print('PRODUCTION_START',c['id'],flush=True)
            if session:
                session.prepare(raw)
                predicted=[]
                for trial in range(10):
                    observation=session.run()
                    if a.passive_monitor:
                        try:
                            observation['monitor']=read_snapshot(session.read_csr,c['bytes'],previous_frame)
                        except Exception as error:
                            observation['monitor_error']=str(error)
                            timing.write(json.dumps(dict(case_id=c['id'],trial=trial,**observation))+'\n');timing.flush()
                            raise
                        previous_frame=observation['monitor']['frame_id'];captured_frames+=1
                    timing.write(json.dumps(dict(case_id=c['id'],trial=trial,**observation))+'\n');timing.flush()
                    predicted.append(observation['logit'])
            else:
                predicted=overlay.predict_raw([raw]*10,(1,),batch_size=1).reshape(-1)
            reference=as_float(int(c['expected_logit_hex'],16));errors=[]
            for i,value in enumerate(predicted):
                value=float(value);bits=int(np.float32(value).view(np.uint32));verdict=int(value>=0)
                error=abs(value-reference);errors.append(error)
                writer.writerow([c['id'],c['sha256'],i,c['expected_logit_hex'],f'{bits:08x}',value,verdict,error]);f.flush()
                if tolerances is not None:
                    try:check_logit(bits,verdict,c,tolerances[c['sha256']])
                    except (ValueError,KeyError) as error:
                        failures.append(dict(case_id=c['id'],trial=i,logit=value,expected=reference,error=str(error)))
                elif not np.isfinite(value) or verdict!=int(reference>=0):
                    failures.append(dict(case_id=c['id'],trial=i,logit=value,expected=reference))
            entries[c['sha256']]=dict(sha256=c['sha256'],bytes=c['bytes'],expected_logit_hex=c['expected_logit_hex'],
                production_verdict=int(reference>=0),repetitions=10,max_abs_error=max(errors),
                production_min=float(min(predicted)),production_max=float(max(predicted)))
            print('PRODUCTION_DONE',c['id'],'max_error',max(errors),flush=True)
    result=dict(status='failed' if failures else 'passed',policy='per-input production maximum absolute error; 10 repeats',
        inputs=entries,failures=failures,cases_sha256=sha(a.cases),library_sha256=sha(build/'lib/libCoyoteInference.so'),
        coyote_library_sha256=sha(build/'libCoyote.so'),
        bitstream_sha256=sha(a.project/'build/prod_res256_manualA_coyote_accel_cyt_hw/bitstreams/cyt_top.bit'))
    result['runtime_lifecycle']='one persistent production context' if a.persistent else 'production predict_raw per case'
    if a.passive_monitor:
        result['passive_timestamps']=dict(status='passed',frames=captured_frames,abi=PASSIVE_ABI,
            scope='five FPGA events, exact counts/order, consecutive capture IDs; no host-clock alignment claim')
    if tolerances is not None:
        result.update(policy='isolation validation against frozen production tolerances',
            acceptance_tolerances_sha256=sha(a.acceptance_tolerances))
        save(a.output/'isolation_validation.json',result)
    else:
        save(a.output/'production_tolerances.json',result)
    print('PRODUCTION_CONTROL',result['status'],len(entries),'inputs',len(failures),'failures',flush=True)
    sys.exit(bool(failures))
