#!/usr/bin/env python3
"""Profile fused GPU work after one validated, fully drained P2P delivery.

Do not invoke the HIP publication adapter while ROCm tracing is active. The
unprofiled hardware campaign already measures publication and FPGA polling.
"""
import argparse
import json
import os
from pathlib import Path

import numpy as np

from benchmark import Gpu, REFERENCE, cases
from hbm_transport import Transport


def run(root, case_id):
    os.sched_setaffinity(0, {64})
    case = next(case for case in cases(REFERENCE / 'cases.tsv') if case['id'] == case_id)
    raw = np.fromfile(case['path'], dtype=np.uint8)
    transport = Transport(134217728)
    gpu = Gpu()
    expected = gpu.prepare(raw)
    transport.load(raw)
    transport.verify(raw)
    transport.start(1234567)
    gpu.run(transport, validate_bytes=raw)
    result = dict(transport.finish())
    assert result['csr_0'] == 10
    tensor = gpu.tf.experimental.dlpack.from_dlpack(transport.input_capsule())
    for _ in range(5):
        gpu.validate(float(gpu.infer(tensor).numpy().ravel()[0]), expected)
    root.mkdir(parents=True, exist_ok=True)
    trace = root / 'profiles' / case_id
    gpu.tf.profiler.experimental.start(str(trace))
    for _ in range(5):
        with gpu.tf.profiler.experimental.Trace('combined_compute', _r=1):
            score = gpu.infer(tensor).numpy()
        gpu.validate(float(score.ravel()[0]), expected)
    gpu.tf.profiler.experimental.stop()
    (root / f'{case_id}_status.json').write_text(json.dumps(dict(
        status='passed', case_id=case_id, profiled_calls=5,
        scope='Resident GPU input after validated P2P; fused compute only; no publication in trace',
        delivery_registers=result), indent=2))
    print('PASS isolated fused GPU profiling', case_id, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('root', type=Path)
    parser.add_argument('case_id')
    args = parser.parse_args()
    run(args.root.resolve(), args.case_id)
