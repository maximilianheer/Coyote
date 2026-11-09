"""One model/programming-independent CPU session, with cache setup untimed."""

import argparse
import gc
import json
from pathlib import Path
import time

import numpy as np

from common import Arena, cases, environment, pixels, save
from models import Runtime, alias, tf


def scalar_call(function, tensor):
    value = float(function(tensor).numpy().ravel()[0])
    return value, int(value >= 0)


def run(root, kind, session):
    output = root / "measurements" / session / kind
    output.mkdir(parents=True, exist_ok=False)
    arena = Arena(root)
    runtime = Runtime(kind)
    save(output / "environment_before.json", environment())
    save(
        output / "runtime.json",
        dict(
            model=kind,
            tensorflow=tf.__version__,
            xla=True,
            intra_threads=tf.config.threading.get_intra_op_parallelism_threads(),
            inter_threads=tf.config.threading.get_inter_op_parallelism_threads(),
            visible_gpus=[
                str(device) for device in tf.config.get_visible_devices("GPU")
            ],
            zero_copy="NumPy DLPack CPU alias checked by mutation before timing",
            quantized_arithmetic=(
                "QKeras fake quantization with floating CPU kernels"
                if kind != "FP32"
                else "FP32"
            ),
        ),
    )
    manifest = cases()
    if session == "B":
        manifest.reverse()
    save(output / "manifest.json", manifest)
    all_calls = 0
    gc.disable()
    with (output / "trials.jsonl").open("w", buffering=1) as trials:
        for case in manifest:
            raw = arena.load(case)
            tensor = alias(raw)
            prepared_array = np.ascontiguousarray(pixels(raw))
            prepared = alias(prepared_array)
            expected = float(
                runtime.model(tf.convert_to_tensor(prepared_array), training=False)
                .numpy()
                .ravel()[0]
            )
            fused = runtime.combined(len(raw))
            inference = runtime.prepared()
            preprocessing = runtime.preprocessing(len(raw)) if kind == "FP32" else None
            for function, argument in [(fused, tensor), (inference, prepared)]:
                actual, verdict = scalar_call(function, argument)
                np.testing.assert_allclose(actual, expected, rtol=1e-4, atol=1e-4)
                assert verdict == int(expected >= 0)
            if preprocessing is not None:
                np.testing.assert_allclose(
                    preprocessing(tensor).numpy(), prepared_array, rtol=0, atol=1.2e-7
                )
            scopes = ["input_cold", "selected_lines_warm"]
            if session == "B":
                scopes.reverse()
            modes = [("total", scope, fused, tensor, raw) for scope in scopes]
            modes.append(
                ("inference_only", "input_cold", inference, prepared, prepared_array)
            )
            if preprocessing is not None:
                modes.append(
                    ("preprocessing_only", "input_cold", preprocessing, tensor, raw)
                )
            for mode, scope, function, argument, cache_array in modes:
                before = environment()
                for index in range(220):
                    setup_start = time.perf_counter_ns()
                    if scope == "input_cold":
                        arena.flush(cache_array)
                    else:
                        arena.warm(cache_array)
                    setup_end = time.perf_counter_ns()
                    cpu_begin = time.process_time_ns()
                    begin = time.perf_counter_ns()
                    if mode == "preprocessing_only":
                        result = function(argument).numpy()
                        end = time.perf_counter_ns()
                        cpu_end = time.process_time_ns()
                        value = float(result.flat[0])
                        verdict = None
                        np.testing.assert_allclose(
                            result, prepared_array, rtol=0, atol=1.2e-7
                        )
                    else:
                        value, verdict = scalar_call(function, argument)
                        end = time.perf_counter_ns()
                        cpu_end = time.process_time_ns()
                        np.testing.assert_allclose(
                            value, expected, rtol=1e-4, atol=1e-4
                        )
                        assert verdict == int(expected >= 0)
                    row = dict(
                        session=session,
                        model=kind,
                        mode=mode,
                        cache_scope=scope,
                        case_id=case["id"],
                        workload_scope=case["scope"],
                        input_bytes=len(raw),
                        input_sha256=case["sha256"],
                        trial=index,
                        warmup=index < 20,
                        elapsed_ns=end - begin,
                        process_cpu_ns=cpu_end - cpu_begin,
                        untimed_cache_setup_ns=setup_end - setup_start,
                        score=value,
                        expected_score=(
                            expected if mode != "preprocessing_only" else None
                        ),
                        verdict=verdict,
                        validation="passed",
                        captured_at=time.time(),
                    )
                    trials.write(json.dumps(row) + "\n")
                    all_calls += 1
                    if index % 20 == 19:
                        save(
                            output / "status.json",
                            dict(
                                status="running",
                                calls=all_calls,
                                case_id=case["id"],
                                mode=mode,
                                cache_scope=scope,
                                trial=index,
                                updated_at=time.time(),
                            ),
                        )
                save(
                    output / f"{case['id']}_{mode}_{scope}_environment.json",
                    dict(before=before, after=environment()),
                )
                print(
                    session,
                    kind,
                    case["id"],
                    mode,
                    scope,
                    all_calls,
                    "validated calls",
                    flush=True,
                )
    save(
        output / "arena_mapping.json",
        dict(
            address=arena.address,
            capacity=arena.capacity,
            collapse_result=arena.collapse_result,
            smaps=arena.mapping(),
        ),
    )
    save(output / "environment_after.json", environment())
    save(
        output / "status.json",
        dict(
            status="passed",
            calls=all_calls,
            model=kind,
            session=session,
            completed_at=time.time(),
        ),
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("kind", choices=["FP32", "QKERAS_W8A8"])
    parser.add_argument("session", choices=["A", "B"])
    args = parser.parse_args()
    run(args.root.resolve(), args.kind, args.session)
