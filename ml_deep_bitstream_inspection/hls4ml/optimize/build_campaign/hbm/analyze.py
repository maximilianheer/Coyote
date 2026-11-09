#!/usr/bin/env python3
"""Derive calibrated ABI5 intervals without touching archived measurements."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from board_benchmark import clock_model


def read_rows(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def model(root, case):
    clocks = json.loads((root / f'{case}_clock.json').read_text())
    samples = [dict(position=position, host_before_ns=a, fpga_tick=t, host_after_ns=b)
               for position, triples in clocks.items() for a, t, b in triples]
    return clock_model(samples)


def analyze(campaign, destination):
    data = destination / 'data'
    data.mkdir(parents=True, exist_ok=True)
    evidence = []
    derived = []
    calibration = []
    for label, directory in [('FPGA_HLS4ML', 'opt10_main'), ('GPU_P2P', 'opt11_main_02'),
                             ('FPGA closing', 'opt10_closing'),
                             ('FPGA repeat', 'opt10_repeat_02'),
                             ('FPGA program 3', 'opt10_program_03'),
                             ('FPGA diagnostic', 'opt10_diagnostics'), ('GPU diagnostic', 'opt11_diagnostics')]:
        root = campaign / directory
        assert json.loads((root / 'status.json').read_text())['status'] == 'passed', root
        raw_path = root / 'trials.jsonl'
        evidence.append(dict(path=str(raw_path), sha256=hashlib.sha256(raw_path.read_bytes()).hexdigest()))
        models = {}
        for row in read_rows(raw_path):
            if row['warmup']:
                continue
            case = row['case_id']
            if case not in models:
                models[case] = model(root, case)
                calibration.append(dict(variant=label, case_id=case, **models[case][1]))
            mapped, details = models[case]
            tick_ns = (details['ns_per_tick_min'] + details['ns_per_tick_max']) / 2
            arm = row['csr_6']
            arm_lo, arm_hi = mapped(arm)
            arm_host = (arm_lo + arm_hi) / 2
            verdict_lo, verdict_hi = mapped(row['csr_24'])
            assert verdict_hi >= row['host_start_ns']
            assert verdict_lo <= row['host_verdict_seen_ns']
            out = dict(variant=label, case_id=case, bytes=row['bytes'], trial=row['trial'],
                       mode=row['mode'], source=str(raw_path), score=row['score'],
                       ns_per_tick=tick_ns,
                       verdict_ms=(row['csr_24'] - arm) * tick_ns / 1e6,
                       host_observed_ms=(row['host_verdict_seen_ns'] - row['host_start_ns']) / 1e6,
                       arm_alignment_half_width_ms=(arm_hi - arm_lo) / 2e6)
            out['workload_role'] = ('real' if case.startswith('real_') else
                                    'synthetic' if case.startswith('synthetic_') else 'diagnostic')
            valid = row['csr_7']
            for name, start, end in [('hbm_request', 16, 17), ('hbm_return', 18, 19),
                                     ('pixel', 20, 21), ('cnn', 22, 23), ('verdict', 24, 25),
                                     ('hbm_completion', 26, 27), ('gpu_forward', 28, 29),
                                     ('gpu_write_completion', 30, 31), ('poll_request', 32, 33)]:
                for key, register in [('start', start), ('end', end)]:
                    if valid & (1 << (register - 16)):
                        out[f'{name}_{key}_ms'] = (row[f'csr_{register}'] - arm) * tick_ns / 1e6
                    else:
                        out[f'{name}_{key}_ms'] = None
            if row['csr_4'] & 0xffff == 10:
                out['requested_hbm_bytes'] = row['csr_48'] * 64
                out['pcie_payload_bytes'] = 0
                out['pixel_count'] = row['csr_51']
            else:
                out['requested_hbm_bytes'] = row['bytes']
                out['pcie_payload_bytes'] = row['csr_48']
                out['poll_requests'] = row['csr_56']
                out['poll_bytes'] = row['csr_57']
                for key in ['gpu_input_ready_ns', 'gpu_framework_begin_ns', 'gpu_framework_end_ns', 'gpu_publication_complete_ns']:
                    if row.get(key) is not None:
                        out[key.replace('_ns', '_ms')] = (row[key] - arm_host) / 1e6
                out['framework_ms'] = (row['gpu_framework_end_ns'] - row['gpu_framework_begin_ns']) / 1e6
                out['poll_ready_ms'] = (row['csr_54'] - arm) * tick_ns / 1e6
                out['poll_payload_ms'] = (row['csr_55'] - arm) * tick_ns / 1e6
            for activity in ['hbm_return', 'gpu_forward']:
                a = out[activity + '_start_ms']
                b = out[activity + '_end_ms']
                size = out['requested_hbm_bytes'] if activity == 'hbm_return' else out['pcie_payload_bytes']
                out[activity + '_requested_GBps'] = size / ((b - a) * 1e6) if a is not None and b > a else None
            derived.append(out)
    statistics = []
    keys = dict.fromkeys((row['variant'], row['case_id']) for row in derived)
    for variant, case in keys:
        rows = [row for row in derived if row['variant'] == variant and row['case_id'] == case]
        metrics = {}
        for name in ['verdict_ms', 'framework_ms', 'hbm_return_requested_GBps', 'gpu_forward_requested_GBps', 'host_observed_ms']:
            values = [row[name] for row in rows if row.get(name) is not None]
            if values:
                metrics[name] = dict(median=float(np.median(values)), p05=float(np.percentile(values, 5)),
                                     p95=float(np.percentile(values, 95)), min=float(min(values)), max=float(max(values)))
        statistics.append(dict(variant=variant, case_id=case, bytes=rows[0]['bytes'], count=len(rows), metrics=metrics))
    drifts = []
    for closing in [row for row in statistics if row['variant'] == 'FPGA closing']:
        opening = next(row for row in statistics if row['variant'] == 'FPGA_HLS4ML' and row['case_id'] == closing['case_id'])
        drift = closing['metrics']['verdict_ms']['median'] / opening['metrics']['verdict_ms']['median'] - 1
        drifts.append(dict(case_id=closing['case_id'], fractional_drift=drift, passed=abs(drift) <= 0.05))
    repeat_drifts = []
    for closing in [row for row in statistics if row['variant'] == 'FPGA closing']:
        repeat = next(row for row in statistics if row['variant'] == 'FPGA repeat' and row['case_id'] == closing['case_id'])
        drift = repeat['metrics']['verdict_ms']['median'] / closing['metrics']['verdict_ms']['median'] - 1
        repeat_drifts.append(dict(case_id=closing['case_id'], fractional_drift=drift, passed=abs(drift) <= 0.05))
    assert all(row['passed'] for row in repeat_drifts), repeat_drifts
    for filename, value in [('trial_events.json', derived), ('statistics.json', statistics),
                            ('clock_models.json', calibration), ('opening_closing_drift.json', drifts),
                            ('within_program_drift.json', repeat_drifts),
                            ('evidence_manifest.json', evidence)]:
        (data / filename).write_text(json.dumps(value, indent=2) + '\n')
    keys = sorted(set().union(*(row.keys() for row in derived)))
    with (data / 'trial_events.csv').open('w') as output:
        writer = csv.DictWriter(output, fieldnames=keys)
        writer.writeheader()
        writer.writerows(derived)
    print(json.dumps(dict(status='passed_with_cross_program_variation', measured_rows=len(derived),
                          maximum_cross_program_drift=max(abs(row['fractional_drift']) for row in drifts),
                          maximum_within_program_drift=max(abs(row['fractional_drift']) for row in repeat_drifts)), indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('campaign', type=Path)
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    analyze(args.campaign.resolve(), args.destination.resolve())
