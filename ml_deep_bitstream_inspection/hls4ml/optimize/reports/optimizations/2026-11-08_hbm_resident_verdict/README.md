# HBM-resident verdict benchmarks

Report created **2026-11-08**. Measurements **2026-11-08**.

- [PDF report](hbm_resident_verdict_report.pdf): 15 pages.
- [Standalone figures](standalone_figures.zip): 13 titled figures, each PNG/SVG/PDF.
- [Review](REVIEW.md), [validation](data/review.json), [statistics](data/statistics.json).
- [Raw-trial derivation](data/trial_events.csv), [source hashes](data/evidence_manifest.json).

## Scope

OPT_10 = FPGA_HLS4ML: selective HBM gather, sample-driven preprocessing, streaming OPT_6 CNN.
OPT_11 = GPU_P2P: full raw HBM input forwarded to MI210 GPU0, R06 XLA + ConcreteFunction FP32, autonomous FPGA verdict polling.

Primary interval: accepted FPGA arm (ABI5 CSR6) to FPGA verdict event (CSR24).
The complete raw input starts in FPGA HBM. Host preload, file reads, compilation,
PR and the host observing completion are excluded. The host emulates an embedded
CPU for preload/control; GPU execution remains CPU dispatched.

Eight unchanged real inputs and four established synthetic inputs: 20 warmups
and 200 measured trials each, per variant (**4,800 primary measured calls**).
Three cutoff diagnostics add 1,200 calls; additional boundary, repeatability and
profiling calls remain separate. Both 520-call admissions passed. No new FPGA
build was launched. Old reports are preserved.

## Interpretation and limitations

- Initial-program real medians: FPGA 2.679–3.074 ms; GPU 1.327–8.012 ms.
- GPU wins at R1/R2; FPGA wins at R3–R8. R3 has a small margin.
- **Cross-program FPGA stability gate failed:** initial versus closing medians
  changed by up to 9.825%. Within-program repeats changed by at most 0.076%.
  Old/new transport adapters agree in the second programmed state. Three
  identical-image programming cycles are shown; the root physical cause is
  not proven. Do not cite this report as demonstrating <5% cross-program drift.
- Main bars retain program 1. Hollow markers and speedup ranges show the other
  programmed states; Appendix A5 documents the investigation.
- The first integrated profiling attempt failed with a ROCm/HIP error. Separate
  fused-compute profiles after drained P2P delivery passed. Failed evidence is
  preserved and excluded; no profiled result replaces primary latency samples.
- Physical HBM-wire traffic, maximum outstanding requests, HBM stall counts and
  FIFO peak occupancy are unavailable. Requested bytes are labeled accordingly.

## Reproduce analysis and figures

From the repository root:

```bash
ml_baseline/.venv/bin/python hls4ml/optimize/build_campaign/hbm/analyze.py \
  hls4ml/optimize/runs/hbm_benchmark_20261108 \
  hls4ml/optimize/reports/optimizations/2026-11-08_hbm_resident_verdict
ml_baseline/.venv/bin/python hls4ml/optimize/build_campaign/hbm/report.py \
  hls4ml/optimize/runs/hbm_benchmark_20261108 \
  hls4ml/optimize/reports/optimizations/2026-11-08_hbm_resident_verdict
ml_baseline/.venv/bin/python hls4ml/optimize/build_campaign/hbm/review.py \
  hls4ml/optimize/runs/hbm_benchmark_20261108 \
  hls4ml/optimize/reports/optimizations/2026-11-08_hbm_resident_verdict
```

The report reuses the archived R06 input identities/data, resource conventions,
and existing affine clock model. Its generator snapshot is `build_report.py`;
maintained code is in `hls4ml/optimize/build_campaign/hbm/`.
