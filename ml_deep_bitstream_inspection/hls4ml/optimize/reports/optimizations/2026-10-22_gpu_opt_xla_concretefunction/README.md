# hls4ml-checker versus R06 GPU inference

**Report date: 22 October 2026. Measurement date: 21 October 2026.**

This report uses **R06: XLA + direct ConcreteFunction calls** for GPU_HOST and
GPU_P2P. The primary metric remains **prepared host input → classification result
accepted inside the FPGA (CSR14)**. Full-input arrival (CSR9), operation completion
(CSR15), and host observation are shown separately.

- [PDF report](gpu_opt_xla_concretefunction_report.pdf)
- [Standalone figures](standalone_figures.zip): titled PNG, SVG, and PDF files.
- [Synthetic results](data/synthetic_summary.csv)
- [Validation and provenance](data/validation.json)
- [Review findings](REVIEW.md) and [automated review](data/review.json)

## Selected measurements

| Content | Source |
| --- | --- |
| GPU_HOST / GPU_P2P latency and breakdowns | Accepted `gpu_runtime_investigation_20261021_030038/hardware_xla_concrete` campaign, including accepted matched rechecks |
| Buffering / Streaming / Resource-optimized streaming | Existing `final_benchmarks_gpu_preprocess_v2_20261021_030038` FPGA measurements and resources |
| Combined GPU compute diagnostics | Separate `experiments/R06_xla_concrete/measurement` results |

The two board campaigns use the same machine, device pairing, images, driver,
input identities, CPU64/NUMA1 placement, and timing ABI. The shared OPT_1 control's
resident host-completion medians differ by at most **0.028%** across the twelve
normal workloads. These remain independent campaigns, not paired trials.

GPU inference uses the original FP32 model, batch one. Preprocessing and the CNN
run in one static-length XLA graph, invoked through its cached ConcreteFunction.
Known input lengths are compiled and warmed before timing. The FPGA uses W8A8.

Figure 6 shows combined compute, because splitting the fused graph would change
the execution being measured. These separate diagnostics use CPU0-7/NUMA0,
exclude transport and FPGA result delivery, and must not be substituted for the
board measurements. Profiled kernel/device/host spans use 20 calls; unprofiled
host-synchronized compute uses 1,000 calls.

The historical `report_eligible: false` metadata protected earlier reports from
automatic adoption of experimental results. The user explicitly selected R06
for this new report. That selection is recorded in `data/report_selection.json`;
archived campaign metadata and previous report folders remain unchanged. R07-R10
and DMA32 transport diagnostics are excluded. No builds or benchmarks were run
to generate this report.

## Figures

1. Synthetic verdict-availability latency.
2. Synthetic FPGA_HLS4ML speedup; ratios below one favor the GPU path.
3. Physical setup and the three logical paths, also exported separately.
4. Invocation breakdown and full-input arrival for all three paths.
5. Representative execution timelines and distinct completion events.
6. R06 combined GPU compute diagnostics.
7. Buffering versus resource-optimized streaming latency.
8. FPGA resources for buffering, streaming, and resource-optimized streaming,
   with counts and device-utilization percentages.
9. Reception, preprocessing, and CNN overlap across the three FPGA variants.

Real-bitstream latency bars, speedup bars, and latency scatter appear in the
appendix. Boundary/special-case workloads and a speedup scatter are excluded.

## Reproduction

From the repository root:

```bash
ml_baseline/.venv/bin/python hls4ml/optimize/reports/optimizations/2026-10-22_gpu_opt_xla_concretefunction/test_timing.py
ml_baseline/.venv/bin/python hls4ml/optimize/reports/optimizations/2026-10-22_gpu_opt_xla_concretefunction/build_report.py
ml_baseline/.venv/bin/python hls4ml/optimize/reports/optimizations/2026-10-22_gpu_opt_xla_concretefunction/review_report.py
```

The generator verifies source hashes and recorded summary statistics, derives
CSR14 timing from each call's calibration block, checks event ordering and input
identity, and verifies that stacked phase means sum to verdict availability.
It exports 12,000 accepted calls, statistics with calibration bounds, timelines,
baseline controls, resources, and an evidence manifest. Previous report hashes
are checked again after generation.

Clock bounds describe host/FPGA alignment uncertainty, not statistical confidence
intervals. Overlapping reception, forwarding, computation, and polling lanes
must not be added. Result acceptance is an internal timestamp; it does not imply
that the public verdict register or reconfiguration path releases early.
