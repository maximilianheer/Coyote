# Paper figures

## Section 6: local inspection versus GPU offloading — 2026-11-08

Section 6 now uses the November 8 HBM-resident campaign. The scientific question
is verdict latency once a complete bitstream is locally available to the FPGA;
HBM is the local-storage implementation. Preload and file I/O are excluded,
GPU inference remains CPU-dispatched, and FPGA verdict polling is autonomous.
The earlier host-fed figures below remain archived but are no longer included
in Section 6. Detection quality and all manuscript sections outside Section 6
are unchanged by this update.

| Current figure | Source adaptation | Editable source |
| --- | --- | --- |
| `benchmark_local_setup.pdf` | Report `03_topology`, restyled to match Figure 3 with original Coyote icons and colors | `benchmark_local_setup.pptx` |
| `benchmark_local_latency.pdf` | Report `01_real_latency` and `02_real_speedup`; shared R1–R8 order, initial-state medians/p95 and median speedup | `benchmark_local_latency.pptx` |
| `benchmark_local_execution_r4.pdf` | Report `04_timelines`, R4 only; original nearest-median trials on a shared 0–5 ms axis | `benchmark_local_execution_r4.pptx` |

Figure 4 now uses Figure 3's Coyote artwork and styling: dashed device
boundaries, green memory blocks, teal checker blocks, gray result blocks,
black connectors, and Arial labels. `generate_coyote_benchmark_setup.py`
reuses the original CPU, memory, neural-network, binary, and shield SVG
geometry from `../coyote-figure.pptx`, converted into editable freeform paths.
The FPGA logic-gate icon matches Figure 3. GPU-card and mailbox icons are
native editable vector shapes. The data paths and timing scope are unchanged.
The shared generator delegates the setup figure to this drawing module.

All files are under `figures/`. PowerPoint text, shapes, connectors, bars,
markers, and axes are editable objects, not screenshots. The PDF and PNG are
vector/preview outputs drawn from the same geometry with Matplotlib. Open the
PPTX in PowerPoint to edit; export the modified slide as the matching PDF for
LaTeX. Port manual edits back to the generator before regenerating.

Source report: `../hls4ml/optimize/reports/optimizations/2026-11-08_hbm_resident_verdict/`.
Sources are read only. Regenerate the paper derivatives from the project root:

```bash
PYTHONPATH=/tmp/paper-figure-deps ml_baseline/.venv/bin/python paper/generate_local_inspection_figures.py
```

The generator needs `python-pptx`, Matplotlib, and NumPy, and shares drawing
helpers with `generate_background_figure.py`. If the temporary dependency
folder has expired, install `python-pptx` in the selected Python environment.
`figures/benchmark_local_sources.json` records source hashes, selected R4 trials,
resource accounting, and deployment calculations. The generator checks all
32 source workload/state cells against accepted trial medians and p95 values.
The latency figure shows only initial-state medians and p95 ticks; later-cycle
markers and speedup ranges are omitted per the user's editorial instruction.
The 9.825% cross-program variation remains documented in the manuscript and
archived report. No new measurements or report outputs are generated.


## Editable standalone Coyote diagram

Created and revised 8 November 2026 for Section 5.
`figures/coyote_network_standalone.pptx` directly reuses the original objects
from `../coyote-figure.pptx`. Per the user's preference, it preserves the FPGA
layout, colors, fonts, icons, shell and service blocks, checker, admission
branches, and TLB/vFPGA groups. It replaces the CPU/PCIe submission path with
a compact user-bitstream card above the FPGA, reusing the original user and
binary icons. The narrower canvas enlarges the FPGA at paper width. HBM,
100G networking, and the checker are enlarged or emphasized, with blue
outlines and arrows tracing user input → networking → HBM → checker verdict
→ admission to PR of a selected vFPGA. PR loads the raw bitstream from HBM;
the highlighted sequence is not a claim that the CNN emits a bitstream.
The red reject branch remains separate. Obsolete routing and decorative
arrows are removed to keep the admission sequence clear. The shell's XDMA block remains
as architectural context; it is not the depicted ingress path.

The complete admission path remains proposed. Acceptance and complete input
reception are required before PR, as explained in Section 5. The paper's
reported measurements remain host-submitted.

Regenerate the editable PPTX from the project root:

```bash
PYTHONPATH=/tmp/paper-figure-deps ml_baseline/.venv/bin/python paper/generate_coyote_network_figure.py
```

Open it in Microsoft PowerPoint to edit and export the slide to
`figures/coyote_network_standalone.pdf`. All original SVG icons remain vector
assets; the generator exposes their existing relationship in the standard
image slot as well as the Office SVG extension for compatible rendering.
Text, shapes, connectors, and groups remain editable. No flattened slide is
used. Preserve the original source presentation.

The current PDF is an actual LibreOffice export of this PPTX, and its PNG is
a preview of that PDF. Automated export is available with
`--soffice /path/to/soffice`. A temporary user-local LibreOffice 7.3 renderer
was extracted under `/tmp/paper-libreoffice/root` without system installation.
It needs its `program` directory first in `LD_LIBRARY_PATH`, followed by its
`usr/lib/x86_64-linux-gnu` directory. Its local configuration paths were
relocated and `.registry` defaults copied to its local `etc/libreoffice/registry`.
Those temporary files are not a persistent dependency; a regular LibreOffice
installation or PowerPoint can export the PPTX. Do not regenerate after manual
PowerPoint edits unless those edits have also been ported to the script.

## Editable background diagram

`figures/background_threat_model.pptx` contains one fully editable slide,
adapted from slide 4 of the hls4ml presentation. The simplified, untitled
diagram reuses the happy/devil faces, binary data, shield, gears, lightning,
and scorpion icons from
`../[hls4ml] ML-Based Deep Bitstream Inspection for Serverless FPGAs .pptx`
(slide 4; media images 11, 7, 10/9, 8, 12, 13, and 14). These SVG outlines are
converted to grouped, editable PowerPoint freeform shapes. Text boxes and
connectors are also editable. The native logic-gate FPGA symbol is adapted
from slide 7, group 119. A newly drawn thermometer represents heating. The
FPGA outline encloses both inspection and partial reconfiguration.
The diagram now matches Figures 3 and 4: a dashed FPGA boundary, a black
FPGA icon, rectangular blocks, teal inspection fill, green PR fill, and
consistent Arial labels. Red and green retain their threat/reject and allow
meanings. The shared Coyote drawing helpers keep these styles consistent.
`background_threat_model.pdf`
is the vector version included in the background section, and the PNG is a
preview. Created 8 November 2026.

The caption distinguishes the proposed admission/control path from the measured
checker implementation. The dashed red arrow shows physical effects only if
malicious logic is admitted, not a bypass of inspection.

Both formats are generated from the same layout in
`generate_background_figure.py`, which needs Matplotlib and `python-pptx`:

```bash
PYTHONPATH=/tmp/paper-figure-deps ml_baseline/.venv/bin/python paper/generate_background_figure.py
```

`python-pptx` was installed into `/tmp/paper-figure-deps` for this generation.
If that temporary directory is unavailable, install `python-pptx` in your
Python environment and omit the `PYTHONPATH` prefix. For manual changes, edit
the PowerPoint and export its slide as `figures/background_threat_model.pdf`.
Do not rerun the generator afterward unless you also port those changes to
the script, because generation replaces both outputs. The older Coyote
integration diagram (previously Figure 3, `coyote_integration_path.pdf`) is
no longer included in the manuscript; its source asset is preserved.

## Benchmark and model-selection figures

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
