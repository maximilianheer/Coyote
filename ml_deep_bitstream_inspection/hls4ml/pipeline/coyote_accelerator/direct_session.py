"""Persistent direct-stream sessions for the campaign CoyoteInference backend."""
from __future__ import annotations

import ctypes as ct
from pathlib import Path
import struct
import numpy as np


class Measurement(ct.Structure):
    _fields_ = [(name, ct.c_uint64) for name in (
        "signature", "status", "transport_bytes", "trial_tag", "host_start_ns",
        "submit_start_ns", "submit_return_ns", "host_dma_done_ns", "host_verdict_seen_ns",
    )] + [("csr", ct.c_uint64 * 24)]


class DirectCoyoteSession:
    def __init__(self, library_path, backend, max_input_bytes, allocation="HPF"):
        if backend not in ("direct_checker", "direct_sink"):
            raise ValueError("backend must be direct_checker or direct_sink")
        if allocation not in ("HPF", "REG") or not 0 <= max_input_bytes <= 134217664:
            raise ValueError("invalid allocation or input capacity")
        self.variant = 7 if backend == "direct_checker" else 8
        self.capacity = max_input_bytes
        self.lib = ct.CDLL(str(Path(library_path).resolve()))
        self.lib.campaign_last_error.restype = ct.c_char_p
        for name, args, result in (
            ("campaign_init", [ct.c_uint]*3, ct.c_void_p),
            ("campaign_prepare", [ct.c_void_p, ct.c_void_p, ct.c_uint], ct.c_int),
            ("campaign_predict", [ct.c_void_p, ct.POINTER(Measurement)], ct.c_int),
            ("campaign_clock", [ct.c_void_p, ct.POINTER(ct.c_uint64)], ct.c_int),
            ("campaign_close", [ct.c_void_p], ct.c_int),
        ):
            fn = getattr(self.lib, name)
            fn.argtypes, fn.restype = args, result
        self.handle = self.lib.campaign_init(self.variant, max_input_bytes, int(allocation == "REG"))
        if not self.handle:
            self._error()

    def _error(self):
        raise RuntimeError(self.lib.campaign_last_error().decode("utf-8", "replace"))

    def _call(self, name, *args):
        if not self.handle:
            raise RuntimeError("session is closed")
        if getattr(self.lib, name)(self.handle, *args):
            self._error()

    def prepare(self, raw):
        data = np.ascontiguousarray(np.asarray(raw, dtype=np.uint8).reshape(-1))
        if data.size > self.capacity:
            raise ValueError("raw input exceeds session capacity")
        self._call("campaign_prepare", data.ctypes.data, data.size)

    def run(self):
        m = Measurement()
        self._call("campaign_predict", ct.byref(m))
        result = {name: int(getattr(m, name)) for name, _ in m._fields_ if name != "csr"}
        result.update({f"csr_{i}": int(m.csr[i-6]) for i in range(6, 30)})
        bits = result["csr_26"] & 0xffffffff
        result["logit"] = struct.unpack("<f", struct.pack("<I", bits))[0] if self.variant == 7 else None
        result["verdict"] = (result["csr_26"] >> 32) & 1 if self.variant == 7 else None
        return result

    def clock_sample(self):
        triple = (ct.c_uint64 * 3)()
        self._call("campaign_clock", triple)
        return tuple(triple)

    def close(self):
        if self.handle:
            handle, self.handle = self.handle, None
            if self.lib.campaign_close(handle):
                self._error()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
