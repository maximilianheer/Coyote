"""Review report provenance, exported numbers, figure files, and PDF structure.

Run after build_report.py. This complements visual inspection of the PDF; it
does not claim to detect every graphical layout problem automatically.
"""

import csv
import hashlib
import html
import json
import math
from pathlib import Path
import re
import subprocess
import zipfile

OUTPUT = Path(__file__).resolve().parent
REPO = OUTPUT.parents[4]
REPORTS = OUTPUT.parent.parent
PREVIOUS = OUTPUT.parent / "2026-10-21_focused_verdict_availability"
PDF = OUTPUT / "gpu_opt_xla_concretefunction_report.pdf"
GPU_IDS = {"OPT_7_GPU_HOST", "OPT_8_GPU_P2P"}
CHECKER_ID = "OPT_6_BRAM_FIFO1024_DSP_B2_RF72_RF288"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path):
    return json.loads(path.read_text())


def read_csv(path):
    with path.open() as source:
        return list(csv.DictReader(source))


def close(actual, expected):
    assert math.isclose(float(actual), float(expected), rel_tol=1e-10, abs_tol=1e-10)


def review():
    manifest = read_json(OUTPUT / "evidence_manifest.json")
    for relative, expected in manifest["sources"].items():
        assert sha(REPO / relative) == expected, relative
    for relative, expected in manifest["generated"].items():
        assert sha(OUTPUT / relative) == expected, relative
    for relative, expected in manifest["original_report_hashes"].items():
        assert sha(OUTPUT.parent / relative) == expected, relative

    events = read_json(OUTPUT / "data/trial_events.json")
    assert len(events) == 12000
    cells = {}
    for row in events:
        key = row["iteration"], row["case_id"]
        cells.setdefault(key, []).append(row)
        assert row["scope"] == "resident"
        assert not row["case_id"].startswith("smoke")
        if row["iteration"] in GPU_IDS:
            assert row["runtime_revision"] == "R06_xla_concrete"
            assert "/hardware_xla_concrete/" in row["source_evidence"]
        else:
            assert (
                "/final_benchmarks_gpu_preprocess_v2_20261021_030038/" in row[
                    "source_evidence"
                ]
            )
        assert row["csr_14"] <= row["csr_15"]
    assert len(cells) == 60
    assert all(len(samples) == 200 for samples in cells.values())

    old_statistics = {
        (row["iteration"], row["case_id"], row["metric"]): row
        for row in read_csv(PREVIOUS / "data/latency_statistics.csv")
    }
    statistics = read_csv(OUTPUT / "data/latency_statistics.csv")
    by_metric = {
        (row["iteration"], row["case_id"], row["metric"]): row for row in statistics
    }
    for key, row in by_metric.items():
        if row["iteration"] not in GPU_IDS:
            for metric in ["mean", "median", "p95"]:
                close(row[metric], old_statistics[key][metric])

    synthetic = read_csv(OUTPUT / "data/synthetic_summary.csv")
    assert len(synthetic) == 4
    gpu_host_wins = []
    fpga_wins = []
    for row in synthetic:
        case = row["case_id"]
        fpga = float(row["fpga_hls4ml_ms"])
        host = float(row["gpu_host_ms"])
        p2p = float(row["gpu_p2p_ms"])
        for iteration, value in [
            (CHECKER_ID, fpga),
            ("OPT_7_GPU_HOST", host),
            ("OPT_8_GPU_P2P", p2p),
        ]:
            close(value, by_metric[iteration, case, "verdict_available_ms"]["median"])
        close(row["fpga_speedup_vs_gpu_host"], host / fpga)
        close(row["fpga_speedup_vs_gpu_p2p"], p2p / fpga)
        assert fpga < p2p
        if host < fpga:
            gpu_host_wins.append(case)
        else:
            fpga_wins.append(case)
    assert fpga_wins == ["synthetic_16777216"]
    assert len(gpu_host_wins) == 3

    phase_totals = {}
    for row in read_csv(OUTPUT / "data/phase_means.csv"):
        key = row["iteration"], row["case_id"]
        phase_totals[key] = phase_totals.get(key, 0) + float(row["mean_ms"])
    for (iteration, case), total in phase_totals.items():
        close(total, by_metric[iteration, case, "verdict_available_ms"]["mean"])

    profiles = read_json(OUTPUT / "data/gpu_profiles.json")
    assert len(profiles) == 2
    for row in profiles:
        assert row["revision"] == "R06_xla_concrete"
        assert len(row["profiled_samples"]) == 20
        assert len(row["unprofiled_samples_ms"]) == 1000
        assert row["cpu"] == "0-7" and row["numa"] == "0"

    figures = read_json(OUTPUT / "data/figure_catalog.json")
    assert len(figures) == 16
    for figure in figures:
        for extension in ["png", "svg", "pdf"]:
            assert (OUTPUT / "figures" / (figure["name"] + "." + extension)).is_file()
        svg = (OUTPUT / "figures" / (figure["name"] + ".svg")).read_text()
        assert figure["title"] in html.unescape(svg), figure["name"]
    with zipfile.ZipFile(OUTPUT / "standalone_figures.zip") as bundle:
        assert bundle.testzip() is None
        assert len(bundle.namelist()) == 49
        for entry in bundle.namelist():
            local = (
                OUTPUT / entry
                if entry.startswith("figures/")
                else OUTPUT / "data" / entry
            )
            assert bundle.read(entry) == local.read_bytes(), entry

    text = subprocess.check_output(["pdftotext", "-layout", str(PDF), "-"], text=True)
    pages = [page for page in text.split("\f") if page.strip()]
    assert len(pages) == 13
    assert "22 October 2026" in pages[0] and "21 October 2026" in pages[0]
    assert "GPU_HOST is faster at all four" not in text
    assert "CPU0-7 / NUMA0" in text and "CPU64 / NUMA1" in text
    assert "approximately 137 ms" in text
    assert "Appendix A1" in pages[10]
    assert "Appendix A2" in pages[11]
    assert "Appendix A3" in pages[12]

    migration = read_json(REPORTS / "report_path_migration_2026-10-22.json")
    preserved = 0
    for old_relative, new_relative in migration["paths"].items():
        new = REPO / new_relative
        assert re.match(r"^\d{4}-\d{2}-\d{2}_", new.name)
        assert new.is_dir() and not (REPO / old_relative).exists()
        if new == OUTPUT:
            continue
        for relative, expected in migration["original_file_hashes"][
            old_relative
        ].items():
            path = new / relative
            if path.suffix in [
                ".pdf",
                ".png",
                ".svg",
                ".zip",
                ".csv",
            ] or relative.startswith("data/"):
                assert sha(path) == expected, path
                preserved += 1
    for archive in migration["archives"].values():
        assert sha(REPO / archive["new_path"]) == archive["sha256"]

    result = {
        "status": "passed",
        "review_date": "2026-10-22",
        "report_sha256": sha(PDF),
        "pages": len(pages),
        "figures": len(figures),
        "accepted_trials": len(events),
        "verified_sources": len(manifest["sources"]),
        "fpga_statistics_unchanged": True,
        "gpu_rows_r06_only": True,
        "gpu_host_faster_synthetic_cases": gpu_host_wins,
        "fpga_faster_than_gpu_host_synthetic_cases": fpga_wins,
        "fpga_faster_than_gpu_p2p_all_synthetic_cases": True,
        "additive_phase_means_checked": True,
        "diagnostics_kept_separate_from_board_measurements": True,
        "standalone_titles_and_archive_verified": True,
        "dated_folder_migration_verified": True,
        "historical_output_files_preserved": preserved,
        "visual_review": "Separate manual inspection is recorded in REVIEW.md.",
    }
    destination = OUTPUT / "data/review.json"
    destination.write_text(json.dumps(result, indent=2) + "\n")
    manifest["generated"]["data/review.json"] = sha(destination)
    review_notes = OUTPUT / "REVIEW.md"
    if review_notes.exists():
        manifest["generated"]["REVIEW.md"] = sha(review_notes)
    (OUTPUT / "evidence_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n"
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    review()
