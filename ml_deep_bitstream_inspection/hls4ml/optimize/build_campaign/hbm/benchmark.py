#!/usr/bin/env python3
"""HBM-resident ABI5 admission and latency collection; preload is untimed."""
import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import struct
import shutil
import sys
import time

import numpy as np

from hbm_transport import Transport


REPO = Path(__file__).resolve().parents[4]
REFERENCE = REPO / 'hls4ml/optimize/runs/gpu_runtime_investigation_20261021_030038/hardware_xla_concrete'


def cases(path):
    result = []
    for line in path.read_text().splitlines():
        name, sweep, source, size, digest, logit = line.split('\t')
        result.append(dict(id=name, sweep=sweep, path=source, bytes=int(size),
                           sha256=digest, quantized_bits=int(logit, 16)))
    return result


def pixels(raw):
    if raw.size > 65536:
        selected = raw[np.arange(65536, dtype=np.int64) * (raw.size - 1) // 65535]
    else:
        selected = np.pad(raw, (0, 65536 - raw.size))
    return ((255 - selected).astype(np.float32) / np.float32(255)).reshape(1, 256, 256, 1)


class Gpu:
    def __init__(self):
        # Match the accepted R06 runtime and preserve its original source.
        os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'
        sys.path.insert(0, str(REFERENCE / 'software/gpu_runtime'))
        import tensorflow as tf
        from fp32_model import build_model
        from xla_runtime import CombinedInference
        tf.config.threading.set_inter_op_parallelism_threads(1)
        tf.config.threading.set_intra_op_parallelism_threads(1)
        for device in tf.config.list_physical_devices('GPU'):
            tf.config.experimental.set_memory_growth(device, True)
        tf.config.experimental.enable_tensor_float_32_execution(False)
        self.tf = tf
        self.infer = CombinedInference(build_model('/GPU:0'))
        self.cpu = build_model('/CPU:0')

    def prepare(self, raw):
        with self.tf.device('/CPU:0'):
            expected = float(self.cpu(self.tf.convert_to_tensor(pixels(raw)), training=False).numpy().ravel()[0])
        with self.tf.device('/GPU:0'):
            warm = self.tf.convert_to_tensor(raw)
            actual = float(self.infer(warm).numpy().ravel()[0])
        self.validate(actual, expected)
        return expected

    @staticmethod
    def validate(actual, expected):
        assert np.isfinite(actual)
        assert abs(actual - expected) <= 1e-4 + 1e-4 * abs(expected), (actual, expected)
        assert (actual >= 0) == (expected >= 0)

    def run(self, transport, delay=False, profile=False, validate_bytes=None, stale=False):
        transport.wait_input()
        if validate_bytes is not None:
            # Admission only: an intrusive D2H comparison proves external DMA
            # visibility before inference. Latency runs use the validated fence.
            np.testing.assert_array_equal(transport.read_gpu(), validate_bytes)
        raw = self.tf.experimental.dlpack.from_dlpack(transport.input_capsule())
        begin = time.monotonic_ns()
        marker = self.tf.profiler.experimental.Trace('combined_compute', _r=1) if profile else contextlib.nullcontext()
        with marker:
            score = self.infer(raw)
            # Export synchronizes the producer, as in the accepted R06 runtime.
            capsule = self.tf.experimental.dlpack.to_dlpack(score)
        end = time.monotonic_ns()
        if delay:
            if stale:
                generation = transport.snapshot()['csr_2'] - 1
                transport.publish(self.tf.experimental.dlpack.to_dlpack(score), generation)
            time.sleep(0.01)
            assert not (transport.snapshot()['csr_0'] & 8), 'Verdict before publication'
        transport.publish(capsule)
        return begin, end, time.monotonic_ns()


def run(args):
    os.sched_setaffinity(0, {64})
    args.output.mkdir(parents=True, exist_ok=True)
    shutil.copy2(__file__, args.output / 'collector_snapshot.py')
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from host_environment import snapshot
    os.environ['COYOTE_BENCH_PCI_BDF'] = '0000:81:00.0'
    (args.output / 'environment_before.json').write_text(json.dumps(snapshot(), indent=2))
    manifest = cases(args.manifest or REFERENCE / ('admission.tsv' if args.mode == 'admission' else 'cases.tsv'))
    if args.case:
        manifest = [case for case in manifest if case['id'] == args.case]
    assert manifest
    transport = Transport(134217728)
    signature = transport.snapshot()['csr_4']
    variant = signature & 0xffff
    gpu = Gpu() if variant == 11 else None
    (args.output / 'manifest.json').write_text(json.dumps(manifest, indent=2))
    trial = int(time.time()) << 16
    total = 0
    with (args.output / 'trials.jsonl').open('a', buffering=1) as output:
        try:
            for case in manifest:
                raw = np.fromfile(case['path'], dtype=np.uint8)
                assert len(raw) == case['bytes']
                assert hashlib.sha256(raw).hexdigest() == case['sha256']
                expected = gpu.prepare(raw) if gpu else None
                placement_begin = time.monotonic_ns()
                transport.load(raw)
                placement_end = time.monotonic_ns()
                assert transport.verify(raw)
                verification_end = time.monotonic_ns()
                placement = dict(input_bytes=len(raw), preload_ms=(placement_end - placement_begin) / 1e6,
                                 readback_and_reoffload_ms=(verification_end - placement_end) / 1e6,
                                 scope='Untimed setup diagnostic; includes host preparation and driver migration')
                (args.output / (case['id'] + '_placement.json')).write_text(json.dumps(placement, indent=2))
                clocks_before = list(transport.calibrate())
                if args.mode == 'profile':
                    assert gpu is not None
                    gpu.tf.profiler.experimental.start(str(args.output / 'profiles' / case['id']))
                unique_words = len(np.unique(np.arange(65536, dtype=np.int64) * (len(raw) - 1) // 65535 // 64)) if len(raw) > 65536 else (len(raw) + 63) // 64
                for index in range(args.warmup + args.repeat):
                    trial += 1
                    transport.start(trial)
                    begin, end, published = gpu.run(
                        transport, delay=args.mode == 'admission' and index == 0,
                        profile=args.mode == 'profile',
                        validate_bytes=raw if args.mode == 'admission' else None,
                        stale=args.stale) if gpu else (None, None, None)
                    row = dict(transport.finish())
                    row.update(case_id=case['id'], sweep=case['sweep'], bytes=len(raw),
                               trial=trial, warmup=index < args.warmup,
                               gpu_framework_begin_ns=begin, gpu_framework_end_ns=end,
                               gpu_publication_complete_ns=published,
                               fp32_cpu_reference=expected, mode=args.mode)
                    assert row['csr_0'] == 10, row
                    assert row['csr_2'] == trial
                    assert row['csr_7'] & (1 << 8)
                    assert row['csr_24'] >= row['csr_6']
                    bits = row['csr_40'] & 0xffffffff
                    score = struct.unpack('<f', struct.pack('<I', bits))[0]
                    row['score'] = score
                    row['verdict_ms'] = (row['csr_24'] - row['csr_6']) * 4e-6
                    if gpu:
                        gpu.validate(score, expected)
                        assert row['csr_48'] == len(raw)
                        assert row['csr_49'] == (len(raw) + 65535) // 65536
                        if index == 0 or args.mode == 'admission':
                            np.testing.assert_array_equal(transport.read_gpu(), raw)
                    else:
                        assert bits == case['quantized_bits'], (case['id'], hex(bits), hex(case['quantized_bits']))
                        assert row['csr_48'] == unique_words, (case['id'], row['csr_48'], unique_words)
                        assert row['csr_49'] == unique_words
                        assert row['csr_50'] == unique_words
                        assert row['csr_51'] == 65536
                    row['validation'] = 'passed'
                    output.write(json.dumps(row) + '\n')
                    total += 1
                if args.mode == 'profile':
                    gpu.tf.profiler.experimental.stop()
                assert transport.verify(raw)
                clocks = dict(before=clocks_before, after=list(transport.calibrate()))
                (args.output / (case['id'] + '_clock.json')).write_text(json.dumps(clocks))
                progress = dict(status='running', case=case['id'], validated_calls=total, updated_at=time.time())
                (args.output / 'status.json').write_text(json.dumps(progress, indent=2))
                print(json.dumps(progress), flush=True)
        except BaseException as error:
            failure = dict(status='failed', error=repr(error), registers=dict(transport.snapshot()), validated_calls=total)
            (args.output / 'status.json').write_text(json.dumps(failure, indent=2))
            raise
    (args.output / 'status.json').write_text(json.dumps(dict(status='passed', variant=variant, validated_calls=total), indent=2))
    (args.output / 'environment_after.json').write_text(json.dumps(snapshot(), indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--mode', choices=['admission', 'pilot', 'main', 'closing', 'diagnostic', 'profile'], required=True)
    parser.add_argument('--warmup', type=int, default=0)
    parser.add_argument('--repeat', type=int, required=True)
    parser.add_argument('--case')
    parser.add_argument('--manifest', type=Path)
    parser.add_argument('--stale', action='store_true')
    run(parser.parse_args())
