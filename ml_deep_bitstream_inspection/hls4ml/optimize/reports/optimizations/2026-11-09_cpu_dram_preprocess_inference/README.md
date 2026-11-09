# Single-core CPU preprocessing and inference

Created and measured **2026-11-09**, on `hacc-build-03` (Xeon Gold 6234).

- [Reviewed PDF](cpu_dram_preprocess_inference_report.pdf)
- [Standalone figures: PNG, SVG and PDF](standalone_figures.zip)
- [Statistics](data/statistics.csv), [individual trials](data/trial_events.csv), [machine review](data/review.json), [review notes](REVIEW.md)
- Campaign: `hls4ml/optimize/runs/cpu_dram_20261109_031305/` relative to the project root.

| Model | Real-input median latency range |
| --- | ---: |
| Original FP32 | 2.547–3.103 ms |
| Frozen QKeras W8A8, floating CPU operators | 2.694–3.131 ms |

These are per-input pooled medians across eight real inputs, not minimum/maximum individual trials. Timing includes preprocessing and a materialized CPU verdict, starting with raw bytes in local DRAM. File reads, preload, graph compilation, cache setup and warmup are excluded. Model/code remain warm. All worker threads are pinned to CPU2, memory to NUMA2, with numerical-library thread counts of one. The SMT sibling was monitored, not reserved.

The cold condition invalidates the actual zero-copy input storage from CPU data caches before each call. A separate control warms only selected source cache lines. Cache probes and hardware cache-miss counters support the eviction method. TLBs, instructions and intermediate activations are not explicitly flushed.

**19,200 primary measurements**, plus separate stage diagnostics, give **33,600 measured calls**. Each primary cell contains 400 measurements: two independent process sessions, each with 20 warmups followed by 200 measured calls. Session order is reversed; medians differ by up to **14.1%**. Both sessions are preserved and shown separately.

**W8A8 is not a native INT8 CPU performance result.** QKeras applies quantization with floating CPU operators. A separate native INT8 conversion retained all 26 admission verdicts but clipped five scores and reached a maximum absolute score error of 18.237; it is retained as diagnostic evidence and excluded from primary timings. See campaign `int8_conversion/review.json`.

The historical FPGA/GPU appendix uses earlier measurements from a different host and different timing origins. It is contextual evidence, not a controlled same-host accelerator speedup experiment. Independent preprocessing/inference diagnostic timings are not additive components of the fused total.

## Reproduce the analysis without rerunning hardware or measurements

From the project root, use `ml_baseline/.venv/bin/python` without resolving its executable symlink. Archived measurement code is in campaign `software/`; the final analysis/rendering snapshot is in campaign `analysis_sources/`. The environment uses TensorFlow 2.21.0, tf-keras 2.21.0, QKeras 0.9.0, NumPy 1.26.4 and Matplotlib 3.10.8. Rendering additionally needs ReportLab 4.4.3 (installed for this session only in `/tmp/cpu_report_deps`).

```bash
ml_baseline/.venv/bin/python hls4ml/optimize/runs/cpu_dram_20261109_031305/analysis_sources/analyze.py hls4ml/optimize/runs/cpu_dram_20261109_031305 hls4ml/optimize/reports/optimizations/2026-11-09_cpu_dram_preprocess_inference
PYTHONPATH=/tmp/cpu_report_deps ml_baseline/.venv/bin/python hls4ml/optimize/runs/cpu_dram_20261109_031305/analysis_sources/report.py hls4ml/optimize/runs/cpu_dram_20261109_031305 hls4ml/optimize/reports/optimizations/2026-11-09_cpu_dram_preprocess_inference
ml_baseline/.venv/bin/python hls4ml/optimize/runs/cpu_dram_20261109_031305/analysis_sources/review.py hls4ml/optimize/runs/cpu_dram_20261109_031305 hls4ml/optimize/reports/optimizations/2026-11-09_cpu_dram_preprocess_inference
```

Campaign `package_manifest.json` hashes final artifacts, measurement records, source snapshots and validation evidence. `data/model_identities.json` and `data/evidence_manifest.json` pin model/input identity and underlying evidence. Existing reports and unrelated campaigns were preserved.
