#!/usr/bin/env python3
"""Pin additional boundary inputs and exact hls4ml CPU reference scores."""
import argparse
import ctypes
import hashlib
import json
from pathlib import Path

import numpy as np


def run(root):
    repo = Path(__file__).resolve().parents[4]
    library_path = repo / 'hls4ml/optimize/runs/hbm_network_20261107/OPT_10_HBM_GATHER_DSP_B2_RF72_RF288/attempt_01/hw/src/hls/cnn_wrapper/firmware/iteration_model-68668784.so'
    library = ctypes.CDLL(str(library_path))
    predict = library.iteration_model_float
    pointer = np.ctypeslib.ndpointer(dtype=np.float32, flags='C_CONTIGUOUS')
    predict.argtypes = [pointer, pointer]
    output = np.zeros(1, dtype=np.float32)

    def reference(raw):
        if len(raw) > 65536:
            sample = raw[np.arange(65536, dtype=np.int64) * (len(raw) - 1) // 65535]
        else:
            sample = np.pad(raw, (0, 65536 - len(raw)))
        prepared = (255 - sample).astype(np.float32) / np.float32(255)
        predict(prepared, output)
        return int(output.view(np.uint32)[0])

    previous = repo / 'hls4ml/optimize/runs/gpu_runtime_investigation_20261021_030038/hardware_xla_concrete/cases.tsv'
    first = previous.read_text().splitlines()[0].split('\t')
    assert reference(np.fromfile(first[2], dtype=np.uint8)) == int(first[5], 16)
    inputs = root / 'inputs'
    inputs.mkdir(exist_ok=True)
    lines = []
    rng = np.random.default_rng(20261108)
    for size in [4095, 4096, 4097, 1048576, 2097152]:
        raw = rng.integers(0, 256, size, dtype=np.uint8)
        path = inputs / f'boundary_{size}.bin'
        raw.tofile(path)
        digest = hashlib.sha256(raw).hexdigest()
        lines.append(f'boundary_{size}\tdiagnostic\t{path}\t{size}\t{digest}\t{reference(raw):08x}')
    (root / 'diagnostics.tsv').write_text('\n'.join(lines) + '\n')
    (root / 'reference_identity.json').write_text(json.dumps(dict(
        library=str(library_path), sha256=hashlib.sha256(library_path.read_bytes()).hexdigest(),
        existing_reference_check='passed', seed=20261108), indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('root', type=Path)
    run(parser.parse_args().root.resolve())
