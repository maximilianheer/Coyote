#!/usr/bin/env python3
"""Adapt accepted November 8 figures for Section 6, with editable PPTX sources.

Reads archived data only. All marks, axes, text, and topology objects are native
PowerPoint shapes mirrored in vector PDF/PNG. Never runs a benchmark or imports
an archived report generator that would overwrite its outputs.
"""

import hashlib
import json
import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/paper-local-inspection-matplotlib")

import numpy as np
from matplotlib.patches import Circle, Polygon, Rectangle
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_AUTO_SIZE
from pptx.oxml.xmlchemy import OxmlElement
from pptx.util import Inches, Pt

from generate_background_figure import Diagram, plt

PAPER = Path(__file__).resolve().parent
ROOT = PAPER.parent
REPORT = ROOT / "hls4ml/optimize/reports/optimizations/2026-11-08_hbm_resident_verdict"
OUTPUT = PAPER / "figures"
BLUE = "2878B5"
ORANGE = "E98A25"
INK = "243746"
GRAY = "65717C"
GRID = "E5E9ED"
RED = "B32B2B"
VARIANTS = ("FPGA_HLS4ML", "GPU_P2P")
CAPACITY = {"LUT": 1303680, "FF": 2607360, "BRAM_tiles": 2016, "DSP": 9024, "URAM": 960}


def load(name):
    return json.loads((REPORT / "data" / name).read_text())


def rectangle(d, name, x, y, width, height, color):
    shape = d.slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(width), Inches(height)
    )
    shape.name = name
    shape.fill.solid()
    shape.fill.fore_color.rgb = RGBColor.from_string(color)
    shape.line.fill.background()
    d.axis.add_patch(Rectangle((x, y), width, height, facecolor=f"#{color}", linewidth=0))


def marker(d, name, x, y, kind, color=INK, radius=0.055):
    preset = MSO_SHAPE.OVAL if kind == "o" else MSO_SHAPE.DIAMOND
    shape = d.slide.shapes.add_shape(
        preset, Inches(x - radius), Inches(y - radius), Inches(2 * radius), Inches(2 * radius)
    )
    shape.name = name
    shape.fill.solid()
    shape.fill.fore_color.rgb = RGBColor(255, 255, 255)
    shape.line.color.rgb = RGBColor.from_string(color)
    shape.line.width = Pt(1.1)
    if kind == "o":
        patch = Circle((x, y), radius, facecolor="white", edgecolor=f"#{color}", linewidth=1.1)
    else:
        points = [(x, y - radius), (x + radius, y), (x, y + radius), (x - radius, y)]
        patch = Polygon(points, facecolor="white", edgecolor=f"#{color}", linewidth=1.1)
    d.axis.add_patch(patch)


def line(d, name, x1, y1, x2, y2, color=INK, dashed=False):
    d.arrow(name, [(x1, y1), (x2, y2)], color=color, dashed=dashed, head=False)


def save(d, stem, notes):
    # Disable inherited Office theme shadows and text-box autosizing so that
    # later PowerPoint exports preserve the scientific figure's flat layout.
    def strip_theme(shapes):
        for shape in shapes:
            if hasattr(shape, "shapes"):
                strip_theme(shape.shapes)
                continue
            properties = shape._element.spPr
            if not properties.xpath("./a:effectLst"):
                properties.append(OxmlElement("a:effectLst"))
            for effect in shape._element.xpath("./p:style/a:effectRef"):
                effect.set("idx", "0")
            if shape.has_text_frame:
                shape.text_frame.auto_size = MSO_AUTO_SIZE.NONE

    strip_theme(d.slide.shapes)
    d.presentation.core_properties.title = stem.replace("_", " ")
    d.slide.notes_slide.notes_text_frame.text = notes
    d.presentation.save(OUTPUT / f"{stem}.pptx")
    d.figure.savefig(OUTPUT / f"{stem}.pdf")
    d.figure.savefig(OUTPUT / f"{stem}.png", dpi=200)
    plt.close(d.figure)


def topology():
    from generate_coyote_benchmark_setup import draw_setup

    draw_setup(save)


def plot_frame(d, title, x, top, width, height, ymax, ticks):
    d.text(title + " title", title, x, top - 0.44, width, 0.30, size=19, bold=True, align="left")
    bottom = top + height
    for tick in ticks:
        y = bottom - tick / ymax * height
        line(d, f"{title} grid {tick}", x, y, x + width, y, GRID)
        d.text(f"{title} tick {tick}", f"{tick:g}", x - 0.52, y - 0.12, 0.40, 0.24, size=14)
    line(d, title + " x-axis", x, bottom, x + width, bottom)
    line(d, title + " y-axis", x, top, x, bottom)
    return lambda value: bottom - value / ymax * height


def latency(stats, cases):
    d = Diagram(width=11.0, height=8.25)
    d.text("Title", "Verdict latency: local inspection versus GPU offloading", 0.2, 0.04, 10.6, 0.36,
           size=23, bold=True)
    rectangle(d, "FPGA legend swatch", 0.9, 0.61, 0.20, 0.15, BLUE)
    d.text("FPGA legend", "FPGA_HLS4ML", 1.18, 0.54, 2.30, 0.28, size=15, align="left")
    rectangle(d, "GPU legend swatch", 4.0, 0.61, 0.20, 0.15, ORANGE)
    d.text("GPU legend", "GPU_P2P", 4.28, 0.54, 2.0, 0.28, size=15, align="left")
    line(d, "p95 legend tick", 6.62, 0.68, 6.82, 0.68)
    d.text("p95 legend", "p95", 6.95, 0.54, 0.65, 0.28, size=15, align="left")
    x, width = 0.9, 9.75
    y = plot_frame(d, "A  Start → FPGA verdict (ms)", x, 1.35, width, 2.55, 10.0, range(0, 11, 2))
    spacing = width / len(cases)
    for i, case in enumerate(cases):
        center = x + (i + 0.5) * spacing
        for offset, variant, color in [(-0.22, "FPGA_HLS4ML", BLUE), (0.22, "GPU_P2P", ORANGE)]:
            metric = stats[variant, case]["metrics"]["verdict_ms"]
            median, p95 = metric["median"], metric["p95"]
            position = center + offset
            rectangle(d, f"R{i + 1} {variant} median bar", position - 0.19, y(median), 0.38, y(0) - y(median), color)
            line(d, f"R{i + 1} {variant} p95", position - 0.11, y(p95), position + 0.11, y(p95))
            label_top = max(median, p95)
            d.text(f"R{i + 1} {variant} value", f"{median:.2f}", position - 0.25, y(label_top) - 0.29,
                   0.50, 0.24, size=13)
        size = stats["FPGA_HLS4ML", case]["bytes"] / 2**20
        d.text(f"R{i + 1} latency input", f"R{i + 1}\n{size:.2f}", center - 0.5, 4.02, 1.0, 0.44, size=14)
    d.text("A x label", "Real bitstream / size (MiB)", 2.0, 4.49, 7.0, 0.28, size=15)

    y = plot_frame(d, "B  Local-inspection speedup (GPU / FPGA latency)", x, 5.35, width, 2.20,
                   3.5, [0, 1, 2, 3])
    line(d, "Equal latency", x, y(1), x + width, y(1), INK, dashed=True)
    for i, case in enumerate(cases):
        center = x + (i + 0.5) * spacing
        gpu = stats["GPU_P2P", case]["metrics"]["verdict_ms"]["median"]
        fpga = stats["FPGA_HLS4ML", case]["metrics"]["verdict_ms"]["median"]
        ratio = gpu / fpga
        color = BLUE if ratio >= 1 else ORANGE
        rectangle(d, f"R{i + 1} speedup", center - 0.31, y(ratio), 0.62, y(0) - y(ratio), color)
        label_y = y(ratio) - 0.29
        if ratio < 1:
            label_y = y(ratio * 0.55) - 0.12
        d.text(f"R{i + 1} speedup value", f"{ratio:.2f}×", center - 0.38, label_y,
               0.76, 0.24, size=14)
        d.text(f"R{i + 1} speedup input", f"R{i + 1}", center - 0.5, 7.65, 1.0, 0.25, size=14)
    d.text("B interpretation", "Above 1× favors local inspection; below 1× favors GPU offloading.",
           0.6, 7.99, 9.9, 0.25, size=14)
    save(d, "benchmark_local_latency", "Adapted from report figures 01_real_latency and 02_real_speedup. "
         "Bars retain initial programmed-state medians, with p95 ticks across 200 primary measured trials. "
         "Speedup is the ratio of GPU to initial-state FPGA median latency. "
         "Later programming cycles are omitted from this figure by editorial request; "
         "the manuscript retains the repeatability limitation. All marks and text are editable.")



def timeline(stats, trials, case):
    d = Diagram(width=11.0, height=6.5)
    d.text("Title", "Execution overlap: R4, 28.92 MiB", 0.2, 0.05, 10.6, 0.38,
           size=23, bold=True)
    line(d, "Verdict legend", 3.4, 0.66, 3.85, 0.66, RED, dashed=True)
    d.text("Verdict legend label", "Verdict available inside FPGA", 3.98, 0.52, 4.4, 0.28,
           size=15, align="left")
    x, width, maximum = 2.55, 7.9, 5.0
    tx = lambda time: x + time / maximum * width
    selected = []
    for variant, title, start, bottom in [
        ("FPGA_HLS4ML", "A  FPGA_HLS4ML: local inspection", 1.55, 2.95),
        ("GPU_P2P", "B  GPU_P2P: GPU offloading", 4.0, 5.85),
    ]:
        median = stats[variant, case]["metrics"]["verdict_ms"]["median"]
        rows = [row for row in trials if row["variant"] == variant and row["case_id"] == case]
        row = min(rows, key=lambda item: abs(item["verdict_ms"] - median))
        selected.append(row)
        d.text(title, title, 0.65, start - 0.48, 9.8, 0.30, size=19, bold=True, align="left")
        for tick in range(6):
            line(d, f"{variant} grid {tick}", tx(tick), start - 0.08, tx(tick), bottom, GRID)
            d.text(f"{variant} tick {tick}", str(tick), tx(tick) - 0.20, bottom + 0.06, 0.40, 0.24, size=14)
        lanes = [("Memory delivery", "hbm_return_start_ms", "hbm_return_end_ms", "65A5CE")]
        if variant == "FPGA_HLS4ML":
            lanes += [("Pixel production", "pixel_start_ms", "pixel_end_ms", "4BAE91"),
                      ("CNN input span", "cnn_start_ms", "cnn_end_ms", "8975BD")]
        else:
            lanes += [("GPU forwarding", "gpu_forward_start_ms", "gpu_forward_end_ms", ORANGE),
                      ("Framework call", "gpu_framework_begin_ms", "gpu_framework_end_ms", "AA67A2"),
                      ("FPGA polling", "poll_request_start_ms", "poll_request_end_ms", "929292")]
        for index, (label, begin, end, color) in enumerate(lanes):
            yy = start + index * 0.45
            d.text(variant + label, label, 0.1, yy + 0.02, 2.25, 0.26, size=15)
            rectangle(d, variant + label + " span", tx(row[begin]), yy,
                      max(tx(row[end]) - tx(row[begin]), 0.001), 0.30, color)
        if variant == "FPGA_HLS4ML":
            yy = start + 2 * 0.45 + 0.15
            line(d, "CNN output tail", tx(row["cnn_end_ms"]), yy, tx(row["verdict_ms"]), yy, "8975BD")
        line(d, variant + " verdict", tx(row["verdict_ms"]), start - 0.08,
             tx(row["verdict_ms"]), bottom, RED, dashed=True)
        d.text(variant + " verdict value", f"{row['verdict_ms']:.3f} ms", tx(row["verdict_ms"]) + 0.07,
               start - 0.06, 1.0, 0.24, size=14, color=RED, align="left")
        line(d, variant + " time axis", x, bottom, x + width, bottom)
    d.text("Shared time label", "Time since accepted FPGA start (ms)", 2.55, 6.20, 7.9, 0.28, size=16)
    save(d, "benchmark_local_execution_r4", "Adapted from report figure 04_timelines, retaining its R4 "
         "nearest-median representative trials. Shared 0--5 ms axis. CNN input span is not pure compute time; "
         "thin extension shows output tail. Framework call includes dispatch and synchronization. "
         "Polling overlaps GPU work. Host-clock annotations use the report's affine calibration. "
         + json.dumps([{key: row[key] for key in ('variant', 'trial', 'source', 'verdict_ms')} for row in selected]))
    return selected


def main():
    plt.rcParams.update({"font.family": "Liberation Sans", "pdf.fonttype": 42})
    statistics = load("statistics.json")
    trials = load("trial_events.json")
    stats = {(row["variant"], row["case_id"]): row for row in statistics}
    cases = sorted((row["case_id"] for row in statistics
                    if row["variant"] == "FPGA_HLS4ML" and row["case_id"].startswith("real_")),
                   key=lambda case: stats["FPGA_HLS4ML", case]["bytes"])
    assert len(cases) == 8
    # Verify primary plot values and archived repeatability measurements.
    for variant in (*VARIANTS, "FPGA closing", "FPGA program 3"):
        for case in cases:
            rows = [row for row in trials if row["variant"] == variant and row["case_id"] == case]
            expected_count = 20 if variant == "FPGA program 3" else 200
            assert len(rows) == expected_count, (variant, case, len(rows))
            values = [row["verdict_ms"] for row in rows]
            metrics = stats[variant, case]["metrics"]["verdict_ms"]
            assert np.isclose(np.median(values), metrics["median"], rtol=0, atol=1e-10)
            assert np.isclose(np.percentile(values, 95), metrics["p95"], rtol=0, atol=1e-10)
    topology()
    latency(stats, cases)
    selected = timeline(stats, trials, cases[3])
    resources = load("resources.json")["OPT_10 (HBM FPGA)"]["wrapper"]
    selected_latency = stats["FPGA_HLS4ML", cases[4]]["metrics"]["verdict_ms"]["median"]
    baselines = [141, 72.3, 85.5, stats["FPGA_HLS4ML", cases[4]]["bytes"] / 800000]
    manifest = {
        "created": "2026-11-08",
        "measurement_date": "2026-11-08",
        "scope": "ABI5 accepted FPGA arm CSR6 to FPGA verdict CSR24; complete input locally available",
        "sources": {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in [REPORT / "data" / filename for filename in
                                 ("statistics.json", "trial_events.json", "resources.json", "evidence_manifest.json")]},
        "case_order": cases,
        "representative_trials": selected,
        "wrapper_resources": resources,
        "device_utilization_percent": {name: 100 * value / CAPACITY[name] for name, value in resources.items()},
        "context_inspection_ms": selected_latency,
        "context_rows": [{"baseline_ms": value, "with_inspection_ms": value + selected_latency,
                          "increase_percent": 100 * selected_latency / value} for value in baselines],
        "validation": "32 workload/state cells: counts, median and p95 matched accepted trial exports",
        "export": "Native editable PPTX objects; vector PDF and PNG mirror the same geometry",
    }
    (OUTPUT / "benchmark_local_sources.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print("Created three editable figures and source manifest; accepted statistics verified.")


if __name__ == "__main__":
    main()
