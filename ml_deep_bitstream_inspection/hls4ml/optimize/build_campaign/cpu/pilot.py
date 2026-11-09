"""CPU placement, cache-eviction, model parity and runtime selection pilot."""

import argparse
import json
import os
from pathlib import Path
import time

import numpy as np

from common import Arena, cases, environment, pixels, save
from models import Runtime, alias, tf


def run(root, kind):
    directory = root / "preflight" / kind
    directory.mkdir(exist_ok=True)
    arena = Arena(root)
    save(directory / "environment.json", environment())
    rng = np.random.default_rng(20261109)
    indices = rng.integers(0, arena.capacity // 4096, size=512) * 4096
    cache = {}
    for cold in [False, True]:
        cache["cold" if cold else "warm"] = [
            int(arena.library.probe_line(arena.address + int(offset), cold))
            for offset in indices
        ]
    assert np.median(cache["cold"]) > 2 * np.median(cache["warm"]), cache
    save(directory / "cache_probe.json", cache)
    runtime = Runtime(kind)
    validation = []
    for case in cases(admission=True):
        raw = arena.load(case)
        tensor = alias(raw)
        expected_pixels = pixels(raw)
        with tf.device("/CPU:0"):
            expected = float(
                runtime.model(tf.convert_to_tensor(expected_pixels), training=False)
                .numpy()
                .ravel()[0]
            )
        function = runtime.combined(len(raw))
        begin = time.perf_counter()
        actual = float(function(tensor).numpy().ravel()[0])
        elapsed = time.perf_counter() - begin
        np.testing.assert_allclose(actual, expected, rtol=1e-4, atol=1e-4)
        assert (actual >= 0) == (expected >= 0)
        times = {}
        for scope in ["selected_lines_warm", "input_cold"]:
            samples = []
            for index in range(5):
                if scope == "input_cold":
                    arena.flush(raw)
                else:
                    arena.warm(raw)
                begin = time.perf_counter_ns()
                value = float(function(tensor).numpy().ravel()[0])
                verdict = int(value >= 0)
                end = time.perf_counter_ns()
                assert verdict == int(expected >= 0)
                samples.append((end - begin) / 1e6)
            times[scope] = samples
        validation.append(
            dict(
                case_id=case["id"],
                bytes=len(raw),
                expected=expected,
                actual=actual,
                first_compile_and_call_s=elapsed,
                samples_ms=times,
            )
        )
        save(directory / "validation_progress.json", validation)
        print(
            kind,
            case["id"],
            "passed",
            {key: round(float(np.median(value)), 3) for key, value in times.items()},
            flush=True,
        )
    save(
        directory / "arena_mapping.json",
        dict(
            address=arena.address,
            capacity=arena.capacity,
            collapse_result=arena.collapse_result,
            smaps=arena.mapping(),
        ),
    )
    save(
        directory / "result.json",
        dict(
            status="passed",
            model=kind,
            calls=len(validation),
            tensorflow=tf.__version__,
            xla=True,
            GPU_devices=tf.config.get_visible_devices("GPU"),
            cache_probe_medians={
                key: float(np.median(value)) for key, value in cache.items()
            },
            results=validation,
        ),
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("kind", choices=["FP32", "QKERAS_W8A8"])
    args = parser.parse_args()
    run(args.root.resolve(), args.kind)
