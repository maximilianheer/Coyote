#!/usr/bin/env python3
"""Calibrated two-round analysis; retain session identity and all accepted trials."""
import argparse
import csv
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

from readers_spec import CONFIGURATIONS, COUNTERS, identify

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from board_benchmark import clock_model


def read_rows(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def clock_models(directory):
    result = {}
    evidence = []
    for block in read_rows(directory / "calibration.jsonl"):
        samples = [
            dict(position=position, host_before_ns=a, fpga_tick=tick, host_after_ns=b)
            for position in ["before", "after"]
            for a, tick, b in block[position]
        ]
        mapped, details = clock_model(samples)
        result[block["case_id"], block["block"]] = (mapped, details)
        evidence.append(dict(case_id=block["case_id"], block=block["block"], **details))
    return result, evidence


def derive(row, mapped, fit):
    variant, abi = identify(row["csr_4"])
    tick_ns = (fit["ns_per_tick_min"] + fit["ns_per_tick_max"]) / 2
    arm = row["csr_6"]
    arm_lo, arm_hi = mapped(arm)
    arm_host = (arm_lo + arm_hi) / 2
    verdict_lo, verdict_hi = mapped(row["csr_24"])
    assert (
        verdict_lo <= row["host_verdict_seen_ns"] and verdict_hi >= row["host_start_ns"]
    )
    result = dict(
        configuration=row["configuration"],
        session=row["session"],
        trial=row["trial"],
        case_id=row["case_id"],
        sweep=row["sweep"],
        input_bytes=row["input_bytes"],
        input_sha256=row["input_sha256"],
        mode=row["mode"],
        setting=row["setting"],
        variant=variant,
        abi=abi,
        ns_per_tick=tick_ns,
        verdict_ms=(row["csr_24"] - arm) * tick_ns / 1e6,
        host_observed_ms=(row["host_verdict_seen_ns"] - row["host_start_ns"]) / 1e6,
        drain_observed_ms=(row["host_drained_ns"] - arm_host) / 1e6,
        arm_alignment_uncertainty_ms=(arm_hi - arm_lo) / 2e6,
        measurement_date=datetime.fromtimestamp(row["captured_wall_time_ns"] / 1e9)
        .date()
        .isoformat(),
    )
    assert row["csr_0"] == 10 and row["csr_2"] == row["trial"]
    assert row["csr_7"] & (1 << 8)
    valid = row["csr_7"]
    for name, start, end in [
        ("hbm_request", 16, 17),
        ("hbm_return", 18, 19),
        ("pixel", 20, 21),
        ("cnn_input", 22, 23),
        ("verdict", 24, 25),
        ("hbm_completion", 26, 27),
        ("gpu_forward", 28, 29),
        ("gpu_write_completion", 30, 31),
        ("poll_requests", 32, 33),
    ]:
        for suffix, register in [("start", start), ("end", end)]:
            result[f"{name}_{suffix}_ms"] = (
                (row[f"csr_{register}"] - arm) * tick_ns / 1e6
                if valid & (1 << (register - 16))
                else None
            )
    if variant == 11:
        result.update(
            requested_bytes=row["input_bytes"],
            logical_requests=row["csr_49"],
            request_count_scope="Completed bulk chunks; one logical HBM read per chunk",
            framework_ms=(row["gpu_framework_end_ns"] - row["gpu_framework_begin_ns"])
            / 1e6,
            poll_request_count=row["csr_56"],
        )
        for key in [
            "gpu_input_ready_ns",
            "gpu_framework_begin_ns",
            "gpu_framework_end_ns",
            "gpu_publication_complete_ns",
        ]:
            result[key.replace("_ns", "_ms")] = (row[key] - arm_host) / 1e6
    else:
        result["logical_requests"] = row["csr_48"]
        result["request_count_scope"] = "Accepted logical HBM read descriptors"
        result["requested_bytes"] = row["csr_53"] if abi == 6 else row["csr_48"] * 64
    for index, name in enumerate(COUNTERS[5:], start=5):
        result["counter_" + name] = row[f"csr_{48 + index}"] if abi == 6 else None
    a, b = result["hbm_return_start_ms"], result["hbm_return_end_ms"]
    result["requested_payload_GBps"] = (
        result["requested_bytes"] / ((b - a) * 1e6) if a is not None and b > a else None
    )
    result["effective_inspection_GBps"] = row["input_bytes"] / (
        result["verdict_ms"] * 1e6
    )
    result["full_drain_scope"] = (
        "Host-observed successful drain, aligned to FPGA accepted arm; includes observation delay"
    )
    return result


def analyze(root, output):
    output.mkdir(parents=True, exist_ok=True)
    data = output / "data"
    data.mkdir(exist_ok=True)
    selected = json.loads((root / "hardware_selection.json").read_text())
    configs = [item for item in CONFIGURATIONS if str(item["variant"]) in selected]
    rows = []
    sources = []
    clocks = []
    for session in ["A", "B"]:
        for config in configs:
            for mode in ["main", "diagnostic"]:
                directory = root / "hardware" / session / config["key"] / mode
                status = json.loads((directory / "status.json").read_text())
                assert status["status"] == "passed"
                models, fits = clock_models(directory)
                clocks.extend(
                    dict(session=session, configuration=config["key"], mode=mode, **fit)
                    for fit in fits
                )
                for filename in [
                    "trials.jsonl",
                    "calibration.jsonl",
                    "manifest.json",
                    "configuration.json",
                    "collector_snapshot.py",
                ]:
                    path = directory / filename
                    sources.append(
                        dict(
                            path=str(path),
                            sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                        )
                    )
                for row in read_rows(directory / "trials.jsonl"):
                    if row["warmup"]:
                        continue
                    mapped, fit = models[row["case_id"], row["block"]]
                    derived = derive(row, mapped, fit)
                    derived["source"] = str(directory / "trials.jsonl")
                    rows.append(derived)
    statistics = []
    keys = list(
        dict.fromkeys(
            (row["configuration"], row["case_id"], row["mode"]) for row in rows
        )
    )
    metrics = [
        "verdict_ms",
        "host_observed_ms",
        "drain_observed_ms",
        "framework_ms",
        "logical_requests",
        "requested_bytes",
        "requested_payload_GBps",
        "effective_inspection_GBps",
        *["counter_" + key for key in COUNTERS[5:]],
    ]
    for config, case, mode in keys:
        samples = [
            row
            for row in rows
            if (row["configuration"], row["case_id"], row["mode"])
            == (config, case, mode)
        ]
        groups = {
            session: [row for row in samples if row["session"] == session]
            for session in ["A", "B"]
        }
        assert len(groups["A"]) == len(groups["B"]) == (200 if mode == "main" else 20)
        for session, subset in [("pooled", samples), *groups.items()]:
            values = {}
            for metric in metrics:
                series = [row[metric] for row in subset if row.get(metric) is not None]
                if series:
                    values[metric] = dict(
                        median=float(np.median(series)),
                        p05=float(np.percentile(series, 5)),
                        p95=float(np.percentile(series, 95)),
                        min=float(min(series)),
                        max=float(max(series)),
                    )
            statistics.append(
                dict(
                    configuration=config,
                    case_id=case,
                    mode=mode,
                    session=session,
                    input_bytes=samples[0]["input_bytes"],
                    count=len(subset),
                    metrics=values,
                )
            )
    primary = [row for row in rows if row["mode"] == "main"]
    assert len(primary) == len(configs) * 12 * 400
    dates = sorted({row["measurement_date"] for row in rows})
    summary = dict(
        configurations=configs,
        primary_measured_calls=len(primary),
        dates=dates,
        session_weighting="A and B each contribute 200/400 primary trials per configuration/workload; pooled empirical medians/p95 and separate sessions retained",
        missing_variants=[
            number for number in [14, 15, 16] if str(number) not in selected
        ],
        scope="Raw input already in HBM; accepted FPGA arm to FPGA verdict; no file/preload/compile/warmup",
    )
    for name, value in [
        ("trial_events.json", rows),
        ("statistics.json", statistics),
        ("clock_models.json", clocks),
        ("evidence_manifest.json", sources),
        ("summary.json", summary),
    ]:
        (data / name).write_text(json.dumps(value, indent=2) + "\n")
    fields = sorted(set().union(*(row.keys() for row in rows)))
    with (data / "trial_events.csv").open("w") as target:
        writer = csv.DictWriter(target, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    flat_statistics = []
    for item in statistics:
        for metric, quantiles in item["metrics"].items():
            flat_statistics.append(
                {key: value for key, value in item.items() if key != "metrics"}
                | dict(metric=metric, **quantiles)
            )
    with (data / "statistics.csv").open("w") as target:
        writer = csv.DictWriter(target, fieldnames=list(flat_statistics[0]))
        writer.writeheader()
        writer.writerows(flat_statistics)
    lookup = {
        (item["configuration"], item["case_id"], item["session"]): item
        for item in statistics
        if item["mode"] == "main"
    }
    speedups = []
    for (config, case, session), item in lookup.items():
        candidate = item["metrics"]["verdict_ms"]["median"]
        for baseline in ["OPT10", "GPU_P2P"]:
            numerator = lookup[baseline, case, session]["metrics"]["verdict_ms"][
                "median"
            ]
            speedups.append(
                dict(
                    configuration=config,
                    baseline=baseline,
                    case_id=case,
                    session=session,
                    numerator_median_ms=numerator,
                    denominator_median_ms=candidate,
                    speedup=numerator / candidate,
                )
            )
    with (data / "speedups.csv").open("w") as target:
        writer = csv.DictWriter(target, fieldnames=list(speedups[0]))
        writer.writeheader()
        writer.writerows(speedups)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    analyze(args.root.resolve(), args.output.resolve())
