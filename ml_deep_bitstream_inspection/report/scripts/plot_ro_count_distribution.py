#!/usr/bin/env python3
"""Generate the report-local RO-count distribution plot."""

from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


REPORT_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = REPORT_DIR.parent / "ml_deep_bitstream_inspection"

NORMAL_MANIFESTS = [
    PROJECT_DIR / "datasets/full_dataset_it1/artifacts/manifest_available.csv",
    PROJECT_DIR / "datasets/full_dataset_it2/artifacts/manifest_available.csv",
    PROJECT_DIR / "datasets/full_dataset_it3/artifacts/manifest_available.csv",
]
BIG_RO_MANIFESTS = [
    PROJECT_DIR / "datasets/full_dataset_it4_big_ro/artifacts/manifest_available.csv",
]
OUTPUT = REPORT_DIR / "figures/ro_count_distribution.png"
BIN_WIDTH = 2000


def ro_counts(paths: list[Path]) -> Counter[int]:
    counts: Counter[int] = Counter()
    for path in paths:
        with path.open(newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                if row["class_label"] == "1" and row["source_type"] == "standalone":
                    counts[int(row["ro_count"])] += 1
    return counts


def bin_counts(counts: Counter[int], width: int = BIN_WIDTH) -> Counter[int]:
    binned: Counter[int] = Counter()
    for ro_count, sample_count in counts.items():
        bin_left = (ro_count // width) * width
        bin_center = bin_left + width // 2
        binned[bin_center] += sample_count
    return binned


def format_count(value: float, _position: int) -> str:
    if value >= 1000:
        return f"{value / 1000:g}k"
    return f"{value:g}"


def main() -> None:
    normal = ro_counts(NORMAL_MANIFESTS)
    big = ro_counts(BIG_RO_MANIFESTS)
    normal_binned = bin_counts(normal)
    big_binned = bin_counts(big)
    bins = sorted(set(normal_binned) | set(big_binned))
    positions = list(range(len(bins)))

    normal_heights = [normal_binned.get(bin_center, 0) for bin_center in bins]
    big_heights = [big_binned.get(bin_center, 0) for bin_center in bins]

    fig, ax = plt.subplots(figsize=(10.8, 4.7), constrained_layout=True)
    bar_width = 0.42
    ax.bar(
        [position - bar_width / 2 for position in positions],
        normal_heights,
        width=bar_width,
        color="#2C7FB8",
        alpha=0.86,
        edgecolor="white",
        linewidth=0.6,
        label="Normal RO",
    )
    ax.bar(
        [position + bar_width / 2 for position in positions],
        big_heights,
        width=bar_width,
        color="#F28E2B",
        alpha=0.86,
        edgecolor="white",
        linewidth=0.6,
        label="Big RO",
    )

    ax.set_xlabel("RO-count bin center, 2k-RO bin width")
    ax.set_ylabel("Available bitstream samples")
    ax.set_title("RO-count distribution in malicious datasets, binned every 2000 ROs")
    ax.set_ylim(0, max(max(normal_binned.values()), max(big_binned.values())) + 2)
    ax.set_xlim(-0.75, len(bins) - 0.25)
    ax.set_xticks(positions)
    ax.set_xticklabels([format_count(bin_center, 0) for bin_center in bins], rotation=75, ha="right", fontsize=8)
    ax.grid(True, which="major", axis="y", color="#d0d0d0", linewidth=0.8)
    ax.legend(frameon=True, loc="upper right")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUTPUT, dpi=300)
    print(f"Wrote {OUTPUT}")


if __name__ == "__main__":
    main()
