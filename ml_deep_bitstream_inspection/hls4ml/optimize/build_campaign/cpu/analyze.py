"""Reconcile all CPU trials, preserve sessions and export numerical tables."""

import argparse
import csv
import hashlib
import json
from pathlib import Path

import numpy as np

from common import cases, save, sha


def analyze(root, output):
    data = output / "data"
    data.mkdir(parents=True, exist_ok=True)
    rows = []
    evidence = []
    groups = {}
    for session in ["A", "B"]:
        for model in ["FP32", "QKERAS_W8A8"]:
            directory = root / "measurements" / session / model
            status = json.loads((directory / "status.json").read_text())
            assert status["status"] == "passed"
            runtime = json.loads((directory / "runtime.json").read_text())
            assert runtime["intra_threads"] == runtime["inter_threads"] == 1
            assert runtime["visible_gpus"] == []
            for path in directory.iterdir():
                if path.is_file():
                    evidence.append(dict(path=str(path), sha256=sha(path)))
            for case in json.loads((directory / "manifest.json").read_text()):
                assert sha(case["path"]) == case["sha256"]
            local_counts = {}
            for line in (directory / "trials.jsonl").read_text().splitlines():
                row = json.loads(line)
                assert (
                    row["validation"] == "passed"
                    and row["session"] == session
                    and row["model"] == model
                )
                key = (
                    row["model"],
                    row["case_id"],
                    row["mode"],
                    row["cache_scope"],
                    session,
                )
                totals = local_counts.setdefault(key, [0, 0])
                totals[0 if row["warmup"] else 1] += 1
                if row["mode"] != "preprocessing_only":
                    assert np.isclose(
                        row["score"], row["expected_score"], rtol=1e-4, atol=1e-4
                    )
                    assert row["verdict"] == int(row["expected_score"] >= 0)
                if row["warmup"]:
                    continue
                row["elapsed_ms"] = row["elapsed_ns"] / 1e6
                row["cpu_time_ms"] = row["process_cpu_ns"] / 1e6
                row["source"] = str(directory / "trials.jsonl")
                rows.append(row)
                groups.setdefault(key, []).append(row)
            assert all(count == [20, 200] for count in local_counts.values())
            assert len(local_counts) == (48 if model == "FP32" else 36)
            for path in directory.glob("*environment*.json"):
                item = json.loads(path.read_text())
                for entry in [item] if "affinity" in item else item.values():
                    assert entry["affinity"] == [2]
                    assert all(
                        value == "2" for value in entry["thread_affinities"].values()
                    )
    stats = []
    keys = list(dict.fromkeys(key[:4] for key in groups))
    for model, case, mode, scope in keys:
        a = groups[model, case, mode, scope, "A"]
        b = groups[model, case, mode, scope, "B"]
        assert len(a) == len(b) == 200
        for session, subset in [("A", a), ("B", b), ("pooled", a + b)]:
            series = [row["elapsed_ms"] for row in subset]
            stats.append(
                dict(
                    model=model,
                    case_id=case,
                    mode=mode,
                    cache_scope=scope,
                    session=session,
                    count=len(subset),
                    input_bytes=subset[0]["input_bytes"],
                    median_ms=float(np.median(series)),
                    p05_ms=float(np.percentile(series, 5)),
                    p95_ms=float(np.percentile(series, 95)),
                    min_ms=min(series),
                    max_ms=max(series),
                    median_cpu_ms=float(
                        np.median([row["cpu_time_ms"] for row in subset])
                    ),
                )
            )
    total = [row for row in rows if row["mode"] == "total"]
    assert len(total) == 19200 and len(rows) == 33600
    lookup = {
        (
            item["model"],
            item["case_id"],
            item["mode"],
            item["cache_scope"],
            item["session"],
        ): item
        for item in stats
    }
    changes = []
    for key, item in lookup.items():
        if key[-1] == "A":
            other = lookup[key[:-1] + ("B",)]
            changes.append(
                dict(
                    model=key[0],
                    case_id=key[1],
                    mode=key[2],
                    cache_scope=key[3],
                    round_a_ms=item["median_ms"],
                    round_b_ms=other["median_ms"],
                    fractional_change=other["median_ms"] / item["median_ms"] - 1,
                )
            )
    maximum_change = max(
        abs(item["fractional_change"])
        for item in changes
        if item["mode"] == "total" and item["cache_scope"] == "input_cold"
    )
    for name, value in [
        ("statistics.json", stats),
        ("trial_events.json", rows),
        ("evidence_manifest.json", evidence),
        ("session_changes.json", changes),
        (
            "summary.json",
            dict(
                measured_calls=len(rows),
                primary_calls=len(total),
                models=["FP32", "QKERAS_W8A8"],
                maximum_absolute_primary_session_change=maximum_change,
                sessions=["A", "B"],
                measurement_dates=sorted(
                    {
                        __import__("datetime")
                        .datetime.fromtimestamp(row["captured_at"])
                        .date()
                        .isoformat()
                        for row in rows
                    }
                ),
                scope="One logical CPU, local DRAM raw input to materialized verdict; model/code warmed",
            ),
        ),
    ]:
        save(data / name, value)
    for name, values in [("statistics.csv", stats), ("trial_events.csv", rows)]:
        with (data / name).open("w") as file:
            writer = csv.DictWriter(file, fieldnames=list(values[0]))
            writer.writeheader()
            writer.writerows(values)
    print(
        "Validated",
        len(rows),
        "measured CPU calls;",
        len(total),
        "primary calls",
        flush=True,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    analyze(args.root.resolve(), args.output.resolve())
