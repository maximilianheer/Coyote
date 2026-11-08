#!/usr/bin/env python3
"""Model proposed data paths; no measurements or hardware builds are performed."""

import csv
import hashlib
import json
import os
from collections import defaultdict
from pathlib import Path
from statistics import median

os.environ.setdefault("MPLCONFIGDIR", "/tmp/coyote_prediction_matplotlib")

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


OUTPUT = Path(__file__).resolve().parent
REPO = OUTPUT.parents[4]
REPORT_DATA = (
    REPO / "hls4ml/optimize/reports/optimizations/"
    "2026-10-22_gpu_opt_xla_concretefunction/data"
)
GPU_OBSERVATIONS = (
    REPO / "hls4ml/optimize/runs/"
    "gpu_runtime_investigation_20261021_030038/hardware_xla_concrete/"
    "jobs/OPT_8_GPU_P2P/attempt_01/full/observations.jsonl"
)

ASSUMPTIONS = {
    "created": "2026-11-07",
    "measurement_date": "2026-10-21",
    "status": "predictions, not new measurements",
    "fpga": "OPT_6, unchanged CNN; new selective HBM reader for option 1",
    "gpu": "MI210, R06 XLA + ConcreteFunction FP32; full raw input forwarded",
    "endpoint": "verdict accepted by FPGA, equivalent to CSR14",
    "option_1_start": "local start command with raw bitstream already in HBM",
    "option_2_start": "first payload arriving at receiving FPGA; connection pre-established",
    "excluded": [
        "file reading", "initial HBM placement", "connection establishment",
        "sender scheduling and network flight before first payload",
        "GPU compilation/cold start", "partial reconfiguration",
        "porting GPU runtime or Coyote control plane to a hostless system",
    ],
    "p2p_gbps": [4.1, 15.75],
    "p2p_fast_caveat": "optimistic encoded-link ceiling; payload cannot sustain this after PCIe overhead",
    "hbm_gpu_feed": "assume sufficient sequential HBM bandwidth to sustain each selected P2P rate",
    "network_gbps": 11.5,
    "network_sensitivity_gbps": [10.0, 12.0],
    "gather_gbps": 4.0,
    "gather_sensitivity_gbps": [2.0, 8.0],
    "gather_requests": 65536,
    "gather_bytes_per_request": 64,
    "gather_condition": "ordered pixels; multiple outstanding reads; adequate buffering",
    "fpga_floor_ms": 1.12,
    "fpga_transport_tail_and_start_ms": 0.05,
    "gpu_start_ms": 0.02,
    "gpu_tail": "per-case median of (CSR14 - CSR19) at 4 ns, 200 measured resident calls",
    "gpu_overlap": "network reception and FPGA-to-GPU forwarding overlap; inference follows full input",
    "concurrency": "alternatives measured separately; no competing deployment or shared-memory traffic",
    "sensitivity_note": "bands vary assumed bandwidth only; not confidence intervals or guaranteed bounds",
    "formulas": {
        "fpga_hbm": "max(1.12, 65536 * 64 / (gather_GBps * 1e6) + 0.05)",
        "fpga_network": "max(1.12, input_bytes / (network_GBps * 1e6) + 0.05)",
        "gpu_hbm": "input_bytes / (P2P_GBps * 1e6) + measured_gpu_tail_ms + 0.02",
        "gpu_network": "input_bytes / (min(network_GBps, P2P_GBps) * 1e6) + measured_gpu_tail_ms + 0.02",
        "gpu_network_store_then_forward": "network_scan_ms + gpu_hbm_ms",
    },
}


def read_csv(path):
    with path.open() as handle:
        return list(csv.DictReader(handle))


def scan_ms(byte_count, gbps):
    return byte_count / (gbps * 1e6)


def fpga_latency(byte_count, gbps):
    # A streaming model: memory/input delivery overlaps CNN work.
    # The calibrated floor and tail are approximations, not an RTL simulation.
    return max(
        ASSUMPTIONS["fpga_floor_ms"],
        scan_ms(byte_count, gbps) + ASSUMPTIONS["fpga_transport_tail_and_start_ms"],
    )


def measured_gpu_tails():
    samples = defaultdict(list)
    with GPU_OBSERVATIONS.open() as handle:
        for line in handle:
            trial = json.loads(line)
            if (
                trial["scope"] == "resident"
                and trial["session"] == "timed"
                and not trial["warmup"]
                and trial["case_id"].startswith("real_")
            ):
                # Preserve GPU preprocessing, inference, publication and polling.
                elapsed_ms = (int(trial["csr_14"]) - int(trial["csr_19"])) * 4e-6
                samples[trial["case_id"]].append(elapsed_ms)
    return samples


def predict_rows():
    cases = json.loads((REPORT_DATA / "real_inputs.json").read_text())
    statistics = read_csv(REPORT_DATA / "latency_statistics.csv")
    measured = {
        (row["iteration"], row["case_id"]): float(row["median"])
        for row in statistics
        if row["metric"] == "verdict_available_ms"
    }
    tails = measured_gpu_tails()
    rows = []
    gather_bytes = ASSUMPTIONS["gather_requests"] * ASSUMPTIONS["gather_bytes_per_request"]
    for case in cases:
        case_id = case["case_id"]
        byte_count = case["input_bytes"]
        assert len(tails[case_id]) == 200
        tail = median(tails[case_id])
        row = {
            "id": case["id"],
            "case_id": case_id,
            "input_bytes": byte_count,
            "input_mib": byte_count / 2**20,
            "measured_fpga_ms": measured[("OPT_6_BRAM_FIFO1024_DSP_B2_RF72_RF288", case_id)],
            "measured_gpu_p2p_ms": measured[("OPT_8_GPU_P2P", case_id)],
            "measured_gpu_tail_ms": tail,
            "option1_fpga_ms": fpga_latency(gather_bytes, ASSUMPTIONS["gather_gbps"]),
            "option1_fpga_low_ms": fpga_latency(gather_bytes, 8.0),
            "option1_fpga_high_ms": fpga_latency(gather_bytes, 2.0),
            "option2_fpga_ms": fpga_latency(byte_count, ASSUMPTIONS["network_gbps"]),
            "option2_fpga_low_ms": fpga_latency(byte_count, 12.0),
            "option2_fpga_high_ms": fpga_latency(byte_count, 10.0),
        }
        for name, p2p_gbps in [("4p1", 4.1), ("15p75", 15.75)]:
            overhead = tail + ASSUMPTIONS["gpu_start_ms"]
            row[f"option1_gpu_{name}_ms"] = scan_ms(byte_count, p2p_gbps) + overhead
            row[f"option2_gpu_{name}_ms"] = scan_ms(
                byte_count, min(p2p_gbps, ASSUMPTIONS["network_gbps"])
            ) + overhead
            for option in [1, 2]:
                row[f"option{option}_fpga_speedup_vs_{name}"] = (
                    row[f"option{option}_gpu_{name}_ms"] / row[f"option{option}_fpga_ms"]
                )
            row[f"option2_gpu_{name}_store_then_forward_ms"] = (
                scan_ms(byte_count, ASSUMPTIONS["network_gbps"])
                + row[f"option1_gpu_{name}_ms"]
            )
        row["slow_gpu_prediction_vs_measured_percent"] = (
            row["option1_gpu_4p1_ms"] / row["measured_gpu_p2p_ms"] - 1
        ) * 100
        rows.append(row)
    return rows


def draw_predictions(rows):
    plt.rcParams.update({"font.size": 11, "axes.spines.top": False, "axes.spines.right": False})
    x = np.array([row["input_mib"] for row in rows])
    figure, axes = plt.subplots(1, 2, figsize=(14.5, 6.4), sharey=True)
    for option, axis in enumerate(axes, start=1):
        axis.fill_between(
            x,
            [row[f"option{option}_fpga_low_ms"] for row in rows],
            [row[f"option{option}_fpga_high_ms"] for row in rows],
            color="#2677b6", alpha=0.15,
        )
        for suffix, label, color, marker in [
            ("fpga", "FPGA_HLS4ML", "#2677b6", "o"),
            ("gpu_4p1", "GPU: P2P at 4.1 GB/s", "#c65b18", "s"),
            ("gpu_15p75", "GPU: P2P at 15.75 GB/s (ideal)", "#21845c", "D"),
        ]:
            axis.plot(
                x, [row[f"option{option}_{suffix}_ms"] for row in rows],
                marker=marker, linestyle="--", color=color, label=label,
                linewidth=2, markersize=5,
            )
        for suffix, color, offset in [("fpga", "#2677b6", -15), ("gpu_4p1", "#c65b18", 9), ("gpu_15p75", "#21845c", 8)]:
            value = rows[-1][f"option{option}_{suffix}_ms"]
            axis.annotate(f"{value:.2f} ms", (x[-1], value), xytext=(-4, offset),
                          textcoords="offset points", ha="right", color=color, weight="bold")
        axis.set_xlabel("Real bitstream size (MiB)")
        axis.set_xlim(3, 57)
        axis.set_ylim(0, 16)
        axis.grid(axis="y", alpha=0.2)
    axes[0].set_ylabel("Predicted time to verdict available at FPGA (ms)")
    axes[0].set_title("Option 1: input already in HBM\nFPGA gathers samples; GPU receives full bitstream")
    axes[1].set_title("Option 2: input arriving over 100 GbE\nNetwork reception overlaps checking or forwarding")
    figure.suptitle("Predicted verdict latency — real bitstream workloads", fontsize=17, weight="bold", y=0.99)
    handles, labels = axes[0].get_legend_handles_labels()
    figure.legend(handles, labels, loc="lower center", bbox_to_anchor=(0.5, 0.105), ncol=3, frameon=False)
    figure.text(
        0.5, 0.055,
        "Central assumptions: HBM gather 4 GB/s; network payload 11.5 GB/s; unchanged OPT_6 CNN; measured R06 GPU tail.\n"
        "Blue shading: gather 2–8 GB/s (left), network 10–12 GB/s (right). Sensitivity only, not confidence intervals.",
        ha="center", fontsize=10,
    )
    figure.text(0.5, 0.012, "Created 7 November 2026 • Calibration: 21 October 2026 • Predictions, not new measurements", ha="center", fontsize=9, color="#555555")
    figure.tight_layout(rect=(0, 0.18, 1, 0.94))
    for extension in ["png", "pdf", "svg"]:
        figure.savefig(OUTPUT / f"predicted_verdict_latency.{extension}", dpi=180)
    plt.close(figure)


def main():
    rows = predict_rows()
    with (OUTPUT / "predictions.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    sources = [REPORT_DATA / "real_inputs.json", REPORT_DATA / "latency_statistics.csv", GPU_OBSERVATIONS]
    provenance = {
        "assumptions": ASSUMPTIONS,
        "sources": {
            str(path.relative_to(REPO)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sources
        },
        "references": [
            "https://xilinx.github.io/Vitis-Tutorials/2022-1/build/html/docs/Hardware_Acceleration/Feature_Tutorials/07-using-hbm/3_BW_Explorations.html",
            "https://fpgasystems.github.io/Coyote/system/dynamic.html",
        ],
    }
    (OUTPUT / "assumptions_and_sources.json").write_text(json.dumps(provenance, indent=2) + "\n")
    draw_predictions(rows)
    for row in rows:
        print(
            f"{row['id']} {row['input_mib']:.2f} MiB | "
            f"HBM FPGA {row['option1_fpga_ms']:.2f}, GPU slow {row['option1_gpu_4p1_ms']:.2f}, "
            f"GPU fast {row['option1_gpu_15p75_ms']:.2f} | "
            f"Network FPGA {row['option2_fpga_ms']:.2f}, GPU slow {row['option2_gpu_4p1_ms']:.2f}, "
            f"GPU fast {row['option2_gpu_15p75_ms']:.2f} ms"
        )
    print("Slow GPU model maximum absolute deviation from measured E2E (%):",
          max(abs(row["slow_gpu_prediction_vs_measured_percent"]) for row in rows))


if __name__ == "__main__":
    main()
