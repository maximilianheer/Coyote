#!/usr/bin/env python3
"""Redraw existing report figures for the paper, without running benchmarks.

From the repository root:
    ml_baseline/.venv/bin/python paper/generate_benchmark_figures.py

Plot selection and timing conventions follow the October 22 R06 report's
build_report.py. Exported statistics and representative timelines are reused
verbatim; importing that generator would regenerate the archived report.
Only the presentation topology is cropped, using Ghostscript (no rasterization).
"""

import csv
import hashlib
import json
import os
from pathlib import Path
import subprocess

os.environ.setdefault("MPLCONFIGDIR", "/tmp/paper-benchmark-matplotlib")

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import numpy as np


PAPER = Path(__file__).resolve().parent
REPO = PAPER.parent
REPORTS = REPO / "hls4ml/optimize/reports/optimizations"
FULL_REPORT = REPORTS / "2026-10-22_gpu_opt_xla_concretefunction"
PRESENTATION_REPORT = (
    REPORTS / "2026-10-22_gpu_opt_xla_concretefunction_presentation_input_timing"
)
SLIDES = REPO / "[hls4ml talk] ML-Based Deep Bitstream Inspection for Serverless FPGAs.pdf"
OUTPUT = PAPER / "figures"
CASE = "synthetic_4194304"
FPGA = "OPT_6_BRAM_FIFO1024_DSP_B2_RF72_RF288"
GPU = "OPT_7_GPU_HOST"
COLORS = {
    "Reception": "#557da5",
    "FPGA reception": "#087e8b",
    "Pixel production": "#8cc4c3",
    "CNN interval": "#dda64c",
    "GPU-input wait": "#557da5",
    "Combined GPU call": "#dda64c",
    "Sync/publication": "#b483b5",
}
EVENTS = {
    "Entire input arrived": ("s", "#087e8b"),
    "Result available": ("o", "#111111"),
    "FPGA operation complete": ("x", "#ab4e69"),
    "Host observes completion": ("D", "#707986"),
}


def read_csv(path):
    with path.open(newline="") as source:
        return list(csv.DictReader(source))


def save_figure(fig, name):
    fig.savefig(OUTPUT / f"{name}.pdf", bbox_inches="tight")
    fig.savefig(OUTPUT / f"{name}.png", bbox_inches="tight", dpi=220)
    plt.close(fig)


def style_axis(ax, grid_axis="x"):
    ax.spines[["top", "right"]].set_visible(False)
    ax.set_axisbelow(True)
    ax.grid(axis=grid_axis, color="#e8e8e8", linewidth=0.6)


def real_latency(statistics, trials):
    rows = [
        row for row in statistics
        if row["iteration"] in (FPGA, GPU)
        and row["case_id"].startswith("real_")
        and row["metric"] == "verdict_available_ms"
    ]
    cases = sorted({row["case_id"] for row in rows}, key=lambda case: int(case[5:]))
    assert len(cases) == 8
    index = {(row["iteration"], row["case_id"]): row for row in rows}

    # Check medians and p95 against the accepted per-call export, rather than
    # treating printed labels in the slides as numerical source data.
    for row in rows:
        matching = [
            trial for trial in trials
            if trial["iteration"] == row["iteration"]
            and trial["case_id"] == row["case_id"]
            and trial["scope"] == "resident"
        ]
        assert len(matching) == 200
        values = [float(trial["verdict_available_ms"]) for trial in matching]
        assert np.isclose(np.median(values), float(row["median"]), atol=1e-10, rtol=0)
        assert np.isclose(np.percentile(values, 95), float(row["p95"]), atol=1e-10, rtol=0)

    fig, ax = plt.subplots(figsize=(5.45, 2.75), layout="constrained")
    x = np.arange(len(cases))
    width = 0.36
    for offset, iteration, label, color in [
        (-width / 2, FPGA, "FPGA_HLS4ML", "#2c944e"),
        (width / 2, GPU, "GPU_HOST", "#cf6a19"),
    ]:
        medians = [float(index[iteration, case]["median"]) for case in cases]
        p95 = [float(index[iteration, case]["p95"]) for case in cases]
        bars = ax.bar(x + offset, medians, width, color=color, label=label)
        ax.scatter(x + offset, p95, marker="_", color="black", s=26, linewidths=0.9)
        for bar, value, tail in zip(bars, medians, p95):
            ax.text(
                bar.get_x() + width / 2, max(value, tail) + 0.055,
                f"{value:.3f}", ha="center", va="bottom", rotation=90, fontsize=7,
            )
    ax.set_xticks(x, [
        f"R{number}\n{int(case[5:]) / 2**20:.2f}" for number, case in enumerate(cases, 1)
    ])
    ax.set(
        title="Real bitstreams: verdict availability",
        xlabel="Bitstream / input size (MiB)",
        ylabel="Invocation to FPGA verdict (ms)",
        ylim=(0, 5.35),
    )
    handles, labels = ax.get_legend_handles_labels()
    handles.append(Line2D([], [], marker="_", linestyle="", color="black"))
    ax.legend(handles, labels + ["p95"], loc="upper left", ncol=3, fontsize=7)
    style_axis(ax, "y")
    save_figure(fig, "benchmark_real_latency")
    return rows


def streaming_overlap(timelines):
    rows = [
        row for row in timelines
        if row["figure"] == "09" and row["case_id"] == CASE
        and row["label"] in ("Buffering", "Streaming")
    ]
    assert len(rows) == 6
    assert {(row["label"], row["trial"]) for row in rows} == {
        ("Buffering", 177), ("Streaming", 97)
    }
    fig, ax = plt.subplots(figsize=(5.45, 2.65), layout="constrained")
    positions = [0, 1, 2, 4, 5, 6]
    for position, row in zip(positions, rows):
        ax.barh(
            position, row["end_ms"] - row["start_ms"], left=row["start_ms"],
            color=COLORS[row["activity"]], height=0.62,
        )
        if row["activity"] in ("Reception", "CNN interval"):
            reception = row["activity"] == "Reception"
            ax.scatter(
                row["end_ms"], position, marker="s" if reception else "o",
                color="#087e8b" if reception else "#111111", s=17, zorder=3,
            )
    stages = {"Buffering": "Before", "Streaming": "After"}
    ax.set_yticks(
        positions,
        [f'{stages[row["label"]]} · {row["activity"]}' for row in rows],
    )
    ax.set(
        title="Streaming optimization · 4 MiB",
        xlabel="Time from FPGA arm (ms)", xlim=(0, 1.5), ylim=(6.7, -0.7),
    )
    handles = [
        Line2D([], [], marker="s", linestyle="", color="#087e8b", label="Input received"),
        Line2D([], [], marker="o", linestyle="", color="#111111", label="Verdict available"),
    ]
    fig.legend(handles=handles, loc="outside lower center", ncol=2, fontsize=7)
    style_axis(ax)
    save_figure(fig, "benchmark_streaming_4mib")
    return rows


def execution_overlap(timelines):
    rows = [
        row for row in timelines
        if row["figure"] == "05" and row["case_id"] == CASE
        and row["iteration"] in (FPGA, GPU)
    ]
    assert {(row["iteration"], row["trial"]) for row in rows} == {(FPGA, 95), (GPU, 1382)}
    # Stack the two existing panels to keep lane labels readable at ACM column
    # width. Both panels retain the same invocation origin and horizontal scale.
    fig, axes = plt.subplots(2, 1, figsize=(5.45, 4.7), layout="constrained", sharex=True)
    fig.suptitle("Measured execution overlap · 4 MiB", fontsize=9)
    for ax, iteration, label, panel in zip(
        axes, (FPGA, GPU), ("FPGA_HLS4ML", "GPU_HOST"), ("a", "b")
    ):
        selected = [row for row in rows if row["iteration"] == iteration]
        verdict = next(row["start_ms"] for row in selected if row["activity"] == "Result available")
        for position, row in enumerate(selected):
            start, stop = row["start_ms"], row["end_ms"]
            assert stop >= start
            if row["kind"] == "interval":
                ax.barh(position, stop - start, left=start, height=0.6, color=COLORS[row["activity"]])
                endpoints = (start, stop)
            else:
                marker, color = EVENTS[row["activity"]]
                ax.scatter(start, position, marker=marker, color=color, s=19, zorder=4)
                endpoints = (start,)
            # These marks are clock-alignment bounds, not statistical error bars.
            uncertainty = row["uncertainty_ms"]
            if uncertainty:
                for endpoint in endpoints:
                    ax.plot(
                        [endpoint - uncertainty, endpoint + uncertainty],
                        [position, position], color="black", linewidth=1,
                    )
        ax.axvline(verdict, color="#555555", linestyle=":", linewidth=0.7)
        ax.set_yticks(range(len(selected)), [row["activity"] for row in selected])
        ax.set(
            title=f"({panel}) {label} · verdict {verdict:.3f} ms",
            xlim=(0, 1.2), ylim=(len(selected) - 0.3, -0.7),
        )
        style_axis(ax)
    axes[-1].set_xlabel("Time since host invocation (ms)")
    save_figure(fig, "benchmark_execution_4mib")
    return rows


def extract_topology():
    # Presentation PDF page 18 (slide numbered 22), in PDF points from the
    # bottom-left. The crop retains the input-path legend and PCIe link labels.
    left, bottom, right, top = (104, 60, 830, 466)
    subprocess.run(
        [
            "gs", "-q", "-dSAFER", "-dBATCH", "-dNOPAUSE", "-sDEVICE=pdfwrite",
            "-dPreserveAnnots=false", "-dPreserveMarkedContent=false",
            "-dFirstPage=18", "-dLastPage=18", "-dFIXEDMEDIA",
            f"-dDEVICEWIDTHPOINTS={right - left}",
            f"-dDEVICEHEIGHTPOINTS={top - bottom}",
            f"-sOutputFile={OUTPUT / 'benchmark_topology.pdf'}",
            "-c", f"<</PageOffset [{-left} {-bottom}]>> setpagedevice",
            "-f", str(SLIDES),
        ],
        check=True, capture_output=True, text=True,
    )
    return {"pdf_page": 18, "displayed_slide": 22, "crop_points": [left, bottom, right, top]}


def main():
    OUTPUT.mkdir(exist_ok=True)
    plt.rcParams.update({
        "font.family": "DejaVu Sans", "font.size": 8,
        "axes.titlesize": 9, "axes.labelsize": 8,
        "xtick.labelsize": 7, "ytick.labelsize": 7,
        "pdf.fonttype": 42, "ps.fonttype": 42,
    })
    statistics_path = PRESENTATION_REPORT / "data/latency_statistics.csv"
    trials_path = PRESENTATION_REPORT / "data/trial_events.csv"
    timelines_path = FULL_REPORT / "data/timelines.json"
    resources_path = FULL_REPORT / "data/resources.json"
    statistics = read_csv(statistics_path)
    timelines = json.loads(timelines_path.read_text())
    selected_statistics = real_latency(statistics, read_csv(trials_path))
    selected_timelines = streaming_overlap(timelines) + execution_overlap(timelines)
    crop = extract_topology()
    resources = json.loads(resources_path.read_text())["Resource-optimized streaming"]
    assert resources["wrapper"]["LUT"] == 61141
    assert resources["wrapper"]["BRAM_tiles"] == 54.5
    assert resources["wrapper"]["DSP"] == 648
    assert resources["wrapper"]["URAM"] == 0

    sources = [statistics_path, trials_path, timelines_path, resources_path, SLIDES]
    manifest = {
        "measurement_date": "2026-10-21",
        "scope": "Existing R06 GPU_HOST and OPT FPGA results; no new measurements.",
        "sources": {
            str(path.relative_to(REPO)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sources
        },
        "adapted_plotting_code": str((FULL_REPORT / "build_report.py").relative_to(REPO)),
        "topology": crop,
        "timeline_origins": {
            "05": "Host invocation; includes host-to-FPGA clock-alignment bounds.",
            "09": "FPGA arm; durations use the calibrated FPGA clock period.",
        },
        "real_latency_statistics": selected_statistics,
        "representative_timelines": selected_timelines,
        "resource_counts": resources["wrapper"],
        "resource_percentages": resources["wrapper_percent"],
    }
    (OUTPUT / "benchmark_sources.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print("Generated four paper figures; verified all 16 real-input median/p95 pairs.")


if __name__ == "__main__":
    main()
