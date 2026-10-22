"""Offline timing derivation. No hardware access and no changes to source evidence."""
import csv
import json
from functools import lru_cache
from pathlib import Path


@lru_cache(None)
def calibration_blocks(evidence):
    base = Path(evidence).parent
    if (base / 'calibration.jsonl').exists():
        return [json.loads(line) for line in (base / 'calibration.jsonl').open()]
    groups = {}
    for row in csv.DictReader((base / 'clock.csv').open()):
        key = (row['case_id'], row['scope'], row['session'], row['block'])
        groups.setdefault(key, []).append(row)
    return groups


@lru_cache(None)
def calibrated_model(evidence, case, scope, session, block, trial, gpu):
    from board_benchmark import clock_model
    blocks = calibration_blocks(evidence)
    if gpu:
        matches = [b for b in blocks if b['case_id'] == case and b['scope'] == scope
                   and b['first_trial'] <= trial <= b['last_trial']]
        assert len(matches) == 1, ('ambiguous calibration', case, trial)
        samples = matches[0]['samples']
    else:
        samples = blocks[case, scope, session, block]
    return clock_model(samples)


def model_for(evidence, row, gpu):
    # GPU models are cached per existing 20-trial block, not per individual call.
    trial = int(row['trial'])
    if gpu:
        matches = [b for b in calibration_blocks(evidence)
                   if b['case_id'] == row['case_id'] and b['scope'] == row['scope']
                   and b['first_trial'] <= trial <= b['last_trial']]
        assert len(matches) == 1
        trial = matches[0]['first_trial']
    return calibrated_model(evidence, row['case_id'], row['scope'],
                            row['session'], str(row.get('block', '')), trial if gpu else 0, gpu)


def derive(row, mapped, details, iteration):
    """CSR14 is score acceptance, CSR9 is last payload, CSR15 is final done."""
    gpu = int(row['variant']) in (10, 11)
    variant = int(row['variant'])
    assert variant in (7, 10, 11)
    ticks = {k: int(row[f'csr_{k}']) for k in [6, 7, 8, 9, 14, 15, 20]}
    status = int(row['csr_0'] if gpu else row['status'])
    signature = int(row['csr_4'] if gpu else row['signature'])
    assert status == 2 and signature == ((0x4342595400040000 if gpu else 0x4342595400030000) | variant)
    needed = 0xc3  # input first/last, accepted result, and final done
    assert ticks[7] & needed == needed, 'missing required event'
    n = int(row['input_bytes']); frame = 64 + ((n + 63) // 64) * 64
    assert n > 0 and int(row['transport_bytes']) == frame and ticks[20] == frame // 64
    assert ticks[6] <= ticks[8] <= ticks[9] <= ticks[15]
    assert ticks[6] <= ticks[14] <= ticks[15]
    if variant == 7:
        assert ticks[14] == ticks[15] and ticks[9] <= ticks[14]
    if variant == 11:
        assert int(row['csr_21']) == ticks[20]
        assert ticks[6] <= int(row['csr_18']) <= int(row['csr_19']) <= ticks[15]
        assert int(row['csr_19']) <= int(row['csr_38']) <= int(row['csr_40']) <= int(row['csr_41']) <= ticks[14]
        assert int(row['csr_45']) == 0, 'P2P polling error'
    h = int(row['host_start_ns'])
    seen = int(row['verdict_seen_ns'] if gpu else row['host_verdict_seen_ns'])
    assert seen >= h
    out = dict(iteration=iteration, case_id=row['case_id'], scope=row['scope'],
               session=row['session'], block=str(row.get('block', '')), trial=int(row['trial']),
               input_bytes=n, input_sha256=row['input_sha256'],
               host_observed_ms=(seen-h)/1e6,
               ns_per_tick_lower=details['ns_per_tick_min'], ns_per_tick_upper=details['ns_per_tick_max'])
    for label, key in [('arm', 6), ('input_first', 8), ('input_complete', 9),
                       ('verdict_available', 14), ('fpga_complete', 15)]:
        lo, hi = mapped(ticks[key])
        assert hi >= h and lo <= seen, ('event outside host brackets', label, row['trial'])
        out[label + '_lower_ms'] = (lo-h)/1e6
        out[label + '_upper_ms'] = (hi-h)/1e6
        out[label + '_ms'] = ((lo+hi)/2-h)/1e6
    tick = (details['ns_per_tick_min'] + details['ns_per_tick_max'])/2
    deltas = {
        'reception': ticks[9]-ticks[8],
        'remaining_input_after_result': max(0, ticks[9]-ticks[14]),
        'result_to_fpga_complete': ticks[15]-ticks[14],
        'after_input_and_result': ticks[15]-max(ticks[9], ticks[14]),
        'arm_to_verdict_available': ticks[14]-ticks[6],
    }
    for label, delta in deltas.items():
        assert delta >= 0
        out[label+'_ms'] = delta*tick/1e6
        out[label+'_lower_ms'] = delta*details['ns_per_tick_min']/1e6
        out[label+'_upper_ms'] = delta*details['ns_per_tick_max']/1e6
    assert abs(out['remaining_input_after_result_ms']+out['after_input_and_result_ms']-out['result_to_fpga_complete_ms']) < 1e-9
    # Preserve calibration uncertainty; do not silently clamp an uncertain estimate.
    out['host_observation_delay_ms'] = out['host_observed_ms']-out['fpga_complete_ms']
    out['host_observation_delay_lower_ms'] = out['host_observed_ms']-out['fpga_complete_upper_ms']
    out['host_observation_delay_upper_ms'] = out['host_observed_ms']-out['fpga_complete_lower_ms']
    out['result_before_input_complete'] = ticks[14] < ticks[9]
    out['max_alignment_half_width_ms'] = max((out[k+'_upper_ms']-out[k+'_lower_ms'])/2
        for k in ['input_first', 'input_complete', 'verdict_available', 'fpga_complete'])
    return out


def phase_partition(row, availability_ms):
    """Consecutive host intervals clipped at the FPGA result-acceptance endpoint."""
    h = int(row['host_start_ns'])
    if int(row['variant']) == 7:
        keys = ['host_start_ns', 'submit_start_ns', 'submit_return_ns']
        t = [(int(row[k])-h)/1e6 for k in keys]
        assert t == sorted(t)
        t = [min(x, availability_ms) for x in t]
        vals = [t[1]-t[0], t[2]-t[1], 0, 0, 0, availability_ms-t[2]]
    else:
        keys = ['host_start_ns', 'submit_ns', 'submitted_ns', 'input_ready_ns', 'relay_start_ns', 'relay_end_ns']
        t = [(int(row[k])-h)/1e6 for k in keys]
        assert t == sorted(t)
        t = [min(x, availability_ms) for x in t] + [availability_ms]
        vals = [b-a for a,b in zip(t,t[1:])]
    assert min(vals) >= -1e-12 and abs(sum(vals)-availability_ms) < 1e-9
    return vals
