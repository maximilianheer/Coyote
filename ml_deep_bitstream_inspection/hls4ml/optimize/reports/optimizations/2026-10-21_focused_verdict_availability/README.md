# Focused report: verdict availability inside the FPGA

The primary endpoint is acceptance of the classification score inside the FPGA
(CSR14), measured from invocation with prepared input in host RAM. Full-input
arrival (CSR9), final FPGA completion (CSR15), and host observation are separate.
The public verdict register need not be updated at CSR14. No early PR admission
behavior is implied.

This folder reanalyzes the accepted `final_benchmarks_gpu_preprocess_v2_20261021_030038`
campaign. It does not contain later GPU runtime experiments or new board calls.
Previous report folders are preserved. This report changes the latency endpoint;
its headline values are therefore not interchangeable with older host-completion
latencies.

From the repository root:

```bash
ml_baseline/.venv/bin/python hls4ml/optimize/reports/optimizations/2026-10-21_focused_verdict_availability/test_timing.py
ml_baseline/.venv/bin/python hls4ml/optimize/reports/optimizations/2026-10-21_focused_verdict_availability/build_report.py
```

- `focused_verdict_availability_report.pdf`: revised focused report.
- `figures/`: titled PNG, SVG, and PDF images, including separate setup diagrams.
- `standalone_figures.zip`: the 16 titled figures in all three formats, with their catalog.
- `data/trial_events.{csv,json}`: 12,000 accepted calls, raw event counters,
  calibrated endpoints and bounds, reception durations, completion delays,
  input identity, and source-evidence paths. Original host-completion latency is retained.
- `data/latency_statistics.csv`: median, mean, and p95 per variant/input/metric;
  calibration bounds on the primary metric's median and p95.
- `data/phase_means.csv`: elapsed host intervals clipped at result availability;
  their means add to mean result-availability latency.
- `data/timelines.json`: actual representative trials, selected by result availability.
- `data/figure_catalog.json`: code-generated figure titles and captions.
- `data/validation.json`: evidence and timing validation summary.
- `evidence_manifest.json`: input/output hashes and preserved-report hashes.

Clock uncertainty bounds describe feasible host/FPGA alignment, not sampling
confidence intervals. GPU phase intervals are host-observed spans, not isolated
GPU arithmetic costs. Concurrent reception/forwarding/compute lanes must not
be added. P2P result availability includes autonomous polling and payload retrieval.
