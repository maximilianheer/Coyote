"""Reviewed CPU-only report with standalone, titled figure exports."""

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import sys
import zipfile

os.environ.setdefault("MPLCONFIGDIR", "/tmp/cpu_dram_report_mpl")
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
    PageBreak,
    Table,
    TableStyle,
    Image,
)

from common import REPO, cases, save

COLORS = {"FP32": "#2878B5", "QKERAS_W8A8": "#D78326"}
LABELS = {
    "FP32": "Original FP32 · CPU XLA",
    "QKERAS_W8A8": "QKeras W8A8 · CPU XLA, float kernels",
}


class Report:
    def __init__(self, root, output):
        self.root, self.output = root, output
        self.stats = json.loads((output / "data/statistics.json").read_text())
        self.rows = json.loads((output / "data/trial_events.json").read_text())
        self.summary = json.loads((output / "data/summary.json").read_text())
        self.real = sorted(
            [item for item in cases() if item["scope"] == "real"],
            key=lambda item: item["bytes"],
        )
        self.synthetic = sorted(
            [item for item in cases() if item["scope"] == "synthetic"],
            key=lambda item: item["bytes"],
        )
        self.models = ["FP32", "QKERAS_W8A8"]
        self.created = datetime.now().date().isoformat()
        self.figures = output / "figures"
        self.figures.mkdir(exist_ok=True)
        self.styles = getSampleStyleSheet()
        self.styles.add(
            ParagraphStyle(
                "Caption", parent=self.styles["BodyText"], fontSize=9, leading=12
            )
        )
        self.story, self.catalog, self.queries = [], [], []
        plt.rcParams.update(
            {
                "font.size": 10,
                "axes.spines.top": False,
                "axes.spines.right": False,
                "svg.fonttype": "none",
                "pdf.fonttype": 42,
            }
        )

    def text(self, value, style="BodyText"):
        self.story.extend([Paragraph(value, self.styles[style]), Spacer(1, 7)])

    def table(self, rows):
        table = Table(
            [
                [Paragraph(str(cell), self.styles["Caption"]) for cell in row]
                for row in rows
            ],
            repeatRows=1,
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
        self.story.extend([table, Spacer(1, 10)])

    def stat(
        self,
        model,
        case,
        mode="total",
        cache="input_cold",
        session="pooled",
        metric="median_ms",
    ):
        item = next(
            row
            for row in self.stats
            if (
                row["model"],
                row["case_id"],
                row["mode"],
                row["cache_scope"],
                row["session"],
            )
            == (model, case, mode, cache, session)
        )
        value = item[metric]
        self.queries.append(
            dict(
                model=model,
                case_id=case,
                mode=mode,
                cache=cache,
                session=session,
                metric=metric,
                value=value,
            )
        )
        return value

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
        scale = min(750 / width, 355 / height)
        self.story.append(
            Image(
                str(self.figures / f"{name}.png"),
                width=width * scale,
                height=height * scale,
            )
        )
        self.story.append(Spacer(1, 8))
        self.text(caption, "Caption")
        self.catalog.append(dict(name=name, title=title, caption=caption))
        plt.close(fig)

    def bars(self, ax, workloads, cache="input_cold", mode="total"):
        x = np.arange(len(workloads))
        for offset, model in [(-0.18, "FP32"), (0.18, "QKERAS_W8A8")]:
            values = [self.stat(model, item["id"], mode, cache) for item in workloads]
            ax.bar(x + offset, values, 0.33, color=COLORS[model], label=LABELS[model])
            ax.scatter(
                x + offset,
                [
                    self.stat(model, item["id"], mode, cache, metric="p95_ms")
                    for item in workloads
                ],
                marker="_",
                s=60,
                color="black",
                zorder=4,
            )
            for session, marker in [("A", "o"), ("B", "D")]:
                ax.scatter(
                    x + offset,
                    [
                        self.stat(model, item["id"], mode, cache, session)
                        for item in workloads
                    ],
                    marker=marker,
                    s=20,
                    facecolors="white",
                    edgecolors="#263645",
                    zorder=5,
                )
        ax.set_ylabel("Completed CPU latency (ms)")
        ax.grid(axis="y", alpha=0.2)

    def latency(self):
        fig, ax = plt.subplots(figsize=(13, 4.8))
        self.bars(ax, self.real)
        ax.set_xticks(
            range(8),
            [
                f"R{i+1}\n{item['bytes']/2**20:.2f} MiB"
                for i, item in enumerate(self.real)
            ],
        )
        ax.set_ylabel("DRAM raw input → CPU verdict (ms)")
        ax.legend(fontsize=8, loc="upper center", bbox_to_anchor=(0.5, 1.14), ncol=2)
        self.figure(
            "01_real_verdict_latency",
            fig,
            "1 · Single-core CPU verdict latency: cold raw input",
            "Raw input is explicitly flushed from CPU data caches before each call; model/code are warmed. "
            "Bars are pooled medians, black ticks p95, white circles round A medians and diamonds round B medians. "
            "Each workload/model contributes 400 measured calls, equally split across rounds after 20 warmups. "
            "Both use CPU XLA + cached ConcreteFunction; QKeras W8A8 uses quantized values with floating CPU operators, not native INT8 kernels.",
        )
        fig, axes = plt.subplots(1, 2, figsize=(13.5, 4.7), sharey=True)
        for ax, scope, title in zip(
            axes,
            ["input_cold", "selected_lines_warm"],
            ["Raw input flushed", "Selected input cache lines warmed"],
        ):
            self.bars(ax, self.real, cache=scope)
            ax.set_xticks(range(8), [f"R{i+1}" for i in range(8)])
            ax.set_title(title)
        axes[0].legend(fontsize=8, loc="upper left", bbox_to_anchor=(0, 1.22))
        self.figure(
            "02_cache_control",
            fig,
            "2 · Cache-state control: cold versus warmed selected input lines",
            "The warm control touches only the source bytes selected by preprocessing. Above the sampling cutoff "
            "these occupy approximately 4 MiB of cache lines, which fits the socket's 24.75 MiB L3; the full 128 MiB "
            "buffer does not. Cache preparation is untimed. The cold condition invalidates the actual aliased input storage. "
            "Natural cache fills and prefetching during execution remain enabled; this is not cache-bypassing inference.",
        )
        fig, ax = plt.subplots(figsize=(13, 4.7))
        self.bars(ax, self.synthetic)
        ax.set_xticks(range(4), ["4 MiB", "16 MiB", "64 MiB", "128 MiB − 64 B"])
        ax.legend(fontsize=8, loc="upper center", bbox_to_anchor=(0.5, 1.14), ncol=2)
        self.figure(
            "03_synthetic_latency",
            fig,
            "3 · Established synthetic workloads: cold-input verdict latency",
            "Pinned synthetic byte identities match the previous HBM campaign. Each bar uses 400 measured calls. "
            "Input lengths affect which bytes are gathered, memory locality and compiled graph shape. Sampling touches "
            "65,536 byte positions rather than casting or scanning the complete raw file into floating point.",
        )

    def diagnostics(self):
        fig, axes = plt.subplots(1, 2, figsize=(13.5, 4.7))
        values = [
            self.stat("FP32", item["id"], "preprocessing_only") for item in self.real
        ]
        axes[0].bar(range(8), values, color="#4BAE91")
        axes[0].set_title("Preprocessing-only diagnostic")
        axes[0].set_ylabel("Completed preprocessing diagnostic (ms)")
        self.bars(axes[1], self.real, mode="inference_only")
        axes[1].set_title("Inference-only diagnostic: prepared input flushed")
        axes[1].legend(fontsize=8, loc="upper center", bbox_to_anchor=(0.5, 1.24))
        for ax in axes:
            ax.set_xticks(range(8), [f"R{i+1}" for i in range(8)])
        self.figure(
            "04_stage_diagnostics",
            fig,
            "4 · Separate preprocessing and inference diagnostics",
            "These are independent completed-call timings, not an additive breakdown of the fused end-to-end graph. "
            "Preprocessing-only returns/materializes a 256 KiB float32 tensor; fused inference does not expose that "
            "intermediate to Python. Inference-only starts from the prepared tensor flushed from data caches. "
            "Preprocessing is shared by the two primary models: integer sampling/padding followed by an exact 256-entry "
            "float32 normalization lookup. Boundary validation caught and rejected a prior rounding-sensitive arithmetic implementation.",
        )
        fig, axes = plt.subplots(1, 2, figsize=(13, 4.7))
        for ax, index in zip(axes, [0, 7]):
            case = self.real[index]
            for model in self.models:
                for session, style in [("A", "-"), ("B", "--")]:
                    series = sorted(
                        row["elapsed_ms"]
                        for row in self.rows
                        if row["model"] == model
                        and row["case_id"] == case["id"]
                        and row["mode"] == "total"
                        and row["cache_scope"] == "input_cold"
                        and row["session"] == session
                    )
                    ax.plot(
                        series,
                        np.arange(1, len(series) + 1) / len(series),
                        style,
                        color=COLORS[model],
                        label=f"{model} · {session}",
                    )
            ax.set_title(f"R{index+1} · {case['bytes']/2**20:.2f} MiB")
            ax.set_xlabel("Raw-input-to-verdict latency (ms)")
            ax.set_ylabel("Empirical cumulative fraction")
            ax.legend(fontsize=8)
        self.figure(
            "05_distributions",
            fig,
            "5 · Latency distributions retain independent process sessions",
            "Two independently launched, model-warmed rounds use reversed model, workload and cache-scope order. "
            "All accepted calls remain present; latency variation alone does not trigger selective reruns. "
            "This is a shared build host: affinity limits our worker to one logical CPU, while another process "
            "could still contend for the core, SMT sibling or shared resources. Environment/load and process CPU-time evidence are retained.",
        )

    def cache_evidence(self):
        probes = {
            model: json.loads(
                (self.root / f"preflight/{model}/cache_probe.json").read_text()
            )
            for model in self.models
        }
        fig, axes = plt.subplots(1, 2, figsize=(13, 4.6))
        for offset, model in [(-0.18, "FP32"), (0.18, "QKERAS_W8A8")]:
            series = [np.median(probes[model][key]) for key in ["warm", "cold"]]
            bars = axes[0].bar(
                np.arange(2) + offset, series, 0.33, color=COLORS[model], label=model
            )
            axes[0].bar_label(bars, fmt="%.0f", padding=4)
        axes[0].set_xticks([0, 1], ["Line warmed immediately", "Line flushed + fence"])
        axes[0].set_ylabel("Single-load latency (timestamp-counter ticks)")
        axes[0].legend()
        path = self.root / "preflight/cache_counters.json"
        if path.exists():
            counters = json.loads(path.read_text())
            bars = axes[1].bar(
                [0, 1],
                [
                    np.median(
                        [row["cache_misses"] for row in counters if row["cold"] == cold]
                    )
                    for cold in [False, True]
                ],
                color=["#4BAE91", "#CB6666"],
            )
            axes[1].bar_label(bars, fmt="%.0f", padding=4)
            axes[1].set_xticks([0, 1], ["Selected lines warmed", "Raw input flushed"])
            axes[1].set_ylabel("Cache misses per 65,536-sample gather")
        else:
            axes[1].axis("off")
            axes[1].text(
                0.05,
                0.5,
                "Hardware-counter diagnostic unavailable;\nsee retained diagnostic log.",
                transform=axes[1].transAxes,
            )
        self.figure(
            "06_cache_evidence",
            fig,
            "6 · Cache eviction evidence from isolated CPU diagnostics",
            "Left: 512 randomized line probes per cache state; fences and timestamp-counter overhead are included. "
            "Timestamp-counter ticks are not actual variable-frequency core cycles. Right, when available: per-thread "
            "hardware cache-miss counters enabled only around a native gather on a 128 MiB−64 B arena, after untimed "
            "cache preparation. This diagnostic is separate from TensorFlow/model timings. CLFLUSHOPT + fences "
            "invalidate input lines before a call; they do not prevent normal cache use during the call.",
        )

    def session_variation(self):
        fig, ax = plt.subplots(figsize=(13, 3.9))
        matrix = np.array(
            [
                [
                    100
                    * (
                        self.stat(model, case["id"], session="B")
                        / self.stat(model, case["id"], session="A")
                        - 1
                    )
                    for case in self.real
                ]
                for model in self.models
            ]
        )
        bound = max(float(np.max(np.abs(matrix))), 5)
        image = ax.imshow(
            matrix,
            aspect="auto",
            cmap="RdBu_r",
            norm=TwoSlopeNorm(vmin=-bound, vcenter=0, vmax=bound),
        )
        ax.set_xticks(range(8), [f"R{i+1}" for i in range(8)])
        ax.set_yticks([0, 1], ["FP32", "QKeras W8A8"])
        for y in range(2):
            for x in range(8):
                ax.text(x, y, f"{matrix[y,x]:+.1f}%", ha="center", va="center")
        fig.colorbar(image, ax=ax, label="Round B / round A median − 1 (%)")
        self.figure(
            "07_session_variation",
            fig,
            "7 · Independent process sessions: cold-input median changes",
            "Round B reverses model, workload and cache-scope order. Session changes are retained rather than "
            "rerun away; separate absolute values appear in the appendix. CPU frequency snapshots vary and "
            "this is a shared host. No single physical cause for these differences is established. Equal "
            "200-call sessions contribute to each pooled 400-call primary cell.",
        )

    def historical(self):
        old = (
            REPO
            / "hls4ml/optimize/reports/optimizations/2026-11-08_hbm_resident_verdict/data/statistics.json"
        )
        old_stats = json.loads(old.read_text())
        fig, ax = plt.subplots(figsize=(13.5, 4.8))
        series = []
        for model in self.models:
            series.append(
                (
                    LABELS[model],
                    [self.stat(model, case["id"]) for case in self.real],
                    COLORS[model],
                )
            )
        for name, color in [("FPGA_HLS4ML", "#4BAE91"), ("GPU_P2P", "#9068AE")]:
            values = [
                next(
                    row["metrics"]["verdict_ms"]["median"]
                    for row in old_stats
                    if row["variant"] == name and row["case_id"] == case["id"]
                )
                for case in self.real
            ]
            series.append((name + " · historical HBM", values, color))
        for index, (label, values, color) in enumerate(series):
            ax.bar(
                np.arange(8) + (index - 1.5) * 0.19,
                values,
                0.18,
                label=label,
                color=color,
            )
        ax.set_xticks(range(8), [f"R{i+1}" for i in range(8)])
        ax.set_ylabel("Resident-raw-input-to-verdict median (ms)")
        ax.legend(fontsize=8)
        self.figure(
            "A1_historical_context",
            fig,
            "Appendix · CPU versus historical HBM paths: different hosts",
            "CPU: Xeon Gold 6234, hacc-build-03, one logical CPU, local DRAM, measurements "
            + ", ".join(self.summary["measurement_dates"])
            + ". "
            "FPGA/GPU: original HBM report, measured 2026-11-08 on hacc-gpu-u55c-01 with EPYC host, U55C device2 and MI210 GPU0. "
            "Accelerator values are FPGA accepted-arm→verdict events; CPU uses completed host wall time. These are different-machine "
            "deployment-path observations, not a controlled same-host speedup claim. Historical OPT_10 changed by up to 9.825% "
            "after identical-image reprogramming; this plot uses the report's initial-program medians. QKeras CPU and hls4ml FPGA "
            "also differ in fixed-point accumulator/input arithmetic; FP32 uses the same pinned float checkpoint as GPU.",
        )

    def appendix(self):
        self.story.append(PageBreak())
        self.text("Appendix · Per-session cold-input medians", "Heading1")
        self.text(
            "Each cell is A / B in milliseconds; 200 measured calls per process session. Main medians pool equally sized sessions."
        )
        table = [["Model", *[f"R{i+1}" for i in range(8)]]]
        for model in self.models:
            table.append(
                [
                    model,
                    *[
                        f"{self.stat(model,c['id'],session='A'):.3f} / {self.stat(model,c['id'],session='B'):.3f}"
                        for c in self.real
                    ],
                ]
            )
        self.table(table)
        self.text("Model identities and interpretation", "Heading2")
        self.text(
            "FP32 uses the original unquantized Keras checkpoint from the accepted GPU R06 runtime. QKeras W8A8 uses the "
            "frozen OPT_6 architecture and pruned/QAT weights. It preserves quantization functions and 8-bit values through "
            "floating CPU operators. It must not be cited as a native INT8 CPU implementation. The hls4ml software simulator "
            "is not used as a CPU performance baseline. SIMD/vectorization on one CPU core is allowed."
        )
        conversion = self.root / "int8_conversion/result.json"
        self.text("Native INT8 conversion investigation", "Heading2")
        if conversion.exists():
            result = json.loads(conversion.read_text())
            review = json.loads((self.root / "int8_conversion/review.json").read_text())
            self.text(
                "A separately labeled native INT8 conversion was attempted: status <b>"
                + review["status"]
                + "</b>. "
                "Conversion changes tie rounding and integer pooling/output scales; it is not bit-exact QKeras or hls4ml. "
                "All 26 admission verdicts match, but its calibrated output range clips several original logits "
                f"(maximum score difference {review['maximum_absolute_score_difference']:.3f}). "
                "It is not accepted as a faithful replacement or primary timing baseline. No native INT8 speedup "
                "is claimed. Its calibration/provenance, rejected disposition and score differences are retained "
                "under campaign int8_conversion/. Calibration was not retuned on benchmark outputs."
            )
        else:
            self.text(
                "The native INT8 conversion attempt did not produce an accepted deployment artifact. Conversion logs are "
                "retained under campaign software/ and int8_conversion/. No converted or partially floating graph is "
                "silently substituted for the frozen QKeras model in the primary figures."
            )
        self.text("Reproducibility and measurement limits", "Heading2")
        self.text(
            "The campaign retains source/model/input hashes, input alias tests, 26-case admission, raw trials, "
            "thread affinities, local NUMA placement, page backing, cache setup times, CPU frequency/load snapshots and "
            "numerical/visual review. File reads, DRAM preload, page faults during initial setup, model loading, graph "
            "compilation, cache preparation and warmups are excluded from primary timing. Runtime materialization and "
            "thresholding of the final scalar verdict are included. Code/model are warmed; intermediate activations "
            "naturally use caches. TLBs and instruction caches are not explicitly flushed. No global cache dropping, "
            "governor changes, FPGA programming or GPU execution occurred."
        )

    def build(self):
        self.text("Single-core CPU: DRAM preprocessing + inference", "Title")
        self.text(
            "Created "
            + self.created
            + " · Measurements "
            + ", ".join(self.summary["measurement_dates"])
        )
        self.text(
            "Host hacc-build-03: Intel Xeon Gold 6234, CPU2 on NUMA2, SMT sibling CPU34; 32 KiB L1d, 1 MiB L2 "
            "per physical core and 24.75 MiB shared L3 per socket. All worker threads are restricted to CPU2. "
            "The raw bitstream begins in local DRAM and is evicted from CPU data caches before primary calls. "
            "Compiled code/model are warmed. The complete pipeline is measured through materialized CPU verdict."
        )
        self.text(
            f"<b>{self.summary['primary_calls']:,} primary calls</b> across two models, two input-cache scopes and twelve "
            f"workloads; <b>{self.summary['measured_calls']:,} measured calls</b> including separate stage diagnostics. "
            "Each cell has 400 measurements from two independently launched rounds, after 20 warmups per round."
        )
        self.text(
            f"<b>Repeatability limitation:</b> cold-input medians differ by up to "
            f"{100 * self.summary['maximum_absolute_primary_session_change']:.1f}% between independent process sessions. "
            "The figures expose both sessions; pooled medians should not be interpreted as a uniquely stable machine latency."
        )
        table = [["Input", "MiB", "FP32 cold (ms)", "QKeras W8A8 cold (ms)"]]
        for index, case in enumerate(self.real):
            table.append(
                [
                    f"R{index+1}",
                    f"{case['bytes']/2**20:.2f}",
                    *[f"{self.stat(model,case['id']):.3f}" for model in self.models],
                ]
            )
        self.table(table)
        self.text(
            "The QKeras result measures the frozen quantized model using floating CPU operators. It does not establish "
            "the performance of native INT8 instructions. Primary models and preprocessing are validated against their "
            "own CPU references; no equality of FP32 and quantized scores is assumed."
        )
        self.latency()
        self.diagnostics()
        self.cache_evidence()
        self.session_variation()
        self.historical()
        self.appendix()
        page = landscape(A4)
        document = SimpleDocTemplate(
            str(self.output / "cpu_dram_preprocess_inference_report.pdf"),
            pagesize=page,
            leftMargin=40,
            rightMargin=40,
            topMargin=35,
            bottomMargin=35,
            title="Single-core CPU DRAM benchmark — " + self.created,
        )

        def footer(canvas, doc):
            canvas.setFont("Helvetica", 8)
            canvas.drawString(
                40, 18, "Single-core CPU DRAM benchmark · " + self.created
            )
            canvas.drawRightString(page[0] - 40, 18, str(doc.page))

        document.build(self.story, onFirstPage=footer, onLaterPages=footer)
        save(self.output / "data/figure_catalog.json", self.catalog)
        save(self.output / "data/figure_values.json", self.queries)
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
