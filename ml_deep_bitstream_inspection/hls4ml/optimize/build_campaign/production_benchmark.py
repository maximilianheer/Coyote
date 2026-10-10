"""Production-DMA collection helpers for the R_SO_T five-event observer.

No board programming or automatic admission. The board supervisor must verify
the bitstream, 260-case parity gate and exclusive device lease before calling.
All allocation and per-input copies precede the timed production predict call.
"""
import hashlib
import json
import statistics
import time
import numpy as np
from board_benchmark import clock_model, percentile, save, sha, target, write_csv, EXACT
from parity_gate import check_logit, load_tolerances
from production_timestamps import ABI, MASK, read_snapshot


def clock_sample(session):
    before = time.monotonic_ns()
    tick = session.read_csr(1)
    after = time.monotonic_ns()
    return dict(host_before_ns=before, fpga_tick=tick, host_after_ns=after)


def collect_session(session, cases, tolerances, observations, calibration, *, trials=200, warmups=20, environment=None):
    """Collect into already-open JSONL files, preserving partial failed attempts."""
    if trials < 1 or warmups < 0:
        raise ValueError('invalid trial counts')
    if session.read_csr(0) != ABI:
        raise RuntimeError('R_SO_T observer required')
    previous_frame = session.read_csr(2)
    count = 0
    for case in cases:
        raw = np.fromfile(case['path'], dtype=np.uint8)
        if raw.size != case['bytes'] or hashlib.sha256(raw).hexdigest() != case['sha256']:
            raise ValueError('input identity changed')
        session.prepare(raw)
        print('CASE_START', case['id'], case['bytes'], flush=True)
        if environment is not None:
            from host_environment import record as record_environment
            record_environment(environment,case['id'],'before')
        for _ in range(32):
            calibration.write(json.dumps(dict(case_id=case['id'], position='before', **clock_sample(session)))+'\n')
        calibration.flush()
        for trial in range(warmups+trials):
            result = session.run()  # Original LOCAL_TRANSFER + blocking result DMA.
            row = dict(case_id=case['id'], sweep=case['sweep'], variant='R_SO_T',
                       input_sha256=case['sha256'], trial=trial, warmup=int(trial<warmups), **result)
            try:
                row['monitor'] = read_snapshot(session.read_csr, case['bytes'], previous_frame)
                check_logit(result['logit_bits'], result['verdict'], case, tolerances[case['sha256']])
                row['validation'] = 'passed'
            except Exception as error:
                row.update(validation='failed', error=str(error))
                observations.write(json.dumps(row)+'\n'); observations.flush()
                raise
            observations.write(json.dumps(row)+'\n'); observations.flush()
            previous_frame = row['monitor']['frame_id']
            count += 1
        for _ in range(32):
            calibration.write(json.dumps(dict(case_id=case['id'], position='after', **clock_sample(session)))+'\n')
        calibration.flush()
        if environment is not None:record_environment(environment,case['id'],'after')
        print('CASE_DONE', case['id'], flush=True)
    return count


def components(row, case, mapped, tick_ns, tolerance):
    """Derive only intervals supported by the five captured FPGA events."""
    if (row['variant'] != 'R_SO_T' or row['validation'] != 'passed' or
        row['case_id'] != case['id'] or row['sweep'] != case['sweep'] or
        row['input_sha256'] != case['sha256'] or row['raw_bytes'] != case['bytes'] or
        row['transport_bytes'] != 64+case['bytes']):
        raise ValueError('production trial identity/status mismatch')
    registers = {int(k): int(v) for k, v in row['monitor']['registers'].items()}
    monitor = read_snapshot(registers.__getitem__, case['bytes'])
    if monitor['frame_id'] != row['monitor']['frame_id']:
        raise ValueError('inconsistent captured frame identity')
    check_logit(row['logit_bits'], row['verdict'], case, tolerance)
    host = [int(row[k]) for k in ('host_start_ns', 'submit_start_ns', 'predict_return_ns', 'host_verdict_seen_ns')]
    if host != sorted(host):
        raise ValueError('invalid production host timestamp ordering')
    stamps = monitor['timestamp_ticks']
    lo, hi = mapped(stamps['verdict'])
    ingress_lo, ingress_hi = mapped(stamps['in'])
    if hi < host[0] or lo > host[-1] or ingress_hi < host[0] or ingress_lo > host[-1]:
        raise ValueError('FPGA event outside observed host interval')
    result = dict(case_id=case['id'], sweep=case['sweep'], variant='R_SO_T',
        input_bytes=case['bytes'], trial=int(row['trial']), warmup=int(row['warmup']),
        frame_id=monitor['frame_id'], total_lower_ms=(lo-host[0])/1e6,
        total_upper_ms=(hi-host[0])/1e6, total_ms=((lo+hi)/2-host[0])/1e6,
        clock_uncertainty_ms=(hi-lo)/1e6, host_observed_ms=(host[-1]-host[0])/1e6,
        pre_submit_ms=(host[1]-host[0])/1e6,
        production_predict_ms=(host[2]-host[1])/1e6,
        host_to_ingress_lower_ms=(ingress_lo-host[0])/1e6,
        host_to_ingress_upper_ms=(ingress_hi-host[0])/1e6)
    result.update({name+'_ms': value*tick_ns/1e6 for name, value in monitor['interval_ticks'].items()})
    # No last-input-byte event: do not label predict duration as transfer time.
    cnn_offset = (stamps['cnn_first']-stamps['in']) & MASK
    result['overlap_ms'] = max(0, monitor['interval_ticks']['preprocessing_elapsed']-cnn_offset)*tick_ns/1e6
    return result


def analyze(root, attempt, mode='full'):
    if mode not in ('full', 'pilot', 'smoke'):
        raise ValueError('unknown production analysis mode')
    manifest = json.loads((root/'inputs.json').read_text())
    cases = manifest['smoke' if mode=='smoke' else 'cases']
    if mode == 'pilot':
        cases = [c for c in cases if c['bytes'] in (min(EXACT), max(EXACT))]
    trials, warmups = dict(full=(200,20), pilot=(10,2), smoke=(2,0))[mode]
    rows = [json.loads(line) for line in (attempt/f'{mode}.jsonl').read_text().splitlines()]
    calibration = [json.loads(line) for line in (attempt/f'{mode}.clock.jsonl').read_text().splitlines()]
    expected_cases = {c['id'] for c in cases}
    if not expected_cases or {r['case_id'] for r in rows} != expected_cases or {r['case_id'] for r in calibration} != expected_cases:
        raise ValueError('incomplete/extra case grid')
    frames = [int(r['monitor']['frame_id']) for r in rows]
    if any(b != (a+1) & MASK for a,b in zip(frames,frames[1:])):
        raise ValueError('nonconsecutive production frames')
    tolerances = load_tolerances(root/'production_tolerances.json')
    derived, summary, clocks = [], [], {}
    for case in cases:
        if sha(case['path']) != case['sha256']:
            raise ValueError('input hash mismatch')
        block = [r for r in rows if r['case_id']==case['id']]
        if len(block) != trials+warmups or [r['trial'] for r in block] != list(range(trials+warmups)):
            raise ValueError('missing/duplicate/out-of-order trials')
        if any(r['warmup'] != int(r['trial']<warmups) for r in block):
            raise ValueError('incorrect warmup labels')
        mapped, details = clock_model([r for r in calibration if r['case_id']==case['id']])
        clocks[case['id']] = details
        tick_ns = (details['ns_per_tick_min']+details['ns_per_tick_max'])/2
        values = [components(r,case,mapped,tick_ns,tolerances[case['sha256']]) for r in block]
        derived.extend(values)
        ceiling = target(case['bytes']) if case['bytes']>=65536 else None
        uncertainty = max(r['clock_uncertainty_ms'] for r in values)
        if mode!='smoke' and (ceiling is None or uncertainty>ceiling*.01):
            raise ValueError('clock uncertainty exceeds 1% target')
        measured = [r for r in values if not r['warmup']]
        latencies = [r['total_ms'] for r in measured]
        item = dict(case_id=case['id'],sweep=case['sweep'],variant='R_SO_T',input_bytes=case['bytes'],
                    measured=trials,warmups=warmups,median_ms=statistics.median(latencies),
                    p95_ms=percentile(latencies,.95),max_ms=max(latencies),
                    first_call_ms=values[0]['total_ms'],
                    all_calls_median_ms=statistics.median(r['total_ms'] for r in values),
                    all_calls_p95_ms=percentile([r['total_ms'] for r in values],.95),
                    clock_uncertainty_ms=uncertainty,target_ms=ceiling)
        if mode=='full':
            item['p95_upper95_ms'] = sorted(r['total_upper_ms'] for r in measured)[195]
            item['meets_pdf_target'] = item['p95_upper95_ms']<=ceiling
        for key in measured[0]:
            if key.endswith('_ms'):
                item['median_'+key] = statistics.median(r[key] for r in measured)
        summary.append(item)
    write_csv(attempt/f'{mode}.derived.csv',derived)
    write_csv(attempt/f'{mode}.summary.csv',summary)
    result = dict(status='passed',variant='R_SO_T',mode=mode,trials=len(rows),cases=len(cases),
        summary=summary,clock_models=clocks,
        measurement='host before production flush/submission to first FPGA output-valid; result read via production DMA',
        interval_scope='preprocessing includes header; CNN includes input stalls and output conversion; overlapping intervals',
        transfer_scope='exact raw bytes plus 64-byte header; 4-byte result; last-input-byte timestamp unavailable',
        statistics='per-case, one session; measured-only, all calls, first call; no independent cold-start claim',
        gpu_comparison='PDF reference only; final payload 64 bytes below 128 MiB',
        tolerances_sha256=sha(root/'production_tolerances.json'))
    metadata=attempt/f'{mode}.meta.json'
    if mode=='full' and metadata.exists():
        collection=json.loads(metadata.read_text())
        if collection.get('status')!='passed':raise ValueError('Incomplete candidate collection')
        from resource_attribution import installed_resources
        resources=installed_resources(root/'installed_image.json',collection['hardware_identity'])
        save(attempt/'full.resources.json',resources)
        result['routed_resources']='full.resources.json'
    save(attempt/f'{mode}.analysis.json',result)
    return result


if __name__=='__main__':
    import argparse
    from pathlib import Path
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('board',type=Path);parser.add_argument('attempt',type=Path)
    parser.add_argument('--mode',choices=['smoke','pilot','full'],default='full')
    args=parser.parse_args()
    result=analyze(args.board.resolve(),args.attempt.resolve(),args.mode)
    print('PASS production benchmark analysis',args.mode,result['trials'])
