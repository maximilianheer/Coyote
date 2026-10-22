#!/usr/bin/env python3
"""Focused hls4ml-checker report; adapted from the full-report generator. No hardware access.
Run from the repository: ml_baseline/.venv/bin/python <this script>
"""

import csv
import hashlib
import json
import sys
import math
import os
import zipfile
import textwrap
from timing import model_for, derive, phase_partition
from pathlib import Path
from functools import lru_cache
from xml.sax.saxutils import escape
import numpy as np

os.environ.setdefault("MPLCONFIGDIR", "/tmp/final_benchmark_report_mpl")
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

try:
    import reportlab
except ImportError:
    sys.path.append("/usr/lib/python3/dist-packages")
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Image,
    Table,
    TableStyle,
    PageBreak,
    KeepTogether,
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4

OUT = Path(__file__).resolve().parent
REPO = OUT.parents[4]
FPGA_ROOT = (
    REPO / "hls4ml/optimize/runs/final_benchmarks_gpu_preprocess_v2_20261021_030038"
)
INVESTIGATION = REPO / "hls4ml/optimize/runs/gpu_runtime_investigation_20261021_030038"
ROOT = INVESTIGATION / "hardware_xla_concrete"
DIAGNOSTIC_ROOT = INVESTIGATION / "experiments/R06_xla_concrete"
GPU_CAMPAIGN = json.loads((ROOT / "campaign.json").read_text())
FPGA_CAMPAIGN = json.loads((FPGA_ROOT / "campaign.json").read_text())
assert GPU_CAMPAIGN["runtime_revision"] == "experimental_xla_concrete"
assert FPGA_CAMPAIGN["runtime_revision"] == "gpu_preprocess_v2"
# Historical report_eligible=False protected the old preprocessing-v2 reports.
# The user explicitly selected R06 for this new report; archived metadata stays intact.
REPORT_SELECTION = {
    "gpu_revision": "R06_xla_concrete",
    "authorization": (
        "User requested a new report using R06, labeled gpu_opt_xla_concretefunction."
    ),
    "archived_report_eligible": GPU_CAMPAIGN["report_eligible"],
    "fpga_source": str(FPGA_ROOT),
    "gpu_source": str(ROOT),
    "diagnostic_source": str(DIAGNOSTIC_ROOT),
}
sys.path.insert(0, str(ROOT / "tooling"))
from board_benchmark import clock_model

FIG = OUT / "figures"
FIG.mkdir(exist_ok=True)
DATA = OUT / "data"
DATA.mkdir(exist_ok=True)
FPGA_SUMMARY = json.loads((FPGA_ROOT / "summary.json").read_text())
GPU_SUMMARY = json.loads((ROOT / "summary.json").read_text())
assert FPGA_SUMMARY["status"] == GPU_SUMMARY["status"] == "passed"
assert GPU_SUMMARY["runtime_revision"] == "experimental_xla_concrete"
S = {
    "status": "passed",
    "resources": FPGA_SUMMARY["resources"],
    "rows": (
        [
            row
            for row in FPGA_SUMMARY["rows"]
            if row["iteration"]
            in (
                "OPT_0_NONSTREAMING",
                "OPT_1_STREAMING",
                "OPT_6_BRAM_FIFO1024_DSP_B2_RF72_RF288",
            )
        ]
        + [
            row
            for row in GPU_SUMMARY["rows"]
            if row["iteration"] in ("OPT_7_GPU_HOST", "OPT_8_GPU_P2P")
        ]
    ),
}
IDS = [
    "OPT_0_NONSTREAMING",
    "OPT_1_STREAMING",
    "OPT_6_BRAM_FIFO1024_DSP_B2_RF72_RF288",
    "OPT_7_GPU_HOST",
    "OPT_8_GPU_P2P",
]
LABELS = [
    "Buffering",
    "Streaming",
    "Resource-optimized streaming",
    "GPU_HOST",
    "GPU_P2P",
]
N = dict(zip(IDS, LABELS))
C = dict(zip(IDS, ["#7b8494", "#087e8b", "#2c944e", "#cf6a19", "#7752a5"]))
SHORT = dict(N)
SHORT[IDS[2]] = "Resource-optimized\nstreaming"
SIZES = [4194304, 16777216, 67108864, 134217664]
SYN = [f"synthetic_{x}" for x in SIZES]
CASES = sorted(
    {
        r["case_id"]: r["input_bytes"]
        for r in S["rows"]
        if not r["case_id"].startswith("smoke")
    }.items(),
    key=lambda x: (x[1], x[0]),
)
CASE = dict(CASES)
REPS = [SYN[0], SYN[-1]]
ROWS = {(r["iteration"], r["case_id"], r["scope"]): r for r in S["rows"]}
plt.rcParams.update(
    {
        "font.family": "DejaVu Sans",
        "font.size": 11,
        "axes.titlesize": 12,
        "axes.labelsize": 11,
        "legend.fontsize": 10,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "figure.dpi": 120,
        "savefig.dpi": 210,
    }
)
VERIFIED = {}
STATS = []
SEGMENTS = []
TIMELINES = []
FIGURES = []
EVENTS = {}
TRIAL_EXPORT = []
VALIDATION = {}


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def savejson(p, x):
    p.write_text(json.dumps(x, indent=2) + "\n")


def warm(x):
    return str(x).lower() in ["true", "1"]


def pct(a, p):
    return float(np.percentile(a, p))


def stat(a):
    return dict(mean=float(np.mean(a)), median=float(np.median(a)), p95=pct(a, 95))


@lru_cache(None)
def source(path):
    p = Path(path).parent
    gpu = (p / "observations.jsonl").exists()
    if gpu:
        raw = [
            json.loads(x) for x in (p / "observations.jsonl").read_text().splitlines()
        ]
        derived = json.loads((p / "derived.json").read_text())
    else:
        raw = list(csv.DictReader((p / "observations.csv").open()))
        derived = list(csv.DictReader((p / "derived.csv").open()))
    return raw, derived


@lru_cache(None)
def trials(i, c, scope):
    row = ROWS[i, c, scope]
    a, b = source(row["evidence"])

    def select(xs):
        return [
            r
            for r in xs
            if r["case_id"] == c and r["scope"] == scope and not warm(r["warmup"])
        ]

    aa, bb = select(a), select(b)
    assert len(aa) == len(bb) == 200
    for metric, expected in row.items():
        if isinstance(expected, dict):
            vals = [float(r[metric]) for r in bb]
            for k, q in [("median", 50), ("p95", 95)]:
                assert math.isclose(
                    pct(vals, q), expected[k], rel_tol=1e-8, abs_tol=1e-8
                ), (i, c, scope, metric, k)
    return aa, bb


def values(i, c, scope, key):
    rows = EVENTS[i, c] if key == "verdict_available_ms" else trials(i, c, scope)[1]
    return np.array([float(x[key]) for x in rows])


def med(i, c, scope, key=None):
    return float(
        np.median(
            values(
                i,
                c,
                scope,
                key or ("file_e2e_ms" if scope == "file" else "verdict_available_ms"),
            )
        )
    )


def case_label(c):
    n = CASE[c]
    if c == SYN[-1]:
        return "128 MiB − 64 B"
    if c.startswith("synthetic"):
        return f"{n/2**20:g} MiB"
    return f"{n:,} B"


FIGURE_TITLES = {
    "01_synthetic_latency": "Synthetic inputs: verdict availability inside the FPGA",
    "02_synthetic_speedup": (
        "Synthetic inputs: FPGA_HLS4ML speedup to verdict availability"
    ),
    "03_benchmark_setup": "Benchmark setup: input and classification-result paths",
    "03_setup_FPGA_HLS4ML": "FPGA_HLS4ML: streaming preprocessing and inference",
    "03_setup_GPU_HOST": "GPU_HOST: independent input copies and host result relay",
    "03_setup_GPU_P2P": "GPU_P2P: FPGA forwarding and autonomous result polling",
    "03_setup_connectivity": "Benchmark machine: host RAM, PCIe, FPGA and GPU",
    "04_invocation_breakdown": (
        "Verdict availability and full-input arrival at the FPGA"
    ),
    "05_execution_overlap": "Measured execution overlap and FPGA result availability",
    "06_gpu_diagnostics": "R06: combined preprocessing and inference on the GPU",
    "07_checker_optimization": "Checker optimization: latency to verdict availability",
    "08_fpga_resources": "Checker optimization: FPGA wrapper resource utilization",
    "09_streaming_timelines": (
        "How streaming overlaps reception, preprocessing and inference"
    ),
    "A1_real_latency": "Real bitstreams: verdict availability inside the FPGA",
    "A2_real_speedup_bars": (
        "Real bitstreams: FPGA_HLS4ML speedup to verdict availability"
    ),
    "A3_real_latency_scatter": (
        "Real bitstreams: verdict-availability latency versus input size"
    ),
}
FIGURE_NOTES = {
    "01_synthetic_latency": (
        "Prepared host input → FPGA result acceptance. Bars = median; ticks = p95. 200"
        " calls per input/variant."
    ),
    "02_synthetic_speedup": (
        "Speedup = GPU median / FPGA_HLS4ML median; above 1× favors FPGA_HLS4ML."
        " Endpoint: FPGA result acceptance."
    ),
    "A1_real_latency": (
        "Prepared host input → FPGA result acceptance. Bars = median; ticks = p95. 200"
        " calls per file/variant."
    ),
    "A2_real_speedup_bars": (
        "Speedup = GPU median / FPGA_HLS4ML median; above 1× favors FPGA_HLS4ML."
        " Endpoint: FPGA result acceptance."
    ),
    "A3_real_latency_scatter": (
        "Prepared host input → FPGA result acceptance. Points = medians of 200 calls"
        " per file/variant."
    ),
}
FIGURE_NOTES.update(
    {
        "04_invocation_breakdown": (
            "Means of 200 calls; reception lanes overlap the stacked intervals. 128* ="
            " 128 MiB − 64 B."
        ),
        "05_execution_overlap": (
            "Actual trials nearest median result availability. Parallel lanes overlap;"
            " do not add their durations."
        ),
        "06_gpu_diagnostics": (
            "Separate compute diagnostics; input already on GPU. Profiled: 20 calls;"
            " unprofiled: 1,000. Medians and p95 ticks."
        ),
        "07_checker_optimization": (
            "Prepared host input → accepted FPGA result. Points = medians; short ticks"
            " = p95. 128* = 128 MiB − 64 B."
        ),
        "08_fpga_resources": (
            "Routed user wrapper, including interfaces and ILA; percentages use total"
            " U55C capacity. Shell resources excluded."
        ),
        "09_streaming_timelines": (
            "FPGA-clock intervals from arm. CNN interval includes stalls waiting for"
            " incoming pixels. Lanes overlap."
        ),
    }
)


def figure(name, fig):
    title_text = FIGURE_TITLES[name]
    note = FIGURE_NOTES.get(name, "")
    if name.startswith(("01_", "02_", "04_", "05_", "A1_", "A2_", "A3_")):
        note += " GPU: R06 XLA + ConcreteFunction (FP32); FPGA: W8A8."
    note = textwrap.fill(note, width=115)
    fig.suptitle(
        title_text + ("\n" + note if note else ""), fontsize=12, fontweight="medium"
    )
    assert fig._suptitle.get_text().startswith(title_text)
    for ext in ["png", "svg", "pdf"]:
        fig.savefig(FIG / (name + "." + ext), bbox_inches="tight", facecolor="white")
    plt.close(fig)
    FIGURES.append(name)
    return name


def axes_grid(rows=1, cols=2, size=None):
    fig, axs = plt.subplots(
        rows, cols, figsize=size or (9, 3.3 * rows), squeeze=False, layout="constrained"
    )
    for ax in axs.flat:
        ax.grid(axis="y", alpha=0.2)
        ax.set_axisbelow(True)
    return fig, axs


from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
from matplotlib.lines import Line2D

OLD_ROOTS = [
    OUT.parent / x
    for x in [
        "2026-10-21_focused_verdict_availability",
        "2026-10-21_focused_hls4ml_checker_gpu_preprocess_v2",
        "2026-10-21_final_benchmarks_gpu_preprocess_v2",
        "2026-10-20_final_benchmarks",
    ]
]
OLD_HASHES = {
    str(p.relative_to(OUT.parent)): sha(p)
    for root in OLD_ROOTS
    for p in root.rglob("*")
    if p.is_file() and "__pycache__" not in p.parts
}
COMPARE = IDS[2:]
DISPLAY = {**N, IDS[2]: "FPGA_HLS4ML"}
REAL = [c for c, n in CASES if c.startswith("real")]
RID = {c: f"R{j+1}" for j, c in enumerate(REAL)}
assert len(SYN) == 4 and len(REAL) == 8 and len(CASES) == 12
assert S["status"] == "passed"


def record_source(path, expected=None):
    digest = sha(path)
    if expected is not None:
        assert digest == expected, ("Source hash mismatch", str(path))
    VERIFIED[str(path.relative_to(REPO))] = digest


for campaign_root, campaign in [(FPGA_ROOT, FPGA_CAMPAIGN), (ROOT, GPU_CAMPAIGN)]:
    manifest = json.loads((campaign_root / "measurement_manifest.json").read_text())
    assert manifest["status"] == "passed"
    for relative_path, digest in manifest["files"].items():
        record_source(campaign_root / relative_path, digest)
    for filename in [
        "summary.json",
        "campaign.json",
        "measurement_manifest.json",
        "board_admission.json",
    ]:
        record_source(campaign_root / filename)
    for relative_path, digest in campaign["software_files"].items():
        record_source(campaign_root / relative_path, digest)

for key in [
    "hostname",
    "device",
    "pci_bdf",
    "board_serial",
    "gpu",
    "gpu_bdf",
    "cpu",
    "numa_node",
    "driver_sha256",
]:
    assert GPU_CAMPAIGN[key] == FPGA_CAMPAIGN[key], ("Hardware mismatch", key)
for iteration in IDS[3:] + [IDS[1]]:
    assert (
        GPU_CAMPAIGN["images"][iteration]["bitstream_sha256"]
        == FPGA_CAMPAIGN["images"][iteration]["bitstream_sha256"]
    )
assert (ROOT / "cases.tsv").read_bytes() == (FPGA_ROOT / "cases.tsv").read_bytes()
assert (ROOT / "tooling/board_benchmark.py").read_bytes() == (
    FPGA_ROOT / "tooling/board_benchmark.py"
).read_bytes()

diagnostic_config = json.loads((DIAGNOSTIC_ROOT / "experiment.json").read_text())
for relative_path, digest in diagnostic_config["source_hashes"].items():
    record_source(DIAGNOSTIC_ROOT / relative_path, digest)
for filename in [
    "experiment.json",
    "measurement/result.json",
    "measurement/profiles.json",
]:
    record_source(DIAGNOSTIC_ROOT / filename)
DIAGNOSTICS = json.loads((DIAGNOSTIC_ROOT / "measurement/result.json").read_text())
JOINT_PROFILES = json.loads((DIAGNOSTIC_ROOT / "measurement/profiles.json").read_text())
assert DIAGNOSTICS["status"] == "passed"
assert DIAGNOSTICS["weights_unchanged"] and DIAGNOSTICS["precision"] == "FP32"

# A shared streaming control supports comparisons across the two accepted campaigns.
# These control statistics use host-observed completion, not the headline CSR14 endpoint.
BASELINE_COMPARISON = []
for case_id, input_bytes in CASES:
    reference = next(
        row
        for row in FPGA_SUMMARY["rows"]
        if row["iteration"] == IDS[1]
        and row["case_id"] == case_id
        and row["scope"] == "resident"
    )
    control = next(
        row
        for row in GPU_SUMMARY["rows"]
        if row["iteration"] == IDS[1]
        and row["case_id"] == case_id
        and row["scope"] == "resident"
    )
    previous_ms = reference["host_observed_ms"]["median"]
    current_ms = control["host_observed_ms"]["median"]
    BASELINE_COMPARISON.append(
        {
            "case_id": case_id,
            "input_bytes": input_bytes,
            "metric": "resident host_observed_ms",
            "fpga_campaign_median_ms": previous_ms,
            "r06_campaign_median_ms": current_ms,
            "relative_change_percent": (current_ms / previous_ms - 1) * 100,
            "fpga_evidence": reference["evidence"],
            "r06_evidence": control["evidence"],
        }
    )
MAX_CONTROL_DRIFT_PERCENT = max(
    abs(row["relative_change_percent"]) for row in BASELINE_COMPARISON
)
assert MAX_CONTROL_DRIFT_PERCENT < 5
VALIDATION["cross_campaign_control_max_change_percent"] = MAX_CONTROL_DRIFT_PERCENT
VALIDATION["cross_campaign_hardware_and_input_identity_verified"] = True

for i in IDS:
    for c, n in CASES:
        raw, old = trials(i, c, "resident")
        by_trial = {int(d["trial"]): d for d in old}
        events = []
        evidence = ROWS[i, c, "resident"]["evidence"]
        for r in raw:
            mapped, details = model_for(evidence, r, i in IDS[3:])
            d = derive(r, mapped, details, i)
            assert d["input_bytes"] == n
            assert (
                abs(
                    d["host_observed_ms"]
                    - float(by_trial[d["trial"]]["host_observed_ms"])
                )
                < 1e-9
            )
            d["source_evidence"] = evidence
            d["runtime_revision"] = (
                "R06_xla_concrete" if i in IDS[3:] else "unchanged FPGA checker"
            )
            for k in [6, 7, 8, 9, 14, 15]:
                d["csr_" + str(k)] = int(r["csr_" + str(k)])
            events.append(d)
            TRIAL_EXPORT.append(d)
        assert len(events) == 200 and len({d["input_sha256"] for d in events}) == 1
        EVENTS[i, c] = events
        for metric in [
            "verdict_available_ms",
            "input_complete_ms",
            "reception_ms",
            "fpga_complete_ms",
            "host_observed_ms",
            "remaining_input_after_result_ms",
            "result_to_fpga_complete_ms",
            "host_observation_delay_ms",
        ]:
            record = dict(
                iteration=i,
                label=DISPLAY[i],
                case_id=c,
                input_bytes=n,
                metric=metric,
                timing_scope="prepared host input",
                evidence=evidence,
                **stat([d[metric] for d in events]),
            )
            if metric == "verdict_available_ms":
                record.update(
                    median_lower_ms=pct(
                        [d["verdict_available_lower_ms"] for d in events], 50
                    ),
                    median_upper_ms=pct(
                        [d["verdict_available_upper_ms"] for d in events], 50
                    ),
                    p95_lower_ms=pct(
                        [d["verdict_available_lower_ms"] for d in events], 95
                    ),
                    p95_upper_ms=pct(
                        [d["verdict_available_upper_ms"] for d in events], 95
                    ),
                )
            STATS.append(record)
for c, _ in CASES:
    assert len({EVENTS[i, c][0]["input_sha256"] for i in IDS}) == 1
large = EVENTS[IDS[3], SYN[-1]]
assert all(d["result_before_input_complete"] for d in large)
VALIDATION.update(
    selected_cells=60,
    measured_trials=len(TRIAL_EXPORT),
    source_hashes=len(VERIFIED),
    original_host_statistics_reconciled=True,
    calibration_blocks_matched=True,
    max_alignment_half_width_ms=max(
        d["max_alignment_half_width_ms"] for d in TRIAL_EXPORT
    ),
)
print(
    "PASS evidence hashes, calibrated events and all 12,000 accepted calls", flush=True
)

SPEEDUPS = []


def labels(cases):
    return [
        case_label(c) if c in SYN else f"{RID[c]}\n{CASE[c]/2**20:.2f} MiB"
        for c in cases
    ]


def latency_bars(cases, name):
    f, a = plt.subplots(figsize=(11, 5.8), layout="constrained")
    x = np.arange(len(cases))
    width = 0.24
    for j, i in enumerate(COMPARE):
        vv = [med(i, c, "resident") for c in cases]
        pp = [pct(values(i, c, "resident", "verdict_available_ms"), 95) for c in cases]
        xx = x + (j - 1) * width
        a.bar(xx, vv, width, color=C[i], label=DISPLAY[i])
        a.scatter(xx, pp, marker="_", color="black", s=65, zorder=4)
        for xx1, v, p95 in zip(xx, vv, pp):
            a.annotate(
                f"{v:.3f}",
                (xx1, max(v, p95)),
                xytext=(0, 5),
                textcoords="offset points",
                ha="center",
                fontsize=9,
                rotation=90 if len(cases) > 4 else 0,
            )
    a.set_xticks(x, labels(cases))
    a.set(
        xlabel="Raw input size" if cases == SYN else "Real bitstream / raw input size",
        ylabel="Invocation → verdict available inside FPGA (ms)",
    )
    a.set_ylim(
        0,
        max(
            pct(values(i, c, "resident", "verdict_available_ms"), 95)
            for i in COMPARE
            for c in cases
        )
        * (1.26 if len(cases) > 4 else 1.18),
    )
    h, l = a.get_legend_handles_labels()
    h.append(Line2D([], [], marker="_", ls="", color="black"))
    l.append("p95 marker")
    a.legend(h, l, ncol=4, loc="upper left", fontsize=10)
    a.grid(axis="y", alpha=0.2)
    a.set_axisbelow(True)
    figure(name, f)


def speedup_bars(cases, name):
    f, a = plt.subplots(figsize=(11, 5.8), layout="constrained")
    x = np.arange(len(cases))
    width = 0.32
    for j, i in enumerate(IDS[3:]):
        vv = [med(i, c, "resident") / med(IDS[2], c, "resident") for c in cases]
        xx = x + (j - 0.5) * width
        a.bar(xx, vv, width, color=C[i], label="vs " + DISPLAY[i])
        for c, xx1, v in zip(cases, xx, vv):
            a.text(xx1, v + 0.04, f"{v:.2f}×", ha="center", va="bottom", fontsize=10)
            SPEEDUPS.append(
                dict(
                    case_id=c,
                    comparison="FPGA_HLS4ML vs " + DISPLAY[i],
                    metric="verdict_available_ms",
                    speedup=v,
                )
            )
    a.axhline(1, color="#4e5560", ls="--", lw=1)
    a.set_xticks(x, labels(cases))
    a.set(
        xlabel="Raw input size" if cases == SYN else "Real bitstream / raw input size",
        ylabel="FPGA_HLS4ML speedup (×)",
    )
    a.set_ylim(0, max(v["speedup"] for v in SPEEDUPS) * 1.18)
    a.legend(ncol=2)
    a.grid(axis="y", alpha=0.2)
    a.set_axisbelow(True)
    figure(name, f)


latency_bars(SYN, "01_synthetic_latency")
speedup_bars(SYN, "02_synthetic_speedup")
latency_bars(REAL, "A1_real_latency")
speedup_bars(REAL, "A2_real_speedup_bars")
f, a = plt.subplots(figsize=(11, 5.8), layout="constrained")
for i, marker in zip(COMPARE, ["o", "s", "D"]):
    xx = [CASE[c] / 2**20 for c in REAL]
    yy = [med(i, c, "resident") for c in REAL]
    a.scatter(xx, yy, color=C[i], marker=marker, label=DISPLAY[i], s=45)
    for c, x, y in zip(REAL, xx, yy):
        a.annotate(
            RID[c],
            (x, y),
            xytext=(4, 5),
            textcoords="offset points",
            fontsize=9,
            color=C[i],
        )
a.set(
    xlabel="Raw input size (MiB)",
    ylabel="Invocation → verdict available inside FPGA (ms)",
    ylim=(0, max(med(i, c, "resident") for i in COMPARE for c in REAL) * 1.18),
)
a.legend()
a.grid(alpha=0.2)
figure("A3_real_latency_scatter", f)


# Setup schematic: physical connectivity plus three logical data paths.
def box(ax, x, y, w, h, text, color="#e9eef4", fs=10):
    ax.add_patch(
        FancyBboxPatch(
            (x, y),
            w,
            h,
            boxstyle="round,pad=0.015",
            facecolor=color,
            edgecolor="#617184",
            lw=1,
        )
    )
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=fs)


def arrow(ax, p, q, color="#465e73", style="-", rad=0):
    ax.add_patch(
        FancyArrowPatch(
            p,
            q,
            arrowstyle="-|>",
            mutation_scale=12,
            lw=1.6,
            color=color,
            linestyle=style,
            connectionstyle=f"arc3,rad={rad}",
        )
    )


def physical(ax):
    ax.set(xlim=(0, 10), ylim=(0, 2.4))
    ax.axis("off")
    ax.set_title("Shared machine: hacc-gpu-u55c-01", loc="left")
    box(ax, 0.15, 1.15, 2.15, 0.68, "Host CPU + RAM\nCPU64 / NUMA1", fs=10)
    box(
        ax,
        3.0,
        1.15,
        3.4,
        0.68,
        "PCIe fabric / root complexes\nCross-root peer transactions",
        fs=10,
    )
    box(ax, 7.2, 1.25, 2.6, 0.65, "U55C FPGA (device2)\nPCIe Gen3 ×16", fs=10)
    box(ax, 7.2, 0.15, 2.6, 0.65, "MI210 GPU0 + GPU RAM\nNUMA0 · PCIe Gen4 ×16", fs=10)
    arrow(ax, (2.3, 1.49), (3, 1.49))
    arrow(ax, (6.4, 1.49), (7.2, 1.57))
    arrow(ax, (6.4, 1.49), (7.2, 0.48))
    arrow(ax, (7.2, 0.42), (6.0, 1.15), color="#7752a5", rad=-0.15)
    ax.text(
        0.15,
        0.30,
        "P2P traverses the PCIe fabric; it is not a dedicated cable.\nHost controls GPU"
        " launches; FPGA polls the GPU_P2P mailbox.",
        fontsize=10,
        va="center",
    )


def path_panel(ax, kind):
    ax.set(xlim=(0, 10), ylim=(0, 2.4))
    ax.axis("off")
    ax.set_title(
        kind,
        loc="left",
        color=C[
            (
                IDS[2]
                if kind == "FPGA_HLS4ML"
                else IDS[3] if kind == "GPU_HOST" else IDS[4]
            )
        ],
        fontweight="bold",
    )
    if kind == "FPGA_HLS4ML":
        box(ax, 0.15, 1, 2, 0.65, "Prepared host RAM")
        box(
            ax,
            3.4,
            1,
            3.0,
            0.65,
            "FPGA streaming\npreprocessing + CNN",
            color="#e2f1e7",
        )
        box(ax, 7.5, 1, 2.2, 0.65, "Result available\ninside FPGA (CSR14)")
        arrow(ax, (2.15, 1.33), (3.4, 1.33))
        arrow(ax, (6.4, 1.33), (7.5, 1.33), color="#23884b")
        ax.text(2.75, 1.53, "PCIe", ha="center", fontsize=9)
        ax.text(
            0.2,
            0.35,
            "Input transfer, preprocessing, and CNN execution overlap.",
            fontsize=10,
        )
    elif kind == "GPU_HOST":
        box(ax, 0.15, 0.9, 1.8, 0.65, "Prepared\nhost RAM")
        box(
            ax,
            3.1,
            1.25,
            2.5,
            0.68,
            "GPU preprocessing + CNN\nR06 XLA graph",
            color="#fae9d9",
        )
        box(ax, 3.1, 0.15, 2.5, 0.65, "FPGA input reception\ncontinues independently")
        box(ax, 6.3, 1.25, 1.4, 0.68, "Host\nresult relay")
        box(ax, 8.3, 0.55, 1.5, 0.68, "FPGA result\naccepted")
        arrow(ax, (1.95, 1.4), (3.1, 1.58))
        arrow(ax, (1.95, 1.0), (3.1, 0.48))
        arrow(ax, (5.6, 1.58), (6.3, 1.58), color="#23884b")
        arrow(ax, (7.7, 1.58), (8.3, 1.0), color="#23884b")
        ax.text(2.5, 1.88, "PCIe input copies", ha="center", fontsize=9)
        ax.text(
            0.2,
            -0.05,
            "FPGA input may still be arriving when its classification result is"
            " accepted.",
            fontsize=9,
        )
    else:
        box(ax, 0.15, 1.05, 1.8, 0.65, "Prepared\nhost RAM")
        box(
            ax, 3.05, 1.05, 2.0, 0.65, "FPGA bridge\n32 × 64-byte FIFO", color="#eee6f5"
        )
        box(
            ax,
            6.05,
            1.05,
            3.6,
            0.65,
            "GPU input → R06 XLA graph\nPublish score + ready flag",
            color="#eee6f5",
        )
        arrow(ax, (1.95, 1.37), (3.05, 1.37))
        arrow(ax, (5.05, 1.37), (6.05, 1.37), color="#7752a5")
        ax.text(5.55, 1.9, "PCIe P2P", ha="center", fontsize=9)
        arrow(ax, (4.0, 1.05), (7.3, 1.05), color="#7752a5", style="--", rad=0.22)
        arrow(ax, (7.8, 1.05), (4.3, 1.05), color="#23884b", rad=-0.43)
        ax.text(5.7, 0.68, "Mailbox polling", ha="center", fontsize=9)
        ax.text(
            5.7,
            0.10,
            "Result accepted inside FPGA (CSR14)",
            ha="center",
            fontsize=9,
            color="#23884b",
            bbox={"facecolor": "white", "edgecolor": "none", "pad": 2},
        )
        ax.text(0.2, 0.25, "GPU starts after\ncomplete input arrival.", fontsize=9)
    # Explicit control-plane note, rather than a misleading physical wire.
    ax.text(
        0.2,
        2.14,
        "Host arms transfer and launches work  - - →",
        fontsize=9,
        color="#617184",
    )


f = plt.figure(figsize=(11, 9.5), layout="constrained")
axs = f.subplots(4, 1)
physical(axs[0])
for a, k in zip(axs[1:], ["FPGA_HLS4ML", "GPU_HOST", "GPU_P2P"]):
    path_panel(a, k)
figure("03_benchmark_setup", f)
for k in ["FPGA_HLS4ML", "GPU_HOST", "GPU_P2P"]:
    f, a = plt.subplots(figsize=(11, 3.2), layout="constrained")
    path_panel(a, k)
    figure("03_setup_" + k, f)
f, a = plt.subplots(figsize=(11, 3.3), layout="constrained")
physical(a)
figure("03_setup_connectivity", f)

PHASES = [
    "Host setup",
    "Transfer submission",
    "GPU input-ready wait",
    "Combined GPU call",
    "Synchronization / publication",
    "Remaining wait for result",
]
PC = ["#a5b6c6", "#7d9cb7", "#557da5", "#dda64c", "#b483b5", "#50616a"]


def phase_values(i, c):
    raw, _ = trials(i, c, "resident")
    by_trial = {d["trial"]: d for d in EVENTS[i, c]}
    vals = [
        phase_partition(r, by_trial[int(r["trial"])]["verdict_available_ms"])
        for r in raw
    ]
    means = np.mean(vals, axis=0)
    assert (
        abs(sum(means) - np.mean([d["verdict_available_ms"] for d in EVENTS[i, c]]))
        < 1e-9
    )
    for k, v in zip(PHASES, means):
        SEGMENTS.append(
            dict(iteration=i, label=DISPLAY[i], case_id=c, phase=k, mean_ms=float(v))
        )
    return means


f, axs = axes_grid(3, 1, size=(11, 9.3))
endmax = (
    max(
        np.mean([d[k] for d in EVENTS[i, c]])
        for i in COMPARE
        for c in SYN
        for k in ["verdict_available_ms", "input_complete_ms"]
    )
    * 1.13
)
for a, i in zip(axs.flat, COMPARE):
    for j, c in enumerate(SYN):
        vals = phase_values(i, c)
        left = 0
        for label, v, color in zip(PHASES, vals, PC):
            a.barh(
                j,
                v,
                left=left,
                height=0.28,
                color=color,
                label=label if j == 0 else None,
            )
            left += v
        start, last = [
            np.mean([d[k] for d in EVENTS[i, c]])
            for k in ["input_first_ms", "input_complete_ms"]
        ]
        a.plot(
            [start, last],
            [j + 0.30, j + 0.30],
            lw=3,
            color="#087e8b",
            solid_capstyle="butt",
        )
        a.scatter([left], [j], c="black", marker="o", s=21, zorder=5)
        a.scatter([last], [j + 0.30], c="#087e8b", marker="s", s=21, zorder=5)
        a.annotate(
            f"{left:.3f}",
            (left, j),
            xytext=(5, 2),
            textcoords="offset points",
            fontsize=8,
            va="bottom",
        )
        a.annotate(
            f"{last:.3f}",
            (last, j + 0.30),
            xytext=(5, -3),
            textcoords="offset points",
            fontsize=8,
            va="top",
            color="#087e8b",
        )
    a.set_yticks(np.arange(4) + 0.12, ["4 MiB", "16 MiB", "64 MiB", "128* MiB"])
    a.set(
        xlim=(0, endmax),
        ylim=(3.85, -0.45),
        xlabel="Time from host invocation (ms)",
        title=DISPLAY[i],
    )
    a.grid(axis="x", alpha=0.2)
    a.grid(axis="y", visible=False)
handles = [
    plt.Rectangle((0, 0), 1, 1, color=color, label=label)
    for label, color in zip(PHASES, PC)
]
handles += [
    Line2D(
        [], [], marker="o", ls="", color="black", label="Result available inside FPGA"
    ),
    Line2D(
        [],
        [],
        marker="s",
        color="#087e8b",
        lw=3,
        label="FPGA reception → entire input arrived",
    ),
]
f.legend(handles=handles, loc="outside lower center", ncol=3, fontsize=9)
figure("04_invocation_breakdown", f)


@lru_cache(None)
def representative(i, c):
    raw, _ = trials(i, c, "resident")
    d = min(
        EVENTS[i, c],
        key=lambda d: abs(d["verdict_available_ms"] - med(i, c, "resident")),
    )
    r = next(r for r in raw if int(r["trial"]) == d["trial"])
    return r, d


def event_interval(i, c, r, d, k1, k2):
    mapped, _ = model_for(ROWS[i, c, "resident"]["evidence"], r, i in IDS[3:])
    h = int(r["host_start_ns"])
    lo0, hi0 = mapped(int(r["csr_" + str(k1)]))
    lo1, hi1 = mapped(int(r["csr_" + str(k2)]))
    return (
        ((lo0 + hi0) / 2 - h) / 1e6,
        ((lo1 + hi1) / 2 - h) / 1e6,
        max(hi0 - lo0, hi1 - lo1) / 2e6,
    )


f, axs = axes_grid(2, 3, size=(13.4, 8.4))
ENDPOINTS = [
    ("input_complete_ms", "Entire input arrived", "s", "#087e8b"),
    ("verdict_available_ms", "Result available", "o", "#111111"),
    ("fpga_complete_ms", "FPGA operation complete", "x", "#ab4e69"),
    ("host_observed_ms", "Host observes completion", "D", "#707986"),
]
for row, c in enumerate(REPS):
    endmax = max(representative(i, c)[1]["host_observed_ms"] for i in COMPARE) * 1.07
    for col, i in enumerate(COMPARE):
        a = axs[row, col]
        r, d = representative(i, c)
        h = int(r["host_start_ns"])
        ints = []

        def add_fpga(label, k1, k2, color):
            start, stop, u = event_interval(i, c, r, d, k1, k2)
            ints.append((label, start, stop, color, u))

        add_fpga("FPGA reception", 8, 9, "#087e8b")
        if i == IDS[2]:
            add_fpga("Pixel production", 10, 11, "#8cc4c3")
            add_fpga("CNN interval", 12, 14, "#dda64c")
        else:
            if i == IDS[4]:
                add_fpga("P2P forwarding", 18, 19, "#7752a5")
            for label, k1, k2, color in [
                ("GPU-input wait", "submit_ns", "input_ready_ns", "#557da5"),
                ("Combined GPU call", "input_ready_ns", "relay_start_ns", "#dda64c"),
                ("Sync/publication", "relay_start_ns", "relay_end_ns", "#b483b5"),
            ]:
                ints.append(
                    (label, (int(r[k1]) - h) / 1e6, (int(r[k2]) - h) / 1e6, color, 0)
                )
            if i == IDS[4]:
                add_fpga("Polling / retrieval", 38, 14, "#7752a5")
        for j, (label, start, stop, color, u) in enumerate(ints):
            assert stop >= start
            a.barh(j, stop - start, left=start, height=0.55, color=color)
            if u:
                for x in [start, stop]:
                    a.plot([x - u, x + u], [j, j], color="black", lw=2)
            TIMELINES.append(
                dict(
                    figure="05",
                    iteration=i,
                    label=DISPLAY[i],
                    case_id=c,
                    trial=d["trial"],
                    kind="interval",
                    activity=label,
                    start_ms=start,
                    end_ms=stop,
                    uncertainty_ms=u,
                )
            )
        labs = [x[0] for x in ints]
        for j, (key, label, marker, color) in enumerate(ENDPOINTS, start=len(ints)):
            x = d[key]
            u = (
                0
                if key == "host_observed_ms"
                else (
                    d[key.replace("_ms", "_upper_ms")]
                    - d[key.replace("_ms", "_lower_ms")]
                )
                / 2
            )
            a.scatter([x], [j], marker=marker, color=color, s=27, zorder=5)
            if u:
                a.plot([x - u, x + u], [j, j], color="black", lw=1.5)
            labs.append(label)
            TIMELINES.append(
                dict(
                    figure="05",
                    iteration=i,
                    label=DISPLAY[i],
                    case_id=c,
                    trial=d["trial"],
                    kind="event",
                    activity=label,
                    start_ms=x,
                    end_ms=x,
                    uncertainty_ms=u,
                )
            )
        a.axvline(d["verdict_available_ms"], color="#111111", ls=":", lw=0.8, alpha=0.6)
        a.set_yticks(range(len(labs)), labs, fontsize=8)
        a.invert_yaxis()
        a.set(
            xlim=(0, endmax),
            xlabel="Since invocation (ms)",
            title=(
                f'{DISPLAY[i]} · {case_label(c)}\nTrial {d["trial"]} · result'
                f' {d["verdict_available_ms"]:.3f} ms'
            ),
        )
        a.title.set_fontsize(10)
        a.tick_params(axis="x", labelsize=9)
figure("05_execution_overlap", f)
# R06 fuses sampling and the CNN. Splitting those phases would change execution.
# The standalone compute diagnostic used CPU0-7/NUMA0; board trials used CPU64/NUMA1.
figure_object, diagnostic_axes = axes_grid(1, 2, size=(11, 5.2))
PROFILE_EXPORT = []
for axis, case_id in zip(diagnostic_axes.flat, REPS):
    profile = next(row for row in JOINT_PROFILES if row["case_id"] == case_id)
    compute = next(
        row for row in DIAGNOSTICS["measurements"] if row["case_id"] == case_id
    )
    assert len(profile["samples"]) == 20
    assert len(compute["samples_ms"]) == 1000
    assert {sample["kernels"] for sample in profile["samples"]} == {23}
    assert compute["input_sha256"] == EVENTS[IDS[3], case_id][0]["input_sha256"]
    sample_groups = [
        [sample[metric] for sample in profile["samples"]]
        for metric in ["kernel_sum_ms", "device_span_ms", "host_diagnostic_ms"]
    ] + [compute["samples_ms"]]
    medians = [float(np.median(samples)) for samples in sample_groups]
    percentiles = [pct(samples, 95) for samples in sample_groups]
    axis.bar(range(4), medians, color=["#dda64c", "#cf6a19", "#8dabc0", "#557da5"])
    axis.scatter(range(4), percentiles, color="black", marker="_", s=65)
    for index, (median, percentile) in enumerate(zip(medians, percentiles)):
        axis.text(
            index,
            max(median, percentile),
            f" {median:.3f}",
            ha="center",
            va="bottom",
            fontsize=10,
        )
    axis.axvline(2.5, color="gray", linestyle=":", linewidth=1)
    axis.set_xticks(
        range(4),
        [
            "Kernel\nsum",
            "Device\nspan",
            "Host sync\n(profiled)",
            "Host sync\n(unprofiled)",
        ],
    )
    axis.set(
        ylabel="Combined compute duration (ms)",
        title=case_label(case_id),
        ylim=(0, max(percentiles) * 1.22),
    )
    PROFILE_EXPORT.append(
        {
            "case_id": case_id,
            "revision": "R06_xla_concrete",
            "profiled_trials": 20,
            "unprofiled_trials": 1000,
            "profiled_samples": profile["samples"],
            "unprofiled_samples_ms": compute["samples_ms"],
            "first_call_seconds": compute["first_call_seconds"],
            "scope": compute["scope"],
            "cpu": diagnostic_config["cpu"],
            "numa": diagnostic_config["numa"],
        }
    )
diagnostic_upper_limit = max(axis.get_ylim()[1] for axis in diagnostic_axes.flat)
for axis in diagnostic_axes.flat:
    axis.set_ylim(0, diagnostic_upper_limit)
figure("06_gpu_diagnostics", figure_object)
# Optimization comparison: only synthetic inputs, Buffering and optimized Streaming.
f, axs = axes_grid(1, 2, size=(11, 4.9))
xx = np.array(SIZES) / 2**20
for i in [IDS[0], IDS[2]]:
    yy = [med(i, c, "resident") for c in SYN]
    axs[0, 0].plot(xx, yy, "o-", color=C[i], label=N[i])
    axs[0, 0].scatter(
        xx,
        [pct(values(i, c, "resident", "verdict_available_ms"), 95) for c in SYN],
        color=C[i],
        marker="_",
        s=65,
    )
axs[0, 0].set(
    xlabel="Raw input size (MiB)",
    ylabel="Invocation → verdict available inside FPGA (ms)",
    ylim=(0, None),
)
axs[0, 0].legend(fontsize=9)
rat = [med(IDS[0], c, "resident") / med(IDS[2], c, "resident") for c in SYN]
axs[0, 1].plot(
    xx,
    rat,
    "o-",
    color=C[IDS[2]],
    label="Resource-optimized streaming\nversus Buffering",
)
axs[0, 1].axhline(1, color="gray", ls="--")
axs[0, 1].set(
    xlabel="Raw input size (MiB)",
    ylabel="Speedup versus Buffering (×)",
    ylim=(0, max(rat) * 1.15),
)
axs[0, 1].legend(fontsize=9)
for a in axs.flat:
    a.set_xticks([4, 16, 64, 128], ["4", "16", "64", "128*"])
figure("07_checker_optimization", f)
# FPGA wrapper resources with matching device-percent axis.
f, axs = axes_grid(3, 2, size=(10.5, 9))
for a, key, titletext in zip(
    axs.flat,
    ["BRAM_tiles", "DSP", "LUT", "FF", "URAM"],
    ["BRAM tiles", "DSPs", "LUTs", "Flip-flops", "URAM blocks"],
):
    cap = S["resources"][IDS[0]]["capacity"][key]
    vv = [S["resources"][i]["wrapper"][key] for i in IDS[:3]]
    a.bar(range(3), vv, color=[C[i] for i in IDS[:3]])
    a.set_xticks(
        range(3),
        ["Buffering", "Streaming", "Resource-optimized\nstreaming"],
        fontsize=9,
    )
    a.set(title=titletext, ylabel="Wrapper count", ylim=(0, max(vv) * 1.28))
    a.secondary_yaxis(
        "right",
        functions=(lambda x, cap=cap: x / cap * 100, lambda x, cap=cap: x * cap / 100),
    ).set_ylabel("Device utilization (%)", fontsize=9)
    for j, v in enumerate(vv):
        a.text(j, v, f"{v:g}\n{v/cap*100:.2f}%", ha="center", va="bottom", fontsize=9)
axs.flat[-1].axis("off")
axs.flat[-1].text(
    0,
    0.95,
    "Resource-optimized streaming\nversus Streaming\n\nBRAM: −83.95%\nDSP:"
    " −51.20%\nURAM: 11 → 0\n\nRouted wrapper includes\ninterfaces and ILA.",
    va="top",
    fontsize=12,
)
figure("08_fpga_resources", f)
f, axs = axes_grid(2, 1, size=(11, 8.8))
for a, c in zip(axs.flat, REPS):
    labs = []
    ticks = []
    for j, i in enumerate(IDS[:3]):
        r, d = representative(i, c)
        _, details = model_for(ROWS[i, c, "resident"]["evidence"], r, False)
        tick = (details["ns_per_tick_min"] + details["ns_per_tick_max"]) / 2 / 1e6
        origin = int(r["csr_6"])
        for k, (label, k1, k2, color) in enumerate(
            [
                ("Reception", 8, 9, "#557da5"),
                ("Pixel production", 10, 11, "#8cc4c3"),
                ("CNN interval", 12, 14, "#dda64c"),
            ]
        ):
            start = (int(r[f"csr_{k1}"]) - origin) * tick
            stop = (int(r[f"csr_{k2}"]) - origin) * tick
            y = j * 4 + k
            a.barh(y, stop - start, left=start, color=color, height=0.65)
            ticks.append(y)
            labs.append(N[i] + " · " + label)
            if k in (0, 2):
                a.scatter(
                    [stop],
                    [y],
                    s=24,
                    marker="s" if k == 0 else "o",
                    color="#087e8b" if k == 0 else "#111111",
                    zorder=4,
                )
            TIMELINES.append(
                dict(
                    figure="09",
                    iteration=i,
                    label=N[i],
                    case_id=c,
                    trial=d["trial"],
                    kind="interval",
                    activity=label,
                    start_ms=start,
                    end_ms=stop,
                    uncertainty_ms=(int(r[f"csr_{k2}"]) - origin)
                    * (details["ns_per_tick_max"] - details["ns_per_tick_min"])
                    / 2e6,
                )
            )
    a.set_yticks(ticks, labs, fontsize=9)
    a.invert_yaxis()
    a.set(xlabel="Time from FPGA arm (ms)", title=case_label(c), xlim=(0, None))
f.legend(
    handles=[
        Line2D(
            [], [], marker="s", ls="", color="#087e8b", label="Entire input arrived"
        ),
        Line2D(
            [],
            [],
            marker="o",
            ls="",
            color="black",
            label="Result available inside FPGA",
        ),
    ],
    loc="outside lower center",
    ncol=2,
    fontsize=9,
)
figure("09_streaming_timelines", f)
print("PASS all focused figures generated", flush=True)
# Compact report: nine figure-led main pages, one methods page, three appendix pages.
styles = getSampleStyleSheet()
styles.add(
    ParagraphStyle(
        name="TitleR",
        fontName="Helvetica-Bold",
        fontSize=20,
        leading=24,
        textColor=colors.HexColor("#17324d"),
        spaceAfter=12,
    )
)
styles.add(
    ParagraphStyle(
        name="BodyR", fontName="Helvetica", fontSize=10.5, leading=14.5, spaceAfter=9
    )
)
styles.add(
    ParagraphStyle(
        name="SmallR", fontName="Helvetica", fontSize=8.5, leading=11, spaceAfter=7
    )
)
styles.add(ParagraphStyle(name="CellR", fontName="Helvetica", fontSize=8, leading=10))
STORY = []
PAGES = []


def p(s, small=False):
    STORY.append(Paragraph(s, styles["SmallR" if small else "BodyR"]))


def title(s):
    if PAGES:
        STORY.append(PageBreak())
    PAGES.append(s)
    STORY.append(Paragraph(s, styles["TitleR"]))


def plot(name, maxh=440):
    from PIL import Image as PILImage

    path = FIG / (name + ".png")
    w, h = PILImage.open(path).size
    scale = min(507 / w, maxh / h)
    STORY.extend([Image(str(path), width=w * scale, height=h * scale), Spacer(1, 12)])


def table(rows, widths):
    t = Table(
        [[Paragraph(escape(str(v)), styles["CellR"]) for v in row] for row in rows],
        colWidths=widths,
        repeatRows=1,
        hAlign="LEFT",
    )
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8eff5")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                (
                    "ROWBACKGROUNDS",
                    (0, 1),
                    (-1, -1),
                    [colors.white, colors.HexColor("#f5f7f9")],
                ),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    STORY.extend([t, Spacer(1, 10)])


def speed(i, c):
    return med(i, c, "resident") / med(IDS[2], c, "resident")


small, large = REPS

title("hls4ml-checker versus R06 GPU inference")
p("<b>Figure 1 · Synthetic inputs · GPU: XLA + ConcreteFunction (R06)</b>")
p("Report: <b>22 October 2026</b> · Accepted measurements: 21 October 2026.", True)
p(
    "The bitstream is already prepared in host RAM when timing starts. Timing ends when"
    " the FPGA accepts the classification result: the local CNN score for FPGA_HLS4ML,"
    " or the validated GPU score for GPU_HOST and GPU_P2P. This is the existing"
    " <b>CSR14 timestamp</b>."
)
plot("01_synthetic_latency", 365)
p(
    f'<b>At 4 MiB:</b> FPGA_HLS4ML takes {med(IDS[2],small,"resident"):.3f} ms,'
    f' GPU_HOST {med(IDS[3],small,"resident"):.3f} ms, and GPU_P2P'
    f' {med(IDS[4],small,"resident"):.3f} ms. At 128 MiB minus 64 B, the medians are'
    f' {med(IDS[2],large,"resident"):.3f}, {med(IDS[3],large,"resident"):.3f}, and'
    f' {med(IDS[4],large,"resident"):.3f} ms.'
)
p(
    "<b>GPU_HOST is faster at 4, 64 and approximately 128 MiB. FPGA_HLS4ML is"
    " slightly faster at 16 MiB, and faster than GPU_P2P at all four sizes.</b>"
    " Bars show medians; black ticks show p95 across 200 calls per input"
    " and implementation. GPU_P2P includes autonomous polling and result retrieval."
    " Every call still transfers the complete input, even when the result reaches the"
    " FPGA earlier."
)
p(
    "<b>Endpoint distinction:</b> accepting the classification result does not imply"
    " that the final verdict register has been updated or that reconfiguration may"
    " begin. Figures 4 and 5 show input arrival separately. FPGA uses W8A8; GPU uses"
    " the original FP32 model with R06. Compilation and warmup are excluded. Existing"
    " FPGA results are retained; the shared streaming control changes by at most 0.028%"
    " across campaigns. Real bitstreams appear only in the appendix.",
    True,
)

title("Checker speedup to verdict availability")
p("<b>Figure 2 · Synthetic inputs · Values above 1 favor FPGA_HLS4ML</b>")
plot("02_synthetic_speedup", 385)
p(
    "<b>Speedup = GPU median result-availability latency / FPGA_HLS4ML median"
    " result-availability latency.</b> Both timings end inside the FPGA at acceptance"
    " of the classification result. Values below 1 favor the GPU path."
)
p(
    f"Against GPU_HOST, the ratios are {speed(IDS[3],small):.2f}x at 4 MiB and"
    f" {speed(IDS[3],large):.2f}x at the largest input. Against GPU_P2P, they are"
    f" {speed(IDS[4],small):.2f}x and {speed(IDS[4],large):.2f}x."
)
p(
    "R06 combines preprocessing and inference in a static-length XLA graph and calls"
    " its cached ConcreteFunction directly. GPU_HOST can deliver its result before the"
    " FPGA receives all input bytes. Its Gen4 x16 GPU copy is faster than reception"
    " through the FPGA Gen3 x16 path. The revised endpoint exposes this difference"
    " instead of including the subsequent wait for the remaining FPGA input."
)
p(
    "Ratios use independent-run medians, not paired trials or confidence intervals."
    " These compare complete implemented paths with different model precisions; they"
    " are not equal-precision kernel benchmarks.",
    True,
)

title("Benchmark setup and data paths")
p("<b>Figure 3 · Shared physical setup and logical paths</b>")
plot("03_benchmark_setup", 465)
p(
    "Solid arrows carry input; green arrows carry the classification result; dashed"
    " arrows denote control or polling. The primary endpoint is acceptance of the"
    " result inside the FPGA. P2P uses peer transactions through the PCIe fabric, not a"
    " dedicated FPGA-GPU cable."
)
p(
    "Both GPU paths use the same R06 FP32 runtime; its preprocessing and CNN execute as"
    " one compiled graph. The FPGA checker consumes pixels while input arrives."
    " GPU_HOST starts GPU work after its GPU copy completes; the independent FPGA copy"
    " may continue. GPU_P2P forwards input incrementally through a 2 KiB FIFO, then"
    " polls GPU memory and retrieves the published result.",
    True,
)

title("Verdict availability and full-input arrival")
p("<b>Figure 4 · FPGA_HLS4ML, GPU_HOST and GPU_P2P</b>")
plot("04_invocation_breakdown", 420)
p(
    "Stacked bars end at <b>mean classification-result availability</b> (black circle)."
    " Each separate teal lane spans the first through last FPGA payload beat; the"
    " square marks when the entire input has arrived. These intervals overlap and must"
    " not be added. All panels use the same time scale."
)
p(
    "The stacked segments are consecutive observed host intervals, clipped at the FPGA"
    " result timestamp. They describe elapsed time, not isolated device costs. The"
    " combined GPU call covers framework dispatch and any execution completed before"
    " the call returns; remaining execution may appear in synchronization/publication."
    " FPGA_HLS4ML has no GPU phases: its remaining wait includes streaming"
    " preprocessing and CNN execution. GPU-input wait ends at GPU readiness, not"
    " necessarily FPGA input completion."
)
L = EVENTS[IDS[3], large]
p(
    "For the largest GPU_HOST input, the result is accepted at"
    f' {np.mean([d["verdict_available_ms"] for d in L]):.3f} ms on average; the last'
    f' FPGA input beat arrives at {np.mean([d["input_complete_ms"] for d in L]):.3f}'
    f' ms. The {np.mean([d["remaining_input_after_result_ms"] for d in L]):.3f} ms'
    " difference is remaining input reception, not verdict-notification overhead.",
    True,
)

title("How the execution paths overlap")
p("<b>Figure 5 · Representative measured trials, including GPU_P2P</b>")
plot("05_execution_overlap", 420)
p(
    "Each panel uses a real trial nearest that implementation’s median"
    " result-availability latency. Its ID appears in the title. The two input-size rows"
    " share scales across implementations. Circle: result accepted. Square: entire"
    " input received. Cross: FPGA operation complete. Diamond: host observes"
    " completion."
)
p(
    "GPU_P2P’s polling/retrieval lane starts at the first readiness read and ends when"
    " the validated result reaches the controller. It can overlap GPU execution. FPGA"
    " forwarding and reception also overlap. GPU_HOST’s result can arrive before its"
    " FPGA input transfer finishes."
)
p(
    "FPGA event endpoints use the existing host/FPGA clock calibration; black endpoint"
    " marks indicate alignment uncertainty. Host-aligned GPU copy start was not"
    " recorded, so the figure shows the observed GPU-input wait. Lanes overlap and must"
    " not be added.",
    True,
)

title("R06: compiled GPU preprocessing and inference")
p("<b>Figure 6 · Combined compute diagnostics, separate from board timings</b>")
plot("06_gpu_diagnostics", 335)
p(
    "<b>Kernel sum:</b> attributed GPU kernel durations. <b>Device span:</b> first"
    " kernel start through last completion, including gaps. <b>Host synchronized:</b>"
    " the complete call through scalar synchronization. The first three bars use 20"
    " profiled calls; the fourth uses 1,000 unprofiled calls. Black ticks mark p95."
    " These are alternative timing scopes, not additive stages."
)
p(
    "R06 uses one <b>tf.function(jit_compile=True)</b> for sampling, normalization and"
    " the original FP32 model. A cached <b>get_concrete_function()</b> is called"
    " directly for each input length. Joint traces contain 23 kernels. Preprocessing"
    " and inference cannot be separated faithfully without changing this fused"
    " execution."
)
p(
    "Unprofiled compute medians are <b>0.432 ms at 4 MiB</b> and <b>0.421 ms at the"
    " largest input</b>. GPU device spans are 0.188 and 0.196 ms. Input transport,"
    " result publication and FPGA polling are outside these standalone measurements."
)
p(
    "These diagnostics used CPU0-7 / NUMA0; all board-path measurements used CPU64 /"
    " NUMA1. Do not subtract these compute durations from Figures 1-5. First calls"
    " include approximately 137 ms of setup/compilation for these two examples and are"
    " excluded from steady-state timing; unseen input lengths need preparation. R07-R10"
    " and DMA32 transport experiments are excluded.",
    True,
)

title("Checker optimization: latency impact")
p("<b>Figure 7 · Buffering versus Resource-optimized streaming</b>")
plot("07_checker_optimization", 350)
p(
    f'At 4 MiB, Buffering reaches its result in {med(IDS[0],small,"resident"):.3f} ms'
    f' and Resource-optimized streaming in {med(IDS[2],small,"resident"):.3f} ms:'
    f' {med(IDS[0],small,"resident")/med(IDS[2],small,"resident"):.2f}x speedup. At the'
    " largest input, the speedup is"
    f' {med(IDS[0],large,"resident")/med(IDS[2],large,"resident"):.2f}x.'
)
p(
    "The left panel shows invocation-to-result medians and p95 ticks. The right divides"
    " Buffering median by Resource-optimized streaming median. Lines connect measured"
    " sizes only. Both use the same CSR14 endpoint as Figures 1 and 2."
)
p(
    "Resource-optimized streaming combines native hls4ml FIFO optimization (profiling"
    " capacity 1024) with convolution reuse factors 72/72/288/288 for conv3/4/5/6. The"
    " profiling capacity is not a uniform final FIFO depth. The fixed quantized model,"
    " streaming preprocessing and timestamp interface are retained.",
    True,
)

title("Checker optimization: resource impact")
p("<b>Figure 8 · FPGA variants only</b>")
plot("08_fpga_resources", 465)
p(
    "Relative to Streaming, Resource-optimized streaming reduces wrapper BRAM from"
    " <b>339.5 to 54.5 tiles</b> (83.95%) and DSPs from <b>1328 to 648</b> (51.20%)."
    " URAM falls from 11 blocks to zero."
)
p(
    "Counts are routed user-wrapper resources, including interfaces and ILA. Right axes"
    " and bar labels express percentages of total U55C capacity. The shell occupies"
    " additional resources. These resource measurements are unchanged from the previous"
    " report.",
    True,
)

title("How streaming overlaps the work")
p("<b>Figure 9 · Common FPGA timestamps across three checker variants</b>")
plot("09_streaming_timelines", 465)
p(
    "Buffering waits for the entire input and pixel frame before CNN consumption."
    " Streaming starts the CNN as pixels become available. Resource-optimized streaming"
    " preserves this overlap while reducing memory and multiplier resources."
)
p(
    "Squares mark full-input arrival; circles mark classification-result availability."
    " Each example is the trial nearest median result-availability latency. All lanes"
    " use the FPGA clock relative to arm. The CNN interval includes waiting for pixels;"
    " it is not standalone arithmetic time. Trial IDs and clock uncertainty are"
    " exported.",
    True,
)

title("Measurement definitions and evidence")
table(
    [
        ["Item", "Definition / scope"],
        [
            "Primary endpoint",
            (
                "Prepared host invocation to accepted classification result inside"
                " FPGA: CSR14."
            ),
        ],
        [
            "Input reception",
            "CSR8 to CSR9; invocation to CSR9 separately records full-input arrival.",
        ],
        [
            "Final completion",
            (
                "CSR15 marks committed verdict/done. Host observation is later and"
                " remains in exported data."
            ),
        ],
        [
            "GPU_P2P endpoint",
            (
                "CSR14 follows autonomous mailbox polling, payload retrieval and"
                " validation."
            ),
        ],
        [
            "Not an early-release claim",
            (
                "The accepted score is available internally; the public verdict"
                " register may still wait for full input. No PR admission behavior was"
                " changed."
            ),
        ],
        [
            "Workloads",
            (
                "4 synthetic sizes and 8 real files; 200 measured calls per"
                " implementation/input; warmups excluded."
            ),
        ],
        [
            "FPGA labels",
            (
                "Buffering = OPT_0; Streaming = OPT_1; Resource-optimized streaming /"
                " FPGA_HLS4ML = OPT_6."
            ),
        ],
        [
            "GPU labels",
            (
                "GPU_HOST = OPT_7; GPU_P2P = OPT_8. Original FP32 TensorFlow model;"
                " combined XLA graph with direct ConcreteFunction calls (R06)."
            ),
        ],
        [
            "Hardware",
            (
                "U55C device2 at 81:00.0; MI210 GPU0 at 03:00.0; hacc-gpu-u55c-01."
                " CPU64 / NUMA1; GPU on NUMA0."
            ),
        ],
        [
            "Clock alignment",
            (
                "Existing per-block affine calibration; midpoint estimates with"
                " exported lower/upper bounds. Maximum endpoint half-width:"
                f' {VALIDATION["max_alignment_half_width_ms"]*1000:.3f} us.'
            ),
        ],
        [
            "Correctness / stability",
            (
                "Accepted campaigns: per-image admission, exact FPGA logits, GPU"
                " CPU-reference parity, autonomous P2P polling and baseline-drift"
                " gates."
            ),
        ],
        [
            "Cross-campaign comparison",
            (
                "FPGA results retained from preprocessing-v2 campaign; GPU results"
                " selected from accepted R06 hardware campaign. Shared OPT_1 resident"
                " host-completion medians differ by at most"
                f" {MAX_CONTROL_DRIFT_PERCENT:.3f}%. These are independent runs, not"
                " paired trials."
            ),
        ],
        [
            "Compilation / diagnostics",
            (
                "Known input lengths compiled and warmed before board arming. Figure 6"
                " uses separate joint R06 diagnostics on CPU0-7/NUMA0."
            ),
        ],
        [
            "Comparability limits",
            (
                "FPGA W8A8 versus GPU FP32; one machine/device pairing and fixed run"
                " order. No cold-SSD, equal-precision or power claim."
            ),
        ],
    ],
    [137, 370],
)
p(
    "This is offline reanalysis of existing measurements. No FPGA builds, board"
    " programming or benchmark reruns were performed. All 12,000 selected calls pass"
    " the new event and calibration checks; original host-completion statistics are"
    " reproduced unchanged.",
    True,
)
p(
    "Reproduce from the repository root: <b>ml_baseline/.venv/bin/python "
    + str(OUT.relative_to(REPO))
    + "/build_report.py</b>. The folder includes standalone titled figures, per-trial"
    " event data, statistics, timing tests and an evidence manifest.",
    True,
)

title("Appendix A1 · Real-bitstream verdict availability")
p(
    "Eight real files, ordered by size. The endpoint matches Figure 1: host invocation"
    " to accepted classification result inside the FPGA. File reading and input"
    " preparation are outside the interval."
)
plot("A1_real_latency", 400)
p(
    "Each group compares FPGA_HLS4ML, GPU_HOST and GPU_P2P for the same file. Labels"
    " show medians; black ticks show p95. Different files also have different sizes, so"
    " this does not isolate content-dependent effects."
)
p(
    "Runtime and transport effects can make results non-monotonic between files. The"
    " measurements do not establish that real bitstream contents inherently require"
    " more computation.",
    True,
)

title("Appendix A2 · Real-bitstream checker speedup")
plot("A2_real_speedup_bars", 400)
p(
    "For each file, divide the GPU median invocation-to-result latency by the"
    " FPGA_HLS4ML median using the same endpoint. Ratios above 1 favor the checker;"
    " ratios below 1 favor the GPU path. Inputs and accepted timing scope match."
)
p(
    "This report retains per-file speedup bars and does not include a speedup scatter"
    " plot.",
    True,
)

title("Appendix A3 · Real-bitstream latency by size")
plot("A3_real_latency_scatter", 290)
p(
    "Linear size axis; unconnected median result-availability latencies. R1-R8 identify"
    " the files below. No fitted trend or synthetic interpolation is overlaid.",
    True,
)
case_sources = {}
for line in (ROOT / "cases.tsv").read_text().splitlines():
    if line and not line.startswith("#"):
        fields = line.split("\t")
        case_sources[fields[0]] = fields[2]
rr = [["ID", "Bytes / MiB", "Source identifier"]]
for c in REAL:
    sourcepath = case_sources[c]
    short = (
        sourcepath.split("/upload_dataset/")[-1]
        if "/upload_dataset/" in sourcepath
        else sourcepath.split("/jobs/")[-1]
    )
    rr.append([RID[c], f"{CASE[c]:,} / {CASE[c]/2**20:.2f}", short])
table(rr, [35, 118, 354])


# Both new endpoints and the original completion measurements remain available.
def writecsv(path, rows):
    fields = list(dict.fromkeys(k for row in rows for k in row))
    with path.open("w") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


writecsv(DATA / "latency_statistics.csv", STATS)
writecsv(DATA / "speedups.csv", SPEEDUPS)
writecsv(DATA / "phase_means.csv", SEGMENTS)
writecsv(DATA / "trial_events.csv", TRIAL_EXPORT)
savejson(DATA / "trial_events.json", TRIAL_EXPORT)
savejson(DATA / "timelines.json", TIMELINES)
savejson(DATA / "gpu_profiles.json", PROFILE_EXPORT)
savejson(DATA / "resources.json", {N[i]: S["resources"][i] for i in IDS[:3]})
savejson(
    DATA / "real_inputs.json",
    [
        dict(id=RID[c], case_id=c, input_bytes=CASE[c], source=case_sources[c])
        for c in REAL
    ],
)
savejson(
    DATA / "figure_catalog.json",
    [
        dict(
            name=k,
            title=FIGURE_TITLES[k],
            note=FIGURE_NOTES.get(k, ""),
            formats=["png", "svg", "pdf"],
        )
        for k in FIGURES
    ],
)
VALIDATION.update(
    status="passed",
    excluded_warmups=True,
    additive_intervals_verified=True,
    figure_count=len(FIGURES),
    all_figures_titled=True,
    primary_metric="verdict_available_ms",
    endpoint="CSR14",
    runtime_revision="R06_xla_concrete",
    report_date="2026-10-22",
    measurement_date="2026-10-21",
    new_builds=0,
    new_benchmark_calls=0,
)
savejson(DATA / "validation.json", VALIDATION)
savejson(DATA / "report_selection.json", REPORT_SELECTION)
writecsv(DATA / "baseline_comparison.csv", BASELINE_COMPARISON)
writecsv(
    DATA / "synthetic_summary.csv",
    [
        dict(
            case_id=case_id,
            input_bytes=CASE[case_id],
            fpga_hls4ml_ms=med(IDS[2], case_id, "resident"),
            gpu_host_ms=med(IDS[3], case_id, "resident"),
            gpu_p2p_ms=med(IDS[4], case_id, "resident"),
            fpga_speedup_vs_gpu_host=speed(IDS[3], case_id),
            fpga_speedup_vs_gpu_p2p=speed(IDS[4], case_id),
        )
        for case_id in SYN
    ],
)
PDF = OUT / "gpu_opt_xla_concretefunction_report.pdf"


def footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#617184"))
    canvas.drawString(
        44, 24, "hls4ml-checker | R06 XLA + ConcreteFunction | 2026-10-22"
    )
    canvas.drawRightString(A4[0] - 44, 24, str(doc.page))
    canvas.restoreState()


SimpleDocTemplate(
    str(PDF),
    pagesize=A4,
    leftMargin=44,
    rightMargin=44,
    topMargin=38,
    bottomMargin=40,
    title="hls4ml-checker versus GPU R06: XLA + ConcreteFunction",
    author="ML Deep Bitstream Inspection",
).build(STORY, onFirstPage=footer, onLaterPages=footer)
for rel, digest in OLD_HASHES.items():
    assert sha(OUT.parent / rel) == digest, ("Original report changed", rel)
with zipfile.ZipFile(
    OUT / "standalone_figures.zip", "w", compression=zipfile.ZIP_DEFLATED
) as bundle:
    for path in sorted(FIG.glob("*")):
        if path.suffix in (".png", ".svg", ".pdf"):
            bundle.write(path, path.relative_to(OUT))
    bundle.write(DATA / "figure_catalog.json", "figure_catalog.json")
savejson(
    OUT / "evidence_manifest.json",
    dict(
        campaigns=REPORT_SELECTION,
        sources=VERIFIED,
        original_report_hashes=OLD_HASHES,
        generated={
            str(p.relative_to(OUT)): sha(p)
            for p in OUT.rglob("*")
            if p.is_file()
            and p.name != "evidence_manifest.json"
            and "__pycache__" not in p.parts
        },
        planned_pages=PAGES,
    ),
)
print("PASS PDF generated; previous reports preserved:", PDF, flush=True)
