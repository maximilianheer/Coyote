# Paper benchmark figures

Updated 5 November 2026. Measurements are from 21 October 2026.

Regenerate from the repository root:

```bash
ml_baseline/.venv/bin/python paper/generate_benchmark_figures.py
```

The script needs Matplotlib, NumPy, and Ghostscript (`gs`). It does not import
or run the archived report generator, access hardware, or rerun benchmarks.

| Paper asset | Existing source | Adaptation |
| --- | --- | --- |
| `benchmark_real_latency.pdf` | Presentation report `A1_real_latency` and exported statistics | Same eight inputs, FPGA_HLS4ML/GPU_HOST medians and p95; paper-sized layout |
| `benchmark_streaming_4mib.pdf` | Report `09_streaming_timelines` | Only 4 MiB, labeled Before/After our streaming optimization; original buffering/streaming trials 177 and 97 |
| `benchmark_execution_4mib.pdf` | Report `05_execution_overlap` | Only 4 MiB, FPGA_HLS4ML/GPU_HOST; original trials 95 and 1382; vertically arranged panels on a shared scale |
| `benchmark_topology.pdf` | hls4ml talk PDF page 18, displayed slide 22 | Original artwork cropped to its diagram and input-path legend |

The source report directories under `hls4ml/optimize/reports/optimizations/` are
`2026-10-22_gpu_opt_xla_concretefunction` and
`2026-10-22_gpu_opt_xla_concretefunction_presentation_input_timing`.
The latter's full PDF and generator are absent from this checkout, but its
CSV exports and figure ZIP are available. The full R06 report exports the same
representative trials and their calibrated intervals. We reuse those exports
without selecting new trials or recalculating clocks.

The generator verifies every real-input median and p95 against the corresponding
200 accepted per-call records. `figures/benchmark_sources.json` records source
hashes, selected statistics and timelines, resource attribution, and topology
crop coordinates. The JSON also distinguishes the invocation origin of the
execution plot from the FPGA-arm origin of the streaming plot.

`f1_resolution_depth.pdf` appears in model selection. On 8 November 2026,
the embedded JPEG was replaced with a vector rendering of the original
`hls4ml/results/plots/f1_heatmap.png`, using `hls4ml/results/experiment_summary.csv`
and the same cell selection, values, axes, and color scale as the original
`heatmap()` in `hls4ml/pipeline/experiment_plots.py`. Text contrast is improved
on light cells. Regenerate only this figure with:

```bash
ml_baseline/.venv/bin/python paper/generate_f1_figure.py
```

The RO-count distribution figure is no longer included in the manuscript.
The contextual F3/Coyote v2 comparison is typeset in `sigconf.tex`, using the
presentation's existing table and the bibliography's original references.

Compile and view with the existing user-local Tectonic installation:

```bash
cd paper
/home/sdeheredia/.local/bin/tectonic --synctex --keep-logs sigconf.tex
```

Open `paper/sigconf.pdf` in the PDF viewer. LaTeX Workshop's Tectonic tool
must pass `%DOC_EXT%` (or `%DOC%.tex`), including the filename extension.
