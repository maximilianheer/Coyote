"""Independent reconciliation of CPU figures, trial counts, gates and hashes."""

import argparse
import csv
import json
from pathlib import Path
import subprocess
import zipfile

import numpy as np

from common import save, sha


def review(root, output):
    data = output / "data"
    stats = json.loads((data / "statistics.json").read_text())
    rows = json.loads((data / "trial_events.json").read_text())
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
    grouped = {}
    unique = set()
    for row in rows:
        key = (
            row["model"],
            row["case_id"],
            row["mode"],
            row["cache_scope"],
            row["session"],
        )
        identity = key + (row["trial"],)
        assert identity not in unique
        unique.add(identity)
        assert not row["warmup"] and row["trial"] in range(20, 220)
        assert row["elapsed_ns"] > 0 and row["process_cpu_ns"] > 0
        assert np.isfinite(row["score"])
        assert row["elapsed_ms"] == row["elapsed_ns"] / 1e6
        grouped.setdefault(key, []).append(row)
    assert len(rows) == 33600
    assert sum(row["mode"] == "total" for row in rows) == 19200
    for key, item in lookup.items():
        samples = (
            grouped[key]
            if key[-1] != "pooled"
            else grouped[key[:-1] + ("A",)] + grouped[key[:-1] + ("B",)]
        )
        assert len(samples) == item["count"] == (400 if key[-1] == "pooled" else 200)
        values = [row["elapsed_ms"] for row in samples]
        assert np.isclose(item["median_ms"], np.median(values), rtol=1e-12)
        assert np.isclose(item["p95_ms"], np.percentile(values, 95), rtol=1e-12)
    for query in json.loads((data / "figure_values.json").read_text()):
        key = (
            query["model"],
            query["case_id"],
            query["mode"],
            query["cache"],
            query["session"],
        )
        assert lookup[key][query["metric"]] == query["value"]
    for item in json.loads((data / "evidence_manifest.json").read_text()):
        assert sha(item["path"]) == item["sha256"]
    for name, expected in json.loads(
        (data / "model_identities.json").read_text()
    ).items():
        assert sha(name) == expected
    for name, expected in json.loads(
        (root / "software/source_identity.json").read_text()
    ).items():
        archived = root / "software" / Path(name).name
        assert sha(archived) == expected, archived
    for model in ["FP32", "QKERAS_W8A8"]:
        result = json.loads((root / f"preflight/{model}/result.json").read_text())
        assert (
            result["status"] == "passed"
            and result["calls"] == 26
            and result["GPU_devices"] == []
        )
        assert (
            result["cache_probe_medians"]["cold"]
            > 2 * result["cache_probe_medians"]["warm"]
        )
    counters = json.loads((root / "preflight/cache_counters.json").read_text())
    cold = np.median([row["cache_misses"] for row in counters if row["cold"]])
    warm = np.median([row["cache_misses"] for row in counters if not row["cold"]])
    assert cold > 10000 and cold > 100 * max(warm, 1)
    for mapping_path in (root / "measurements").glob("*/*/arena_mapping.json"):
        mapping = json.loads(mapping_path.read_text())
        assert mapping["address"] % 2097152 == 0 and mapping["capacity"] == 134217728
        env = json.loads((mapping_path.parent / "environment_after.json").read_text())
        line = next(
            line
            for line in env["numa_maps"].splitlines()
            if line.startswith(f"{mapping['address']:x} ")
        )
        assert "bind:2" in line and "N2=" in line
        for node in [0, 1, 3]:
            assert f"N{node}=" not in line
    catalog = json.loads((data / "figure_catalog.json").read_text())
    for item in catalog:
        for extension in ["png", "svg", "pdf"]:
            path = output / "figures" / (item["name"] + "." + extension)
            assert path.stat().st_size > 1000
        svg = (output / "figures" / (item["name"] + ".svg")).read_text()
        assert "<text" in svg
    with zipfile.ZipFile(output / "standalone_figures.zip") as archive:
        assert len(archive.namelist()) == len(catalog) * 3
        assert archive.testzip() is None
    pdf = output / "cpu_dram_preprocess_inference_report.pdf"
    text = subprocess.check_output(["pdftotext", str(pdf), "-"], text=True)
    summary = json.loads((data / "summary.json").read_text())
    variation = f"{100 * summary['maximum_absolute_primary_session_change']:.1f}%"
    for phrase in [
        "FP32",
        "QKeras",
        variation,
        "diagnostic_only",
        "native INT8",
        "different hosts",
    ]:
        assert phrase in text, phrase
    save(
        data / "review.json",
        dict(
            status="passed",
            measured_calls=33600,
            primary_calls=19200,
            samples_per_cell=400,
            samples_per_session=200,
            models=2,
            rounds=2,
            native_int8_disposition="diagnostic only, not included in primary timing",
            figures=len(catalog),
            cold_gather_median_cache_misses=float(cold),
            warm_gather_median_cache_misses=float(warm),
            visual_review="Required separately; numerical checks do not establish layout quality",
        ),
    )
    print("Numerical/evidence review passed", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    review(args.root.resolve(), args.output.resolve())
