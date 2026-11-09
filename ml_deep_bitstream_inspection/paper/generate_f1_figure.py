#!/usr/bin/env python3
"""Regenerate the existing resolution/depth heatmap as a vector PDF.

Adapted from heatmap() in hls4ml/pipeline/experiment_plots.py. Preserve its
row-order selection: the last numeric result for each cell supplies its F1.
This reproduces hls4ml/results/plots/f1_heatmap.png without changing results.
"""

import csv
import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/paper-f1-matplotlib")

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


PAPER = Path(__file__).resolve().parent
SOURCE = PAPER.parent / "hls4ml/results/experiment_summary.csv"


def main():
    values = {}
    with SOURCE.open(newline="") as source:
        for row in csv.DictReader(source):
            try:
                resolution = int(row["input_resolution"])
                depth = int(row["num_layers"])
                score = float(row["software_f1"])
            except (KeyError, ValueError):
                continue
            if np.isfinite(score):
                values[depth, resolution] = score

    resolutions = sorted({resolution for depth, resolution in values})
    depths = sorted({depth for depth, resolution in values})
    grid = np.array([
        [values.get((depth, resolution), np.nan) for resolution in resolutions]
        for depth in depths
    ])

    plt.rcParams.update({"pdf.fonttype": 42, "ps.fonttype": 42})
    fig, ax = plt.subplots(figsize=(8, 5))
    # pcolormesh emits vector cells; imshow would embed a raster in the PDF.
    mesh = ax.pcolormesh(
        np.arange(len(resolutions) + 1) - 0.5,
        np.arange(len(depths) + 1) - 0.5,
        np.ma.masked_invalid(grid),
        cmap="viridis",
        rasterized=False,
        edgecolors="face",
    )
    ax.invert_yaxis()
    ax.set_xticks(range(len(resolutions)), [str(value) for value in resolutions])
    ax.set_yticks(range(len(depths)), [str(value) for value in depths])
    ax.set_xlabel("Input resolution")
    ax.set_ylabel("Layers")
    ax.set_title("F1")

    for row, depth in enumerate(depths):
        for column, resolution in enumerate(resolutions):
            value = grid[row, column]
            if np.isnan(value):
                continue
            # Dark text keeps the high-F1 green/yellow cells readable.
            color = "black" if mesh.norm(value) > 0.55 else "white"
            ax.text(
                column, row, f"{value:.3g}",
                ha="center", va="center", color=color,
            )

    colorbar = fig.colorbar(mesh, ax=ax, shrink=0.85)
    colorbar.solids.set_rasterized(False)
    colorbar.solids.set_edgecolor("face")
    fig.tight_layout()
    output = PAPER / "figures/f1_resolution_depth"
    fig.savefig(output.with_suffix(".pdf"))
    fig.savefig(output.with_suffix(".png"), dpi=300)
    plt.close(fig)
    print(f"Generated vector heatmap with {len(values)} populated cells.")


if __name__ == "__main__":
    main()
