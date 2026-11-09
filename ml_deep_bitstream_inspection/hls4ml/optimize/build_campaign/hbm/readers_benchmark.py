#!/usr/bin/env python3
"""One configuration/session stage; primary timing uses accepted FPGA arm."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time

import numpy as np
from hbm_transport import Transport

from benchmark import Gpu, REFERENCE, cases
from readers_spec import (
    CONFIGURATIONS,
    effective_setting,
    expected_counters,
    identify,
    validate,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from host_environment import snapshot


def save(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


def run(args):
    os.sched_setaffinity(0, {64})
    os.environ["COYOTE_BENCH_PCI_BDF"] = "0000:81:00.0"
    configuration = next(
        item for item in CONFIGURATIONS if item["key"] == args.configuration
    )
    args.output.mkdir(parents=True, exist_ok=False)
    shutil.copy2(__file__, args.output / "collector_snapshot.py")
    save(
        args.output / "configuration.json",
        dict(configuration, session=args.session, mode=args.mode),
    )
    save(args.output / "environment_before.json", snapshot())
    manifest = cases(
        args.manifest
        or REFERENCE / ("admission.tsv" if args.mode == "admission" else "cases.tsv")
    )
    if args.mode != "admission" and args.manifest is None:
        manifest = [
            item
            for item in manifest
            if item["sweep"] in ["real", "synthetic"]
            and not item["id"].startswith("smoke_")
        ]
        assert len(manifest) == 12
    if args.reverse:
        manifest.reverse()
    save(args.output / "manifest.json", manifest)
    transport = Transport(134217728)
    variant, abi = identify(transport.snapshot()["csr_4"])
    assert variant == configuration["variant"]
    gpu = Gpu() if variant == 11 else None
    trial = (int(time.time()) << 20) + os.getpid()
    calls = 0
    try:
        with (args.output / "trials.jsonl").open("w", buffering=1) as output, (
            args.output / "calibration.jsonl"
        ).open("w", buffering=1) as calibration:
            for case in manifest:
                raw = np.fromfile(case["path"], dtype=np.uint8)
                assert len(raw) == case["bytes"]
                assert hashlib.sha256(raw).hexdigest() == case["sha256"]
                reference = gpu.prepare(raw) if gpu else None
                before = time.monotonic_ns()
                transport.load(raw)
                loaded = time.monotonic_ns()
                assert transport.verify(raw)
                save(
                    args.output / (case["id"] + "_placement.json"),
                    dict(
                        input_bytes=len(raw),
                        preload_ms=(loaded - before) / 1e6,
                        readback_reoffload_ms=(time.monotonic_ns() - loaded) / 1e6,
                        scope="Untimed setup, includes host preparation and full-capacity migration",
                    ),
                )
                base = transport.snapshot()["csr_8"]
                # The allocator returns a hugepage-aligned base. Page-boundary
                # oracle results are consequently independent of ASLR.
                expected = expected_counters(
                    variant, len(raw), configuration["setting"], 0
                )
                for block_start in range(0, args.warmup + args.repeat, 20):
                    clocks_before = list(transport.calibrate())
                    first_trial = trial + 1
                    block_end = min(block_start + 20, args.warmup + args.repeat)
                    for index in range(block_start, block_end):
                        trial += 1
                        transport.start(trial, configuration["setting"])
                        begin, end, published = None, None, None
                        if gpu:
                            begin, end, published = gpu.run(
                                transport,
                                delay=args.mode == "admission" and index == 0,
                                validate_bytes=(
                                    raw if args.mode == "admission" else None
                                ),
                                stale=args.mode == "admission",
                            )
                        row = dict(transport.finish())
                        row.update(
                            trial=trial,
                            case_id=case["id"],
                            sweep=case["sweep"],
                            input_bytes=len(raw),
                            input_sha256=case["sha256"],
                            configuration=args.configuration,
                            session=args.session,
                            mode=args.mode,
                            setting=configuration["setting"],
                            warmup=index < args.warmup,
                            block=block_start // 20,
                            gpu_framework_begin_ns=begin,
                            gpu_framework_end_ns=end,
                            gpu_publication_complete_ns=published,
                            fp32_reference=reference,
                        )
                        row["captured_wall_time_ns"] = time.time_ns()
                        row["score"] = validate(
                            row, configuration, expected, case, reference
                        )
                        assert row["csr_8"] % 2097152 == 0
                        row["validation"] = "passed"
                        row["nominal_verdict_ms"] = (
                            row["csr_24"] - row["csr_6"]
                        ) * 4e-6
                        output.write(json.dumps(row) + "\n")
                        calls += 1
                    calibration.write(
                        json.dumps(
                            dict(
                                session=args.session,
                                configuration=args.configuration,
                                case_id=case["id"],
                                block=block_start // 20,
                                first_trial=first_trial,
                                last_trial=trial,
                                before=clocks_before,
                                after=list(transport.calibrate()),
                            )
                        )
                        + "\n"
                    )
                    save(
                        args.output / "status.json",
                        dict(
                            status="running",
                            calls=calls,
                            case=case["id"],
                            block=block_start // 20,
                            updated_at=time.time(),
                        ),
                    )
                if gpu:
                    np.testing.assert_array_equal(transport.read_gpu(), raw)
                assert transport.verify(raw)
                print(
                    args.session,
                    args.configuration,
                    args.mode,
                    case["id"],
                    calls,
                    "validated calls",
                    flush=True,
                )
    except BaseException as error:
        registers = dict(transport.snapshot())
        status = "failed_holding_mappings" if registers["csr_0"] & 1 else "failed"
        save(
            args.output / "status.json",
            dict(
                status=status,
                error=repr(error),
                calls=calls,
                registers=registers,
                updated_at=time.time(),
            ),
        )
        if status == "failed_holding_mappings":
            # Do not let process teardown unmap memory beneath live DMA. The
            # supervising main thread must prove drain or reset the device and
            # then authorize cleanup through this campaign-local marker.
            while not (args.output / "release_after_safe_drain").exists():
                time.sleep(1)
        raise
    save(
        args.output / "status.json",
        dict(
            status="passed",
            calls=calls,
            variant=variant,
            abi=abi,
            session=args.session,
            configuration=args.configuration,
            setting=configuration["setting"],
            mode=args.mode,
            completed_at=time.time(),
        ),
    )
    save(args.output / "environment_after.json", snapshot())


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--configuration",
        required=True,
        choices=[item["key"] for item in CONFIGURATIONS],
    )
    parser.add_argument("--session", required=True, choices=["A", "B"])
    parser.add_argument(
        "--mode", required=True, choices=["admission", "pilot", "main", "diagnostic"]
    )
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--warmup", type=int, default=0)
    parser.add_argument("--repeat", type=int, required=True)
    parser.add_argument("--reverse", action="store_true")
    run(parser.parse_args())
