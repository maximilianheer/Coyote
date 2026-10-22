#!/usr/bin/env python3
"""R_O/R_S production-runtime timing, without claiming internal FPGA events."""
import argparse
import ctypes
import json
from pathlib import Path
import statistics
import sys
import numpy as np
from board_benchmark import REPO, percentile, save, sha, write_csv
from host_environment import record
from parity_gate import check_logit, load_tolerances
from runtime_benchmark import read_cases
sys.path.insert(0,str(REPO/'hls4ml'))
from pipeline.coyote_accelerator.raw_overlay import RawCoyoteOverlay


def collect(board, job, project, output, mode):
    trials,warmups={'gate':(10,0),'smoke':(2,0),'pilot':(10,2),'full':(200,20)}[mode]
    cases=read_cases(board/('diagnostics/runtime_cases.tsv' if mode=='gate' else 'cases.tsv' if mode=='full' else mode+'.tsv'))
    image=json.loads((board/'installed_image.json').read_text())
    if image['job']!=job or image.get('reset_diagnostic') or image['sha256']!=sha(image['bitstream']) or image['driver_sha256']!=sha(image['driver']):
        raise RuntimeError('Installed image/driver mismatch')
    sw=project/'build/prod_res256_manualA_coyote_accel_cyt_sw'
    ctypes.CDLL(str(sw/'libCoyote.so'),mode=ctypes.RTLD_GLOBAL)
    overlay=RawCoyoteOverlay(project,'prod_res256_manualA_coyote_accel')
    tolerances=load_tolerances(board/'production_tolerances.json')
    rows=[];summary=[]
    with (output/(mode+'.jsonl')).open('x') as rawout,(output/(mode+'.environment.jsonl')).open('x') as env:
        with overlay.open_production_session(max(c['bytes'] for c in cases)) as session:
            for case in cases:
                session.prepare(np.fromfile(case['path'],dtype=np.uint8))
                record(env,case['id'],'before');block=[]
                print('CASE_START',case['id'],flush=True)
                for trial in range(trials+warmups):
                    result=session.run()
                    row=dict(case_id=case['id'],sweep=case['sweep'],variant=job,input_sha256=case['sha256'],trial=trial,warmup=int(trial<warmups),**result)
                    try:
                        check_logit(result['logit_bits'],result['verdict'],case,tolerances[case['sha256']])
                        times=[result[k] for k in ['host_start_ns','submit_start_ns','predict_return_ns','host_verdict_seen_ns']]
                        if times!=sorted(times):raise ValueError('Host timestamp order')
                        row.update(validation='passed',host_observed_ms=(times[3]-times[0])/1e6,pre_submit_ms=(times[1]-times[0])/1e6,production_predict_ms=(times[2]-times[1])/1e6,result_read_ms=(times[3]-times[2])/1e6)
                    except Exception as e:
                        row.update(validation='failed',error=str(e));rawout.write(json.dumps(row)+'\n');rawout.flush();raise
                    rawout.write(json.dumps(row)+'\n');rawout.flush();rows.append(row);block.append(row)
                record(env,case['id'],'after')
                xs=[r['host_observed_ms'] for r in block if not r['warmup']]
                item=dict(case_id=case['id'],sweep=case['sweep'],variant=job,input_bytes=case['bytes'],measured=trials,warmups=warmups,median_ms=statistics.median(xs),p95_ms=percentile(xs,.95),max_ms=max(xs),first_call_ms=block[0]['host_observed_ms'],all_calls_median_ms=statistics.median(r['host_observed_ms'] for r in block),all_calls_p95_ms=percentile([r['host_observed_ms'] for r in block],.95))
                if mode=='full':item['p95_upper95_ms']=sorted(xs)[195]
                for key in ['pre_submit_ms','production_predict_ms','result_read_ms']:item['median_'+key]=statistics.median(r[key] for r in block if not r['warmup'])
                summary.append(item);print('CASE_DONE',case['id'],flush=True)
    if json.loads((board/'installed_image.json').read_text())!=image:raise RuntimeError('Image changed during collection')
    write_csv(output/(mode+'.summary.csv'),summary)
    save(output/(mode+'.analysis.json'),dict(status='passed',job=job,mode=mode,trials=len(rows),cases=len(cases),summary=summary,measurement='host before production flush to host result observation after blocking LOCAL_TRANSFER and result DMA; Python/ctypes boundaries',internal_fpga_events='unavailable in R_O/R_S',hardware_identity=image,library_sha256=sha(sw/'lib/libCoyoteInference.so'),coyote_library_sha256=sha(sw/'libCoyote.so'),tolerances_sha256=sha(board/'production_tolerances.json'),collector_sha256=sha(__file__)))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('board',type=Path);p.add_argument('job',choices=['R_O','R_S']);p.add_argument('project',type=Path);p.add_argument('output',type=Path);p.add_argument('mode',choices=['gate','smoke','pilot','full']);a=p.parse_args()
    collect(a.board.resolve(),a.job,a.project.resolve(),a.output.resolve(),a.mode)
