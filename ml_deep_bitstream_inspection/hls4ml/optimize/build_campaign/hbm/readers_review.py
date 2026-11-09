#!/usr/bin/env python3
"""Reconcile plots/tables against immutable, session-preserving raw evidence."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile

import numpy as np

from readers_spec import CONFIGURATIONS, expected_counters, validate


def read(path):
    return json.loads(path.read_text())


def review(root, output):
    data = output / "data"
    summary = read(data / "summary.json")
    configs = summary["configurations"]
    rows = read(data / "trial_events.json")
    primary = [row for row in rows if row["mode"] == "main"]
    assert len(primary) == len(configs) * 12 * 400
    statistics = read(data / "statistics.json")
    lookup = {
        (item["configuration"], item["case_id"], item["session"], item["mode"]): item
        for item in statistics
    }
    groups = {}
    verified_inputs = set()
    counter_cache = {}
    for row in rows:
        groups.setdefault(
            (row["configuration"], row["case_id"], row["session"], row["mode"]), []
        ).append(row)
        assert 3.99 < row["ns_per_tick"] < 4.01
        assert row["verdict_ms"] > 0
        assert (
            row["hbm_return_end_ms"] is None
            or row["hbm_return_end_ms"] <= row["verdict_ms"]
        )
    for config in configs:
        for session in ["A", "B"]:
            admission = root / "hardware" / session / config["key"] / "admission"
            status = read(admission / "status.json")
            assert status["status"] == "passed" and status["calls"] == 520
            for mode, warmups, count in [
                ("admission", 0, 20),
                ("main", 20, 200),
                ("pilot", 2, 10),
            ]:
                directory = admission.parent / mode
                manifest = {
                    case["id"]: case for case in read(directory / "manifest.json")
                }
                assert len(manifest) == (26 if mode == "admission" else 12)
                counters = {}
                for case, item in manifest.items():
                    identity = (item["path"], item["sha256"])
                    if identity not in verified_inputs:
                        path = Path(item["path"])
                        assert path.stat().st_size == item["bytes"]
                        assert (
                            hashlib.sha256(path.read_bytes()).hexdigest()
                            == item["sha256"]
                        )
                        verified_inputs.add(identity)
                    counter_key = (config["variant"], item["bytes"], config["setting"])
                    if counter_key not in counter_cache:
                        counter_cache[counter_key] = expected_counters(*counter_key)
                    counters[case] = counter_cache[counter_key]
                counts = {case: [0, 0] for case in manifest}
                for line in (directory / "trials.jsonl").read_text().splitlines():
                    row = json.loads(line)
                    assert (
                        row["session"] == session
                        and row["configuration"] == config["key"]
                    )
                    assert row["setting"] == config["setting"]
                    validate(
                        row,
                        config,
                        counters[row["case_id"]],
                        manifest[row["case_id"]],
                        row["fp32_reference"],
                    )
                    counts[row["case_id"]][0 if row["warmup"] else 1] += 1
                assert all(totals == [warmups, count] for totals in counts.values())
    for key, item in lookup.items():
        config, case, session, mode = key
        if session == "pooled":
            samples = groups[config, case, "A", mode] + groups[config, case, "B", mode]
            assert len(groups[config, case, "A", mode]) == len(
                groups[config, case, "B", mode]
            )
        else:
            samples = groups[key]
        assert len(samples) == item["count"]
        values = [row["verdict_ms"] for row in samples]
        assert np.isclose(
            np.median(values), item["metrics"]["verdict_ms"]["median"], rtol=1e-12
        )
        assert np.isclose(
            np.percentile(values, 95), item["metrics"]["verdict_ms"]["p95"], rtol=1e-12
        )
    for query in read(data / "figure_values.json"):
        item = lookup[
            query["configuration"], query["case_id"], query["session"], query["mode"]
        ]
        expected = item["metrics"].get(query["metric"], {}).get(query["quantile"])
        assert query["value"] == expected
    with (data / "speedups.csv").open() as source:
        for item in csv.DictReader(source):
            assert np.isclose(
                float(item["speedup"]),
                float(item["numerator_median_ms"])
                / float(item["denominator_median_ms"]),
                rtol=1e-12,
            )
    for evidence in read(data / "evidence_manifest.json"):
        assert (
            hashlib.sha256(Path(evidence["path"]).read_bytes()).hexdigest()
            == evidence["sha256"]
        )
    catalog = read(data / "figure_catalog.json")
    for item in catalog:
        for extension in ["png", "svg", "pdf"]:
            path = output / "figures" / f"{item['id']}.{extension}"
            assert path.stat().st_size > 1000
        svg = (output / "figures" / (item["id"] + ".svg")).read_text()
        assert "<text" in svg, item["id"]
    with zipfile.ZipFile(output / "standalone_figures.zip") as archive:
        assert len(archive.namelist()) == len(catalog) * 3 and archive.testzip() is None
    pdf = output / "hbm_reader_optimizations_report.pdf"
    text = subprocess.check_output(["pdftotext", str(pdf), "-"], text=True)
    for needed in ["GPU_P2P", "HBM", "Round", "Validation", "ConcreteFunction"]:
        assert needed in text, needed
    session_changes = []
    for key, item in lookup.items():
        config, case, session, mode = key
        if mode == "main" and session == "A":
            a = item["metrics"]["verdict_ms"]["median"]
            b = lookup[config, case, "B", mode]["metrics"]["verdict_ms"]["median"]
            session_changes.append(
                dict(configuration=config, case_id=case, fractional_change=b / a - 1)
            )
    result = dict(
        status="passed",
        configurations=len(configs),
        primary_measured_calls=len(primary),
        measured_calls_per_cell=400,
        calls_per_session=200,
        figures=len(catalog),
        standalone_files=len(catalog) * 3,
        maximum_absolute_session_change=max(
            abs(item["fractional_change"]) for item in session_changes
        ),
        session_variation_disposition="Retained and reported; not a selective rerun gate",
        visual_review="Required separately; numerical checks do not assert layout quality",
    )
    (data / "session_changes.json").write_text(json.dumps(session_changes, indent=2))
    (data / "review.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    review(args.root.resolve(), args.output.resolve())
