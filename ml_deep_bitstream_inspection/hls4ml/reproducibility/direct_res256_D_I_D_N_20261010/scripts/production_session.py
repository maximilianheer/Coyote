"""Persistent batch-one lifecycle for the unchanged production C++ runtime.

Timing is host observed: no FPGA timestamps or benchmark acceptance are implied.
The native production predict call blocks; callers must supervise board tests in
a separate process to enforce a timeout. Sessions allow one outstanding call.
"""
from __future__ import annotations

import ctypes
import math
import struct
import time
import numpy as np


class ProductionCoyoteSession:
    def __init__(self, overlay, max_input_bytes):
        if not isinstance(max_input_bytes, int) or not 0 <= max_input_bytes <= 134217664:
            raise ValueError("invalid production input capacity")
        self.overlay = overlay
        self.lib = overlay.coyote_lib
        self.capacity = max_input_bytes
        self.handle = None
        self.raw_bytes = None
        # Frozen CoyoteInference explicitly allocates HPF, regardless of env.
        required = overlay._required_hugepages_2m(1, max_input_bytes, 1)
        free = overlay._free_hugepages_2m()
        if free is not None and free < required:
            raise RuntimeError(f"Insufficient hugepages: {free} free, {required} required")
        self.handle = self.lib.init_model_inference_raw(1, max_input_bytes, 1)
        if not self.handle:
            raise RuntimeError("production context allocation returned null")

    def _require_open(self):
        if not self.handle:
            raise RuntimeError("session is closed")

    def prepare(self, raw):
        self._require_open()
        data = np.ascontiguousarray(np.asarray(raw, dtype=np.uint8).reshape(-1))
        if data.size > self.capacity:
            raise ValueError("raw input exceeds session capacity")
        # The unchanged C++ method copies the bytes and writes the 64-byte header.
        self.lib.set_inference_raw_data(self.handle, data, data.size, 0)
        self.raw_bytes = int(data.size)

    def run(self):
        self._require_open()
        if self.raw_bytes is None:
            raise RuntimeError("prepare input before predict")
        host_start = time.monotonic_ns()
        self.lib.flush(self.handle)
        submit_start = time.monotonic_ns()
        self.lib.predict(self.handle)  # LOCAL_TRANSFER; waits for result DMA.
        predict_return = time.monotonic_ns()
        ptr = self.lib.get_inference_predictions(self.handle, 0)
        if not ptr:
            raise RuntimeError("production result pointer is null")
        value = float(ptr[0])
        verdict_seen = time.monotonic_ns()
        if not math.isfinite(value):
            raise RuntimeError("nonfinite production result")
        return dict(raw_bytes=self.raw_bytes, transport_bytes=64+self.raw_bytes,
                    host_start_ns=host_start, submit_start_ns=submit_start,
                    predict_return_ns=predict_return, host_verdict_seen_ns=verdict_seen,
                    logit=value, logit_bits=struct.unpack('<I', struct.pack('<f', value))[0],
                    verdict=int(value >= 0))


    def close(self):
        if self.handle:
            handle, self.handle = self.handle, None
            self.lib.free_model_inference(handle)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
