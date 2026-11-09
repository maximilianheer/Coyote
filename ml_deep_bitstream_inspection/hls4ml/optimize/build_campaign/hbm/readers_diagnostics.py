#!/usr/bin/env python3
"""Pin separate small-input diagnostics and exact quantized CPU references."""
import argparse
import ctypes
import hashlib
import json
from pathlib import Path

import numpy as np


def prepare(root):
    repo = Path(__file__).resolve().parents[4]
    library_path = (
        repo
        / "hls4ml/optimize/runs/hbm_network_20261107/OPT_10_HBM_GATHER_DSP_B2_RF72_RF288/attempt_01/hw/src/hls/cnn_wrapper/firmware/iteration_model-68668784.so"
    )
    library = ctypes.CDLL(str(library_path))
    predict = library.iteration_model_float
    pointer = np.ctypeslib.ndpointer(dtype=np.float32, flags="C_CONTIGUOUS")
    predict.argtypes = [pointer, pointer]
    score = np.zeros(1, dtype=np.float32)
    target = root / "diagnostic_inputs"
    target.mkdir(exist_ok=False)
    rows = []
    for size in [4095, 4096, 4097, 1048576, 2097151, 2097152, 2097153]:
        index = np.arange(size, dtype=np.int64)
        raw = ((index * 71 + index // 97) % 256).astype(np.uint8)
        path = target / f"boundary_{size}.bin"
        raw.tofile(path)
        if size > 65536:
            selected = raw[np.arange(65536, dtype=np.int64) * (size - 1) // 65535]
        else:
            selected = np.pad(raw, (0, 65536 - size))
        prepared = (255 - selected).astype(np.float32) / np.float32(255)
        predict(prepared, score)
        rows.append(
            f"boundary_{size}\tdiagnostic\t{path}\t{size}\t{hashlib.sha256(raw).hexdigest()}\t{int(score.view(np.uint32)[0]):08x}"
        )
    reference = (
        repo
        / "hls4ml/optimize/runs/gpu_runtime_investigation_20261021_030038/hardware_xla_concrete/cases.tsv"
    )
    rows.extend(
        line for line in reference.read_text().splitlines() if line.startswith("smoke_")
    )
    (root / "diagnostics.tsv").write_text("\n".join(rows) + "\n")
    (root / "diagnostic_reference.json").write_text(
        json.dumps(
            dict(
                library=str(library_path),
                sha256=hashlib.sha256(library_path.read_bytes()).hexdigest(),
                pattern="(index * 71 + index // 97) % 256",
                scope="Separate diagnostics; never pooled with primary real/synthetic inputs",
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    prepare(parser.parse_args().root.resolve())
