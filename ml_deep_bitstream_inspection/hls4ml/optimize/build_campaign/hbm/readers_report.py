#!/usr/bin/env python3
"""Two-round HBM reader comparison: titled figures, PDF and machine tables."""
import argparse
import csv
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import sys
import zipfile

os.environ.setdefault("MPLCONFIGDIR", "/tmp/hbm_reader_report_mpl")
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import TwoSlopeNorm
import numpy as np

try:
    import reportlab
except ImportError:
    sys.path.append("/usr/lib/python3/dist-packages")
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Image,
    Table,
    TableStyle,
    PageBreak,
)

REPO = next(
    parent
    for parent in Path(__file__).resolve().parents
    if (
        parent / "ML_Based_Deep_Bitstream_Inspection_for_Serverless_FPGAs_Report.pdf"
    ).exists()
)
OLD = REPO / "hls4ml/optimize/reports/optimizations/2026-11-08_hbm_resident_verdict"
REAL = json.loads(
    (
        REPO
        / "hls4ml/optimize/reports/optimizations/2026-10-22_gpu_opt_xla_concretefunction/data/real_inputs.json"
    ).read_text()
)
CAPACITY = dict(LUT=1303680, FF=2607360, BRAM_tiles=2016, DSP=9024, URAM=960)
PALETTE = {
    "OPT10": "#546779",
    "SCAN": "#2878B5",
    "GROUP4": "#3B9C73",
    "WINDOW128": "#9068AE",
    "GPU_P2P": "#E98A25",
}
LABELS = {
    "OPT10": "OPT_10 · previous gather",
    "SCAN": "OPT_14 · scan",
    "GROUP4": "OPT_15 · group 4",
    "WINDOW128": "OPT_16 · window 128",
    "GPU_P2P": "GPU_P2P",
}


def read(path):
    return json.loads(path.read_text())


class Report:
    def __init__(self, root, output):
        self.root, self.output = root, output
        self.data = output / "data"
        self.figures = output / "figures"
        self.figures.mkdir(exist_ok=True)
        self.stats = read(self.data / "statistics.json")
        self.rows = read(self.data / "trial_events.json")
        self.summary = read(self.data / "summary.json")
        self.configs = self.summary["configurations"]
        self.primary = [item["key"] for item in self.configs if item["primary"]]
        self.created = datetime.now().date().isoformat()
        self.styles = getSampleStyleSheet()
        self.styles.add(
            ParagraphStyle(
                "CaptionSmall", parent=self.styles["BodyText"], fontSize=9, leading=12
            )
        )
        self.story, self.catalog = [], []
        self.plot_queries = {}
        plt.rcParams.update(
            {
                "font.size": 10,
                "axes.spines.top": False,
                "axes.spines.right": False,
                "svg.fonttype": "none",
                "pdf.fonttype": 42,
                "axes.titleweight": "bold",
            }
        )

    def stat(
        self,
        config,
        case,
        metric="verdict_ms",
        quantile="median",
        session="pooled",
        mode="main",
    ):
        item = next(
            row
            for row in self.stats
            if (row["configuration"], row["case_id"], row["session"], row["mode"])
            == (config, case, session, mode)
        )
        value = item["metrics"].get(metric, {}).get(quantile)
        self.plot_queries[(config, case, metric, quantile, session, mode)] = value
        return value

    def text(self, value, style="BodyText"):
        self.story += [Paragraph(value, self.styles[style]), Spacer(1, 7)]

    def table(self, rows):
        table = Table(
            [
                [Paragraph(str(cell), self.styles["CaptionSmall"]) for cell in row]
                for row in rows
            ],
            repeatRows=1,
            hAlign="LEFT",
        )
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EAF0F6")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.grey),
                ]
            )
        )
        self.story += [table, Spacer(1, 10)]

    def figure(self, name, fig, title, caption):
        fig.suptitle(title, fontsize=15, fontweight="bold", y=0.995)
        fig.tight_layout(rect=(0, 0, 1, 0.93))
        for extension in ["png", "svg", "pdf"]:
            fig.savefig(
                self.figures / f"{name}.{extension}", dpi=180, bbox_inches="tight"
            )
        self.story.append(PageBreak())
        self.text(title, "Heading1")
        width, height = fig.get_size_inches()
        scale = min(750 / width, 360 / height)
        self.story.append(
            Image(
                str(self.figures / f"{name}.png"),
                width=width * scale,
                height=height * scale,
            )
        )
        self.story.append(Spacer(1, 8))
        self.text(caption, "CaptionSmall")
        self.catalog.append(dict(id=name, title=title, caption=caption))
        plt.close(fig)

    def grouped(self, ax, configs, cases, labels, metric="verdict_ms"):
        x = np.arange(len(cases))
        width = 0.8 / len(configs)
        for index, config in enumerate(configs):
            offset = (index - (len(configs) - 1) / 2) * width
            values = [self.stat(config, case, metric) for case in cases]
            ax.bar(
                x + offset,
                values,
                width * 0.95,
                color=PALETTE.get(config),
                label=LABELS.get(config, config),
            )
            if metric == "verdict_ms":
                ax.scatter(
                    x + offset,
                    [self.stat(config, case, metric, "p95") for case in cases],
                    marker="_",
                    color="black",
                    s=45,
                    zorder=5,
                )
                for session, marker in [("A", "o"), ("B", "D")]:
                    ax.scatter(
                        x + offset,
                        [
                            self.stat(config, case, metric, session=session)
                            for case in cases
                        ],
                        marker=marker,
                        s=15,
                        facecolor="white",
                        edgecolor="#23313F",
                        linewidth=0.6,
                        zorder=6,
                    )
        ax.set_xticks(x, labels)
        ax.grid(axis="y", alpha=0.2)

    def latency(self):
        fig, axes = plt.subplots(1, 2, figsize=(13.5, 4.9), sharey=True)
        for ax, subset in zip(axes, [REAL[:4], REAL[4:]]):
            self.grouped(
                ax,
                self.primary,
                [item["case_id"] for item in subset],
                [
                    f"{item['id']}\n{item['input_bytes'] / 2**20:.2f} MiB"
                    for item in subset
                ],
            )
            ax.set_ylabel("Accepted FPGA arm → FPGA verdict (ms)")
        axes[0].legend(fontsize=8, loc="upper left")
        axes[1].plot(
            [], [], color="black", marker="_", linestyle="", label="Pooled p95"
        )
        axes[1].plot(
            [],
            [],
            color="#23313F",
            marker="o",
            markerfacecolor="white",
            linestyle="",
            label="Round A median",
        )
        axes[1].plot(
            [],
            [],
            color="#23313F",
            marker="D",
            markerfacecolor="white",
            linestyle="",
            label="Round B median",
        )
        axes[1].legend(fontsize=8, loc="upper left")
        self.figure(
            "01_verdict_latency",
            fig,
            "1 · HBM-resident verdict latency: predeclared reader settings",
            "Bars: pooled empirical medians with equal weight from two independent programming rounds "
            "(200 measured calls each after 20 warmups). Black ticks: pooled p95. Hollow circles/diamonds: "
            "separate round medians. Predeclared candidate settings are scan, coalescing group 4 and "
            "outstanding window 128. Controls are freshly programmed OPT_10 and GPU_P2P, not host-fed images. "
            "File access, HBM placement, readback, compilation and warmup are outside the primary interval.",
        )

    def findings(self):
        self.story.append(PageBreak())
        self.text("Measured findings and tradeoffs", "Heading1")
        self.text(
            "The table summarizes the eight real workloads. Ratios use balanced pooled medians; "
            "a ratio above 1× favors the candidate. The geometric mean gives every workload equal "
            "weight. It is a summary of these inputs, not an extrapolation to other bitstreams."
        )
        table = [
            [
                "FPGA configuration",
                "OPT_10 / candidate",
                "GPU_P2P / candidate",
                "Faster than OPT_10",
                "Largest A→B change",
            ]
        ]
        for key in [item for item in self.primary if item != "GPU_P2P"]:
            baseline_ratios = [
                self.stat("OPT10", case["case_id"]) / self.stat(key, case["case_id"])
                for case in REAL
            ]
            gpu_ratios = [
                self.stat("GPU_P2P", case["case_id"]) / self.stat(key, case["case_id"])
                for case in REAL
            ]
            changes = [
                self.stat(key, case["case_id"], session="B")
                / self.stat(key, case["case_id"], session="A")
                - 1
                for case in REAL
            ]
            table.append(
                [
                    LABELS[key],
                    f"{np.exp(np.mean(np.log(baseline_ratios))):.3f}× geometric mean",
                    f"{np.exp(np.mean(np.log(gpu_ratios))):.3f}× geometric mean",
                    f"{sum(ratio > 1 for ratio in baseline_ratios)}/8 workloads",
                    f"{max(changes, key=abs):+.2%}",
                ]
            )
        self.table(table)
        self.text(
            "Read policy trades transaction count against traffic: scan transfers the whole input, "
            "coalescing transfers gaps between selected samples, and individual gather transfers only "
            "selected cache-line words. The latency, traffic and stall figures test which tradeoff wins. "
            "The full setting sweeps remain visible even when they do not improve performance."
        )
        self.text(
            "Two programming sessions are retained separately. An A→B change is an observed difference "
            "under the reversed schedule; its physical cause is not established by these measurements. "
            "No latency-only outlier rejection or selective repeat is applied."
        )

    def speedups(self):
        fig, axes = plt.subplots(1, 2, figsize=(13.5, 4.8))
        x = np.arange(8)
        for ax, numerator, configs in [
            (
                axes[0],
                "OPT10",
                [key for key in self.primary if key not in ["OPT10", "GPU_P2P"]],
            ),
            (axes[1], "GPU_P2P", [key for key in self.primary if key != "GPU_P2P"]),
        ]:
            if not configs:
                ax.text(
                    0.5,
                    0.5,
                    "No accepted candidate readers",
                    ha="center",
                    transform=ax.transAxes,
                )
                continue
            width = 0.8 / len(configs)
            for index, config in enumerate(configs):
                ratio = [
                    self.stat(numerator, case["case_id"])
                    / self.stat(config, case["case_id"])
                    for case in REAL
                ]
                ax.bar(
                    x + (index - (len(configs) - 1) / 2) * width,
                    ratio,
                    width * 0.95,
                    color=PALETTE[config],
                    label=LABELS[config],
                )
            ax.axhline(1, color="black", linestyle="--", linewidth=1)
            ax.set_xticks(x, [case["id"] for case in REAL])
            ax.set_ylabel(f"{numerator} median / compared FPGA median (×)")
            ax.legend(fontsize=7)
            ax.grid(axis="y", alpha=0.2)
        self.figure(
            "02_speedups",
            fig,
            "2 · Speedup against previous HBM gather and GPU_P2P",
            "Above 1× means the compared FPGA configuration is faster than the numerator. Ratios use "
            "equally weighted two-round pooled medians, not ratios of individual unpaired trials. "
            "Per-round results remain available in the appendix and machine-readable tables.",
        )

    def timelines(self):
        for case in [REAL[index] for index in [0, 3, 7]]:
            fig, ax = plt.subplots(figsize=(13, 6.2))
            labels, position = [], 0
            for config in self.primary:
                samples = [
                    row
                    for row in self.rows
                    if row["configuration"] == config
                    and row["case_id"] == case["case_id"]
                    and row["mode"] == "main"
                ]
                middle = self.stat(config, case["case_id"])
                row = min(samples, key=lambda item: abs(item["verdict_ms"] - middle))
                if config == "GPU_P2P":
                    lanes = [
                        (
                            "HBM delivery",
                            "hbm_return_start_ms",
                            "hbm_return_end_ms",
                            "#65A5CE",
                        ),
                        (
                            "P2P forwarding",
                            "gpu_forward_start_ms",
                            "gpu_forward_end_ms",
                            "#E98A25",
                        ),
                        (
                            "Framework",
                            "gpu_framework_begin_ms",
                            "gpu_framework_end_ms",
                            "#AA67A2",
                        ),
                        (
                            "Publication call",
                            "gpu_framework_end_ms",
                            "gpu_publication_complete_ms",
                            "#BB9BB6",
                        ),
                        (
                            "Autonomous polling",
                            "poll_requests_start_ms",
                            "poll_requests_end_ms",
                            "#9A9A9A",
                        ),
                    ]
                else:
                    lanes = [
                        (
                            "HBM delivery",
                            "hbm_return_start_ms",
                            "hbm_return_end_ms",
                            "#65A5CE",
                        ),
                        ("Pixels", "pixel_start_ms", "pixel_end_ms", "#4BAE91"),
                        (
                            "CNN input",
                            "cnn_input_start_ms",
                            "cnn_input_end_ms",
                            "#8975BD",
                        ),
                    ]
                for index, (label, begin, end, color) in enumerate(lanes):
                    ax.barh(
                        position + index,
                        row[end] - row[begin],
                        left=row[begin],
                        height=0.7,
                        color=color,
                    )
                    labels.append(f"{LABELS[config]} · {label}")
                ax.plot(
                    [row["verdict_ms"], row["verdict_ms"]],
                    [position - 0.4, position + len(lanes) - 0.6],
                    color="#B32B2B",
                    linestyle="--",
                    linewidth=1.3,
                )
                position += len(lanes) + 1
                labels.append("")
            ax.set_yticks(range(len(labels)), labels, fontsize=8)
            ax.invert_yaxis()
            ax.set_xlabel("Milliseconds from accepted FPGA arm")
            ax.plot(
                [],
                [],
                color="#B32B2B",
                linestyle="--",
                label="Verdict available at FPGA",
            )
            ax.legend(loc="upper right", bbox_to_anchor=(1.0, 1.08), fontsize=8)
            ax.grid(axis="x", alpha=0.2)
            self.figure(
                f"03_{case['id']}_timeline",
                fig,
                f"3 · {case['id']}: memory delivery, CNN overlap and GPU work",
                "Each configuration uses the measured trial nearest its pooled median; the selected trial retains "
                "its programming-session identity in data/trial_events.json. Lanes overlap and must not be summed. "
                "CNN input span includes input starvation and is not compute-only inference. HBM delivery and "
                "P2P forwarding are separate overlapping lanes. GPU framework and "
                "publication lanes are host-synchronized spans aligned through MMIO clock brackets; publication "
                "call completion can follow FPGA verdict acceptance. Polling overlaps waiting for the verdict.",
            )

    def traffic(self):
        fig, axes = plt.subplots(1, 2, figsize=(13.5, 4.8))
        keys = [case["case_id"] for case in REAL]
        labels = [case["id"] for case in REAL]
        self.grouped(axes[0], self.primary, keys, labels, "logical_requests")
        self.grouped(axes[1], self.primary, keys, labels, "requested_bytes")
        axes[0].set_yscale("log")
        axes[0].set_ylabel("Logical HBM read requests (log scale)")
        axes[1].yaxis.set_major_formatter(
            matplotlib.ticker.FuncFormatter(lambda value, _: f"{value / 2**20:g}")
        )
        axes[1].set_ylabel("Requested HBM payload (MiB)")
        axes[0].legend(fontsize=7)
        self.figure(
            "04_traffic",
            fig,
            "4 · Read-request reduction versus additional HBM traffic",
            "Left: accepted logical requests, using a logarithmic count axis. Right: requested payload. "
            "Coalescing reads intervening unselected bytes to reduce descriptor count. Scan requests the complete "
            "input; individual gather suppresses duplicate selected words. GPU counts are completed bulk chunks, "
            "each corresponding to one logical HBM read; mailbox reads are separate PCIe traffic. Native Coyote "
            "can split descriptors into smaller internal operations. These counts/bytes are not physical HBM-wire traffic.",
        )

    def bottlenecks(self):
        candidates = [key for key in self.primary if key not in ["OPT10", "GPU_P2P"]]
        if not candidates:
            return
        categories = [
            ("request_stalls", "Request ready stalls"),
            ("credit_stalls", "Application credit stalls"),
            ("response_backpressure", "Response backpressure"),
            ("cnn_starvation", "CNN input starvation"),
            ("cnn_backpressure", "CNN input backpressure"),
            ("pixel_producer_backpressure", "Pixel producer blocked"),
        ]
        fig, axes = plt.subplots(2, 3, figsize=(13.5, 6.1))
        for ax, (metric, title) in zip(axes.flat, categories):
            matrix = np.array(
                [
                    [
                        100
                        * self.stat(key, case["case_id"], "counter_" + metric)
                        / max(
                            self.stat(key, case["case_id"], "counter_active_cycles"), 1
                        )
                        for case in REAL
                    ]
                    for key in candidates
                ]
            )
            image = ax.imshow(matrix, aspect="auto", vmin=0, vmax=100, cmap="YlOrRd")
            ax.set_xticks(range(8), [case["id"] for case in REAL], fontsize=8)
            ax.set_yticks(
                range(len(candidates)), [LABELS[key] for key in candidates], fontsize=8
            )
            ax.set_title(title, fontsize=10)
            fig.colorbar(image, ax=ax, label="% active cycles", shrink=0.8)
        self.figure(
            "05_bottlenecks",
            fig,
            "5 · Measured bottleneck counters in the candidate readers",
            "Cells use the median counter divided by median active cycles across equally weighted rounds. "
            "Counters reset at start and accumulate while busy after the start pulse, through successful completion. "
            "CNN starvation counts ready without valid before 65,536 inputs; CNN backpressure includes normal "
            "CNN initiation-interval limits. Categories can overlap and are not additive. Old OPT_10/GPU_P2P "
            "lack comparable bulk counters and are unavailable here, not zero. Outstanding/FIFO peaks are exported separately.",
        )

    def resources(self):
        selected = read(self.root / "hardware_selection.json")
        result = {}
        for variant in [10, 14, 15, 16, 11]:
            if str(variant) not in selected:
                continue
            image = Path(selected[str(variant)]["path"])
            hierarchy = image.parents[1] / "reports/shell_utilization_hierarchical.rpt"
            area = {}
            for line in hierarchy.read_text().splitlines():
                cells = [cell.strip() for cell in line.split("|")[1:-1]]
                if cells and cells[0] in ["cyt_top", "inst_user_wrapper_0"]:
                    area["full" if cells[0] == "cyt_top" else "application"] = dict(
                        LUT=int(cells[4]),
                        FF=int(cells[8]),
                        BRAM_tiles=int(cells[9]) + int(cells[10]) / 2,
                        URAM=int(cells[11]),
                        DSP=int(cells[12]),
                    )
            result[str(variant)] = area
        (self.data / "resources.json").write_text(json.dumps(result, indent=2))
        variants = list(result)
        colors_for = [
            PALETTE[
                {10: "OPT10", 14: "SCAN", 15: "GROUP4", 16: "WINDOW128", 11: "GPU_P2P"}[
                    int(key)
                ]
            ]
            for key in variants
        ]
        for scope in ["application", "full"]:
            fig, axes = plt.subplots(1, 5, figsize=(13.5, 4.8))
            for ax, resource in zip(axes, CAPACITY):
                values = [result[key][scope][resource] for key in variants]
                bars = ax.bar(range(len(values)), values, color=colors_for)
                ax.bar_label(
                    bars,
                    labels=[f"{value:g}" for value in values],
                    rotation=90,
                    padding=4,
                    fontsize=8,
                )
                ax.set_xticks(
                    range(len(values)),
                    [f"OPT_{key}" for key in variants],
                    rotation=45,
                    fontsize=8,
                )
                ax.set_ylim(0, max(max(values) * 1.45, 1))
                ax.set_title(resource.replace("_tiles", " tiles"))
                ax.set_ylabel("Routed count")
                secondary = ax.secondary_yaxis(
                    "right",
                    functions=(
                        lambda x, c=CAPACITY[resource]: x / c * 100,
                        lambda x, c=CAPACITY[resource]: x * c / 100,
                    ),
                )
                secondary.set_ylabel("U55C utilization (%)", fontsize=8)
                secondary.tick_params(labelsize=8)
            self.figure(
                f"06_{scope}_resources",
                fig,
                f"6 · Routed resource cost: {scope} scope",
                "Counts at left; percentage of U55C capacity at right. Application is inst_user_wrapper_0; "
                "full design includes the shell. BRAM tiles = RAMB36 + 0.5×RAMB18. Runtime settings share "
                "one image, so coalescing/window settings have the same area. GPU_P2P counts cover its FPGA "
                "implementation only, excluding MI210 area. Model, reuse factors, CNN FIFOs and clocks are unchanged.",
            )

    def sweeps(self):
        for prefix, title in [
            ("GROUP", "Complete coalescing sweep"),
            ("WINDOW", "Complete outstanding-window sweep"),
        ]:
            keys = ["OPT10"] + [
                item["key"] for item in self.configs if item["key"].startswith(prefix)
            ]
            if len(keys) == 1:
                continue
            fig, ax = plt.subplots(figsize=(13, 4.7))
            for key in keys:
                ax.plot(
                    range(8),
                    [self.stat(key, case["case_id"]) for case in REAL],
                    "o-",
                    label=LABELS.get(key, key),
                )
            ax.set_xticks(range(8), [case["id"] for case in REAL])
            ax.set_ylabel("Accepted arm → FPGA verdict median (ms)")
            ax.legend()
            ax.grid(alpha=0.2)
            self.figure(
                f"A1_{prefix.lower()}_sweep",
                fig,
                f"A1 · {title}",
                "All predeclared settings are shown, including settings that do not improve latency. "
                "Two independently programmed rounds contribute equally. Lines connect workload categories "
                "for readability; they are not an interpolation model. Primary settings remain group 4/window 128.",
            )
        cases = [
            f"synthetic_{size}" for size in [4194304, 16777216, 67108864, 134217664]
        ]
        fig, ax = plt.subplots(figsize=(13, 4.8))
        self.grouped(
            ax, self.primary, cases, ["4 MiB", "16 MiB", "64 MiB", "128 MiB − 64 B"]
        )
        ax.set_ylabel("Accepted arm → FPGA verdict (ms)")
        ax.legend(fontsize=8)
        self.figure(
            "A2_synthetic_latency",
            fig,
            "A2 · Established synthetic workloads",
            "Same pinned synthetic input identities as the previous HBM report, 400 measured calls per "
            "configuration/workload. The largest input preserves the established 128 MiB−64 B convention. "
            "Circles/diamonds show round medians and black ticks pooled p95. No synthetic exception is substituted.",
        )
        fig, ax = plt.subplots(figsize=(13, 4.8))
        for index, key in enumerate([key for key in self.primary if key != "GPU_P2P"]):
            values = [
                self.stat("GPU_P2P", case) / self.stat(key, case) for case in cases
            ]
            ax.bar(
                np.arange(4) + (index - (len(self.primary) - 2) / 2) * 0.16,
                values,
                0.15,
                color=PALETTE[key],
                label=LABELS[key],
            )
        ax.axhline(1, color="black", linestyle="--")
        ax.set_xticks(range(4), ["4 MiB", "16 MiB", "64 MiB", "128 MiB − 64 B"])
        ax.set_ylabel("GPU_P2P median / FPGA median (×)")
        ax.legend(fontsize=8)
        self.figure(
            "A2_synthetic_speedup",
            fig,
            "A2 · Synthetic FPGA speedup against fresh GPU_P2P",
            "Ratios above 1× favor the compared FPGA path. Balanced pooled medians use both rounds; "
            "programming-state variability remains visible in the latency and per-session figures.",
        )

    def appendix(self):
        available = {row["case_id"] for row in self.rows if row["mode"] == "diagnostic"}
        cases = [
            f"boundary_{size}"
            for size in [4095, 4096, 4097, 1048576, 2097151, 2097152, 2097153]
        ]
        cases += [f"smoke_{size}" for size in [4194240, 4194241, 4194242]]
        cases = [case for case in cases if case in available]
        fig, ax = plt.subplots(figsize=(13.5, 4.8))
        for key in self.primary:
            ax.plot(
                range(len(cases)),
                [self.stat(key, case, mode="diagnostic") for case in cases],
                "o-",
                color=PALETTE[key],
                label=LABELS[key],
            )
        ax.set_xticks(
            range(len(cases)),
            [case.split("_")[-1] + " B" for case in cases],
            rotation=30,
        )
        ax.set_ylabel("Diagnostic verdict median (ms)")
        ax.legend(fontsize=8)
        ax.grid(alpha=0.2)
        self.figure(
            "A3_small_inputs",
            fig,
            "A3 · Small inputs, page boundaries and the former preprocessing cutoff",
            "Separate deterministic boundary inputs and established cutoff inputs; 20 measured calls per "
            "round after two warmups. Raw zero padding becomes normalized 1.0. These diagnostics do not "
            "enter the primary real/synthetic comparisons. Build validation also covers empty/short inputs "
            "and compares every fixed-point pixel, all runtime settings, partial chunks and page splits.",
        )
        keys = [item["key"] for item in self.configs]
        fig, ax = plt.subplots(figsize=(13.5, 5.8))
        matrix = np.array(
            [
                [
                    100
                    * (
                        self.stat(key, case["case_id"], session="B")
                        / self.stat(key, case["case_id"], session="A")
                        - 1
                    )
                    for case in REAL
                ]
                for key in keys
            ]
        )
        bound = max(float(np.max(np.abs(matrix))), 5)
        image = ax.imshow(
            matrix,
            aspect="auto",
            cmap="RdBu_r",
            norm=TwoSlopeNorm(vmin=-bound, vcenter=0, vmax=bound),
        )
        ax.set_xticks(range(8), [case["id"] for case in REAL])
        ax.set_yticks(range(len(keys)), keys)
        for y in range(len(keys)):
            for x in range(8):
                ax.text(
                    x, y, f"{matrix[y,x]:+.1f}%", ha="center", va="center", fontsize=8
                )
        fig.colorbar(image, ax=ax, label="Round B / round A median − 1 (%)")
        self.figure(
            "A4_sessions",
            fig,
            "A4 · Programming-session variability: every setting",
            "The second round reverses image, setting and workload order. Changes above 5% are findings, "
            "not grounds to discard data or rerun until timings agree. The previous OPT_10 campaign found "
            "up to 9.825% initial-to-closing variation, with stable within-program repeats. Its physical cause "
            "was not proven. Current per-round medians and raw identities are preserved alongside pooled values.",
        )
        fig, axes = plt.subplots(1, 2, figsize=(13.5, 4.8))
        for key in self.primary:
            rows = [
                row
                for row in self.rows
                if row["mode"] == "main"
                and row["configuration"] == key
                and row["sweep"] == "real"
            ]
            axes[0].scatter(
                [row["input_bytes"] / 2**20 for row in rows],
                [row["verdict_ms"] for row in rows],
                s=5,
                alpha=0.15,
                color=PALETTE[key],
                label=LABELS[key],
            )
            for case in REAL:
                series = sorted(
                    row["verdict_ms"]
                    for row in rows
                    if row["case_id"] == case["case_id"]
                )
                axes[1].plot(
                    series,
                    np.arange(1, len(series) + 1) / len(series),
                    color=PALETTE[key],
                    alpha=0.5,
                )
        axes[0].set_xlabel("Real input size (MiB)")
        axes[0].set_ylabel("Verdict latency (ms)")
        axes[0].legend(fontsize=7)
        axes[1].set_xlabel("Verdict latency (ms)")
        axes[1].set_ylabel("Per-workload empirical cumulative fraction")
        self.figure(
            "A5_distributions",
            fig,
            "A5 · Accepted real-input trials and their distributions",
            "All accepted measured calls are retained. Each plotted workload/configuration has 400 calls "
            "with equal programming-session weight. ECDFs are per workload, not pooled confidence intervals.",
        )

    def session_table_and_peaks(self):
        self.story.append(PageBreak())
        self.text("Appendix · Absolute per-programming-session medians", "Heading1")
        self.text(
            "Each cell is round A / round B in milliseconds. Each number uses 200 measured calls after "
            "20 warmups. The main figures use equally weighted pooled data; both sessions remain available."
        )
        table = [["Configuration", *[case["id"] for case in REAL]]]
        for config in self.configs:
            key = config["key"]
            cells = [key]
            for case in REAL:
                a = self.stat(key, case["case_id"], session="A")
                b = self.stat(key, case["case_id"], session="B")
                cells.append(f"{a:.3f} / {b:.3f}")
            table.append(cells)
        self.table(table)
        candidates = [key for key in self.primary if key not in ["OPT10", "GPU_P2P"]]
        if not candidates:
            return
        fig, axes = plt.subplots(1, 2, figsize=(13.5, 4.7))
        for ax, metric, label in [
            (
                axes[0],
                "counter_peak_outstanding",
                "Peak application outstanding requests",
            ),
            (axes[1], "counter_pixel_fifo_peak", "Peak pixel-FIFO occupancy (entries)"),
        ]:
            for key in candidates:
                ax.plot(
                    range(8),
                    [self.stat(key, case["case_id"], metric) for case in REAL],
                    "o-",
                    color=PALETTE[key],
                    label=LABELS[key],
                )
            ax.set_xticks(range(8), [case["id"] for case in REAL])
            ax.set_ylabel(label)
            ax.set_ylim(bottom=0)
            ax.legend(fontsize=8)
            ax.grid(alpha=0.2)
        self.figure(
            "A5b_peaks",
            fig,
            "A5 · Outstanding-request and pixel-FIFO peaks",
            "Median of per-frame peaks across both rounds. Application credits retain a request until "
            "both response data and completion have returned. Limits are 4 logical scan chunks, "
            "32 coalesced descriptors and 128 individual requests for the primary settings. "
            "These are not native Coyote PMTU counts or physical memory-controller occupancy. "
            "The pixel FIFO has 32 entries. Old controls lack comparable peak counters and are omitted.",
        )

    def bandwidth(self):
        fig, axes = plt.subplots(1, 2, figsize=(13.5, 4.8))
        for ax, metric in zip(
            axes, ["requested_payload_GBps", "effective_inspection_GBps"]
        ):
            for key in self.primary:
                ax.plot(
                    range(8),
                    [self.stat(key, case["case_id"], metric) for case in REAL],
                    "o-",
                    color=PALETTE[key],
                    label=LABELS[key],
                )
            ax.set_xticks(range(8), [case["id"] for case in REAL])
            ax.legend(fontsize=7)
            ax.grid(alpha=0.2)
        axes[0].set_ylabel("Requested payload / first-to-last HBM delivery (GB/s)")
        axes[1].set_ylabel("Raw input bytes / verdict latency (GB/s)")
        self.figure(
            "A6_bandwidth",
            fig,
            "A6 · Requested-payload rate versus effective inspection throughput",
            "Left is requested payload divided by the accepted HBM-return span, including gaps. Right uses "
            "the full raw input size divided by verdict latency. Sampling can make effective inspection "
            "throughput exceed actual memory traffic rate. Neither axis measures physical HBM-wire bandwidth. "
            "MB/GB use decimal units; input labels elsewhere use binary MiB.",
        )

    def controls_and_gpu(self):
        old = read(OLD / "data/statistics.json")
        fig, axes = plt.subplots(1, 2, figsize=(13.5, 4.8))
        for ax, key, old_label in zip(
            axes, ["OPT10", "GPU_P2P"], ["FPGA_HLS4ML", "GPU_P2P"]
        ):
            previous = [
                next(
                    row["metrics"]["verdict_ms"]["median"]
                    for row in old
                    if row["variant"] == old_label and row["case_id"] == case["case_id"]
                )
                for case in REAL
            ]
            ax.bar(
                np.arange(8) - 0.25,
                previous,
                0.23,
                color="#A7B3BE",
                label="Archived · 2026-11-08",
            )
            for offset, session, color in [(0, "A", "#5A8FB3"), (0.25, "B", "#98B9CE")]:
                ax.bar(
                    np.arange(8) + offset,
                    [self.stat(key, case["case_id"], session=session) for case in REAL],
                    0.23,
                    color=color,
                    label=f"Fresh round {session}",
                )
            ax.set_title(key)
            ax.set_xticks(range(8), [case["id"] for case in REAL])
            ax.set_ylabel("HBM start → verdict median (ms)")
            ax.legend(fontsize=7)
        self.figure(
            "A7_fresh_controls",
            fig,
            "A7 · Archived and fresh HBM-resident controls",
            "Archived values use the initial accepted run from the 2026-11-08 HBM report; fresh controls "
            "use the current two-round campaign. Origins/endpoints and raw input identities match. "
            "The old host-fed PCIe baseline is not substituted. Dates differ from report creation dates; "
            "programming/session conditions and historical variation remain relevant.",
        )
        profiles = read(OLD / "data/gpu_profiles.json")
        selected = [REAL[index] for index in [0, 3, 7]]
        fig, ax = plt.subplots(figsize=(13, 4.7))
        for offset, kind, color, label in [
            (-0.26, "kernel_sum_ms", "#4BAE91", "Historical kernel sum"),
            (0, "device_span_ms", "#8975BD", "Historical device span"),
            (0.26, "framework_ms", "#E98A25", "Fresh synchronized framework call"),
        ]:
            numbers = []
            for case in selected:
                if kind == "framework_ms":
                    numbers.append(self.stat("GPU_P2P", case["case_id"], kind))
                else:
                    samples = next(
                        item["samples"]
                        for item in profiles
                        if item["case_id"] == case["case_id"]
                    )
                    numbers.append(np.median([sample[kind] for sample in samples]))
            ax.bar(np.arange(3) + offset, numbers, 0.24, color=color, label=label)
        ax.set_xticks(range(3), [case["id"] for case in selected])
        ax.set_ylabel("Fused preprocessing + inference span (ms)")
        ax.legend()
        self.figure(
            "A8_gpu_framework",
            fig,
            "A8 · GPU framework timing and dated isolated device diagnostics",
            "Historical isolated profiles were measured 2026-11-08 after validated P2P delivery, five calls "
            "per selected input: roughly 23 kernels, 0.185 ms kernel sum and 0.190 ms first-to-last kernel "
            "span. Fresh framework values include dispatch and synchronization and use unprofiled hardware "
            "calls. These scopes and sample sets differ. No TensorFlow profiler ran inside the current live "
            "mailbox process; the prior integrated-profiler incompatibility is not repeated.",
        )

    def validation(self):
        self.story.append(PageBreak())
        self.text("Validation, exact identities and limitations", "Heading1")
        table = [["Configuration", "Round A admission", "Round B admission"]]
        for config in self.configs:
            statuses = [
                read(
                    self.root
                    / "hardware"
                    / session
                    / config["key"]
                    / "admission/status.json"
                )
                for session in ["A", "B"]
            ]
            assert all(
                item["status"] == "passed" and item["calls"] == 520 for item in statuses
            )
            table.append([config["key"], "520/520 passed", "520/520 passed"])
        self.table(table)
        self.text(
            "Every main cell contains 20 warmups and 200 measured calls per round. Exact quantized CNN "
            "logits, fixed-point preprocessing pixels, input hashes, runtime settings, status, trial IDs, "
            "event-valid bits and descriptor/word/completion counts are checked. GPU uses its own FP32 CPU "
            "reference with 1e-4 absolute + 1e-4 relative tolerance and matching threshold verdict; FPGA "
            "and GPU logits are not required to match each other."
        )
        self.text(
            "HBM is read back before and after each workload and restored to card residency after LOCAL_SYNC. "
            "GPU admissions check external-DMA bytes before inference and reject delayed/stale publication. "
            "Successful drain is required before reuse. Full-drain host observation is exported separately "
            "and includes observation delay; primary verdict timing uses the FPGA-local event."
        )
        self.text(
            "Requested bytes and logical credits are application-interface measurements, not physical HBM "
            "wire traffic or memory-controller occupancy. Request/credit/response/CNN stalls overlap. "
            "Coyote native capacity is 128 outstanding/128 active translations only in OPT_16; cache "
            "orders remain unchanged. Runtime windows share that capacity. New readers preserve the accepted "
            "250 MHz application and 450 MHz HBM clocks, one application-memory stream and OPT_6 CNN."
        )
        self.text(
            "The host preloads HBM and emulates an integrated CPU for control. This experiment does not "
            "implement a soft CPU, PR enforcement or fully hostless GPU execution. GPU inference remains "
            "CPU dispatched. No file-to-verdict result appears in this HBM-resident comparison. "
            "All raw trials, calibration, image hashes, programming logs, build/board gates and repair "
            "history are preserved in the dated campaign root."
        )
        if self.summary["missing_variants"]:
            self.text(
                "<b>Missing candidates:</b> "
                + str(self.summary["missing_variants"])
                + ". See build summary and repair journal; no replacement setting was selected."
            )

    def build(self):
        self.text("HBM reader optimizations", "Title")
        self.text(
            "Report created "
            + self.created
            + " · Measurements "
            + ", ".join(self.summary["dates"])
        )
        self.text(
            "Compare sequential scan, coalesced gather and increased request concurrency against fresh "
            "HBM-resident FPGA/GPU controls. Primary settings were declared before measurement; full sweeps "
            "remain visible. Two independent programming rounds reverse image, setting and workload order."
        )
        self.text(
            "FPGA designs preserve the OPT_6 quantized CNN, reuse factors, FIFO depths and first-pixel guard. "
            "GPU_P2P uses accepted R06 XLA compilation + cached ConcreteFunction FP32, batch one. "
            "U55C device2 (81:00.0, NUMA1) connects through PCIe Gen3 ×16; MI210 GPU0 "
            "(03:00.0, NUMA0) uses Gen4 ×16. The host preloads HBM outside timing and emulates embedded-core control."
        )
        self.text(
            f"Accepted primary measured calls: <b>{self.summary['primary_measured_calls']:,}</b>. "
            "Each normal workload/configuration contributes 400 calls, equally weighted across rounds. "
            "Any inter-round change is reported; unexpected latency alone never triggers selective reruns."
        )
        rows = [["Input", "MiB", *[LABELS[key] for key in self.primary]]]
        for case in REAL:
            rows.append(
                [
                    case["id"],
                    f"{case['input_bytes']/2**20:.2f}",
                    *[
                        f"{self.stat(key,case['case_id']):.3f} ms"
                        for key in self.primary
                    ],
                ]
            )
        self.table(rows)
        self.findings()
        self.latency()
        self.speedups()
        self.timelines()
        self.traffic()
        self.bottlenecks()
        self.resources()
        self.sweeps()
        self.appendix()
        self.session_table_and_peaks()
        self.bandwidth()
        self.controls_and_gpu()
        self.validation()
        page = landscape(A4)
        document = SimpleDocTemplate(
            str(self.output / "hbm_reader_optimizations_report.pdf"),
            pagesize=page,
            leftMargin=40,
            rightMargin=40,
            topMargin=35,
            bottomMargin=35,
            title="HBM reader optimizations — " + self.created,
        )

        def footer(canvas, doc):
            canvas.setFont("Helvetica", 8)
            canvas.drawString(
                40, 18, "HBM reader optimization campaign · " + self.created
            )
            canvas.drawRightString(page[0] - 40, 18, str(doc.page))

        document.build(self.story, onFirstPage=footer, onLaterPages=footer)
        (self.data / "figure_catalog.json").write_text(
            json.dumps(self.catalog, indent=2)
        )
        queries = [
            dict(
                configuration=key[0],
                case_id=key[1],
                metric=key[2],
                quantile=key[3],
                session=key[4],
                mode=key[5],
                value=value,
            )
            for key, value in self.plot_queries.items()
        ]
        (self.data / "figure_values.json").write_text(json.dumps(queries, indent=2))
        shutil.copy2(__file__, self.output / "build_report.py")
        with zipfile.ZipFile(
            self.output / "standalone_figures.zip", "w", zipfile.ZIP_DEFLATED
        ) as archive:
            for path in sorted(self.figures.iterdir()):
                archive.write(path, path.relative_to(self.output))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    Report(args.root.resolve(), args.output.resolve()).build()
