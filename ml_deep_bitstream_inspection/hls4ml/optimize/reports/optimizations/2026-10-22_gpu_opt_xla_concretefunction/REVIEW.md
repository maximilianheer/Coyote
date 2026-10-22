# Report review — 22 October 2026

Reviewed the 13-page PDF, all figure layouts, the generation code, and exported
statistics against the accepted source measurements. No unresolved numerical
or timing-scope issue was found in this review.

## Checks completed

- Verified 426 source hashes and all generated-file hashes.
- Checked 12,000 selected resident calls: 200 calls in each of 60 variant/input
  cells. GPU cells use accepted R06 evidence, including the selected recheck.
- Confirmed retained FPGA statistics match the previous report exactly.
- Recomputed synthetic speedups and verified that stacked phase means add to
  mean CSR14 verdict-availability latency.
- Kept CSR14 result acceptance, CSR9 full-input arrival, CSR15 completion, and
  host observation distinct. Means in Figure 4 are labeled separately from the
  medians in Figures 1 and 2.
- Checked combined R06 compute diagnostics: 20 profiled and 1,000 unprofiled
  calls per representative input. No old split-phase profiles were reused.
- Checked PDF page flow, legends, axis labels, titles, numerical annotations,
  resource count/percentage axes, and standalone exports. Verified all 16
  figures in PNG, SVG, and PDF, plus their ZIP bundle.
- Verified report date **22 October 2026**, measurement date **21 October 2026**,
  chronological folder prefixes, local index links, and 378 preserved historical
  PDF, figure, CSV, and data files. Historical bundles remain byte-identical.

## Corrections made during review

- Corrected an overgeneralized draft conclusion: GPU_HOST wins at 4/64/approximately
  128 MiB; **FPGA_HLS4ML wins at 16 MiB** (1.356 versus 1.447 ms).
- Replaced the previous runtime's separate preprocessing/inference diagnostics
  with R06's joint graph measurements, and used a common y-axis range across
  the two representative input sizes.
- Removed an arrow/label overlap in the P2P schematic.
- Updated dates and report-path references while retaining historical outputs
  and original versions of changed archived source/documentation files.

## Interpretation limits retained

- FPGA W8A8 and GPU FP32 compare implemented systems with different precisions.
- FPGA and R06 GPU results come from independent accepted campaigns. Their
  shared streaming control changes by at most 0.02723% for the selected resident
  workloads; this is a stability check, not a paired-trial confidence interval.
- Standalone compute diagnostics use CPU0-7/NUMA0; board measurements use
  CPU64/NUMA1. Their durations must not be subtracted from board latency.
- Known input lengths are compiled and warmed before timing. Approximately
  137 ms first-call costs for the two diagnostic examples are excluded.
- Internal result acceptance does not imply early update of the public verdict
  register or permission to start reconfiguration.

Run `review_report.py` after `build_report.py` to repeat the numerical,
provenance, artifact, and PDF-structure checks. The machine-readable result is
`data/review.json`. Visual inspection is a separate review step.
