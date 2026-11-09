"""CPU-only campaign utilities; importing this file never initializes TensorFlow."""

import ctypes
import hashlib
import json
import os
from pathlib import Path
import time

import numpy as np

REPO = next(
    parent
    for parent in Path(__file__).resolve().parents
    if (
        parent / "ML_Based_Deep_Bitstream_Inspection_for_Serverless_FPGAs_Report.pdf"
    ).exists()
)
GPU_REFERENCE = (
    REPO
    / "hls4ml/optimize/runs/gpu_runtime_investigation_20261021_030038/hardware_xla_concrete"
)


def save(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def cases(admission=False):
    result = []
    for line in (
        (GPU_REFERENCE / ("admission.tsv" if admission else "cases.tsv"))
        .read_text()
        .splitlines()
    ):
        name, scope, path, size, digest, bits = line.split("\t")
        if not admission and scope not in ["real", "synthetic"]:
            continue
        result.append(
            dict(
                id=name,
                scope=scope,
                path=path,
                bytes=int(size),
                sha256=digest,
                hls_bits=bits,
            )
        )
    return result


def pixels(raw):
    if len(raw) > 65536:
        selected = raw[np.arange(65536, dtype=np.int64) * (len(raw) - 1) // 65535]
    else:
        selected = np.pad(raw, (0, 65536 - len(raw)))
    return ((255 - selected).astype(np.float32) / np.float32(255)).reshape(
        1, 256, 256, 1
    )


class Arena:
    def __init__(self, root):
        self.capacity = 134217728
        self.library = ctypes.CDLL(str(root / "software/cache_control.so"))
        self.library.allocate_arena.argtypes = [ctypes.c_size_t]
        self.library.allocate_arena.restype = ctypes.c_void_p
        self.library.flush_input.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
        self.library.collapse_arena.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
        for name in ["warm_selected", "warm_all"]:
            function = getattr(self.library, name)
            function.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
            function.restype = ctypes.c_uint64
        self.library.probe_line.argtypes = [ctypes.c_void_p, ctypes.c_bool]
        self.library.probe_line.restype = ctypes.c_uint64
        self.address = self.library.allocate_arena(self.capacity)
        assert self.address and self.address % 2097152 == 0
        self.array = np.ctypeslib.as_array(
            (ctypes.c_uint8 * self.capacity).from_address(self.address)
        )
        self.array.fill(0)
        self.collapse_result = self.library.collapse_arena(self.address, self.capacity)

    def flush(self, array):
        assert array.flags.c_contiguous
        self.library.flush_input(array.ctypes.data, array.nbytes)

    def warm(self, array, selected=True):
        function = self.library.warm_selected if selected else self.library.warm_all
        return function(array.ctypes.data, array.nbytes)

    def load(self, case):
        raw = np.fromfile(case["path"], dtype=np.uint8)
        assert (
            len(raw) == case["bytes"]
            and hashlib.sha256(raw).hexdigest() == case["sha256"]
        )
        self.array[: len(raw)] = raw
        return self.array[: len(raw)]

    def mapping(self):
        lines = Path("/proc/self/smaps").read_text().splitlines()
        result = []
        selected = False
        for line in lines:
            first = line.split()[0] if line.split() else ""
            if "-" in first:
                try:
                    low, high = (int(part, 16) for part in first.split("-"))
                    selected = low <= self.address < high
                except ValueError:
                    selected = False
            if selected:
                result.append(line)
        return result


def environment():
    threads = {}
    for directory in Path("/proc/self/task").iterdir():
        text = (directory / "status").read_text()
        affinity = next(
            line.split(":", 1)[1].strip()
            for line in text.splitlines()
            if line.startswith("Cpus_allowed_list:")
        )
        threads[directory.name] = affinity
        assert affinity == "2", (directory.name, affinity)
    return dict(
        captured_at=time.time(),
        affinity=sorted(os.sched_getaffinity(0)),
        thread_affinities=threads,
        numa_maps=Path("/proc/self/numa_maps").read_text(),
        cpu_stat=Path("/proc/stat").read_text(),
        load=Path("/proc/loadavg").read_text(),
        kernel=os.uname().release,
        frequency_khz=Path("/sys/devices/system/cpu/cpu2/cpufreq/scaling_cur_freq")
        .read_text()
        .strip(),
    )
