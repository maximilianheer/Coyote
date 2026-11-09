#!/usr/bin/env python3
"""Check report provenance, accepted samples, latency arithmetic and artifacts."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile

import numpy as np


def read(path):
    return json.loads(path.read_text())


def review(campaign, output):
    events = read(output / 'data/trial_events.json')
    statistics = read(output / 'data/statistics.json')
    primary = [row for row in events if row['variant'] in ['FPGA_HLS4ML', 'GPU_P2P']
               and row['workload_role'] in ['real', 'synthetic']]
    assert len(primary) == 4800
    for variant in ['FPGA_HLS4ML', 'GPU_P2P']:
        assert len([row for row in primary if row['variant'] == variant and row['case_id'].startswith('real_')]) == 1600
    assert all(row['count'] == 200 for row in statistics if row['variant'] in ['FPGA_HLS4ML', 'GPU_P2P'])
    for row in events:
        assert row['verdict_ms'] > 0
        assert 3.99 < row['ns_per_tick'] < 4.01
        assert row['hbm_return_end_ms'] < row['verdict_ms']
    for item in read(output / 'data/evidence_manifest.json'):
        assert hashlib.sha256(Path(item['path']).read_bytes()).hexdigest() == item['sha256']
        for line in Path(item['path']).read_text().splitlines():
            raw = json.loads(line)
            assert raw['csr_0'] == 10
            assert (raw['csr_40'] >> 32) & 1 == int(raw['score'] >= 0)
            assert raw['csr_2'] == raw['trial']
    for path, expected in read(output / 'data/archived_report_hashes.json').items():
        assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == expected
    for item in statistics:
        subset = [row['verdict_ms'] for row in events if row['variant'] == item['variant'] and row['case_id'] == item['case_id']]
        assert np.isclose(np.median(subset), item['metrics']['verdict_ms']['median'], rtol=1e-12)
        assert np.isclose(np.percentile(subset, 95), item['metrics']['verdict_ms']['p95'], rtol=1e-12)
    drift = read(output / 'data/opening_closing_drift.json')
    assert any(not row['passed'] for row in drift), 'Cross-program limitation must remain visible'
    assert all(row['passed'] for row in read(output / 'data/within_program_drift.json'))
    for variant in ['opt10_admission', 'opt11_admission']:
        status = read(campaign / variant / 'status.json')
        assert status['status'] == 'passed' and status['validated_calls'] == 520
    assert read(campaign / 'opt11_stale_visibility/status.json')['validated_calls'] == 26
    catalog = read(output / 'data/figure_catalog.json')
    assert len(catalog) == 13
    for item in catalog:
        for extension in ['png', 'svg', 'pdf']:
            path = output / 'figures' / f"{item['id']}.{extension}"
            assert path.stat().st_size > 1000
    with zipfile.ZipFile(output / 'standalone_figures.zip') as archive:
        assert len(archive.namelist()) == 39
        assert archive.testzip() is None
    pdf = output / 'hbm_resident_verdict_report.pdf'
    text = subprocess.check_output(['pdftotext', str(pdf), '-'], text=True)
    for required in ['2026-11-08', 'FPGA_HLS4ML', 'GPU_P2P', 'ConcreteFunction', 'HBM', 'Validation']:
        assert required in text, required
    assert '\ufffd' not in text
    result = dict(status='passed_with_disclosed_cross_program_variation', primary_measured_calls=len(primary),
                  real_primary_calls=3200, figures=len(catalog), standalone_files=39,
                  maximum_control_drift=max(abs(row['fractional_drift']) for row in drift),
                  previous_report_preserved=True,
                  visual_review='Separate visual inspection required; not asserted by this script')
    (output / 'data/review.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('campaign', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    review(args.campaign.resolve(), args.output.resolve())
