# HBM-resident inspection, including the small-input preprocessing fix

Saved: 2026-11-07. Status: planned; saving this document does not launch builds.
Option 1: raw bitstream already in FPGA HBM, ready for inspection and later PR.

## Scope and variants

| Iteration | Report label | Processing path |
| --- | --- | --- |
| `OPT_10_HBM_GATHER_DSP_B2_RF72_RF288` | FPGA_HLS4ML | Selected HBM words → optimized preprocessing → streaming OPT_6 CNN |
| `OPT_11_HBM_GPU_P2P_R06` | GPU_P2P | Full bitstream from HBM → P2P → R06 FP32 preprocessing/inference → autonomous FPGA polling |

The existing host emulates the embedded CPU by loading HBM before measurement.
Implementing a soft CPU and performing PR are outside this campaign. Preserve
the raw HBM contents for later PR. Retain the CPU-managed GPU runtime; this is
not a demonstration of fully hostless GPU operation.

## Preprocessing fix and memory update

- [ ] Record the finding and implementation requirement in `MEMORY.md`.
- [ ] Replace the unnecessary byte-by-byte scan for
  `65,536 < input_bytes < 4,194,241` with equivalent sample-driven processing.
  The cutoff is approximately 4 MiB; smaller inputs at or below 65,536 bytes
  already require processing each available byte.
- [ ] Generate the 65,536 output pixels directly. Fetch aligned 64-byte HBM
  words and reuse cached words when multiple samples select the same word.
- [ ] Use `build_campaign/hardware/common/direct_preprocess.hpp` as a reference;
  write readable, independently validated code for the HBM interface.
- [ ] Preserve integer sample positions, inversion, normalization, fixed-point
  conversion and padding. Raw zero padding must produce normalized 1.0 pixels.
- [ ] Preserve historical sources and measurements; record new code and evidence.

Expected effect: eliminate the unnecessary scan below the cutoff. HBM access,
pixel production and CNN backpressure still constrain performance. The eight
existing real bitstreams are above the cutoff, so this fix alone should not
improve their predicted results.

## Implementation and measurements

- Enable Coyote HBM in both builds with matching settings: one card-memory
  stream, 32 outstanding-request credits, 64 active TLB entries, 250 MHz app clock.
- Use bounded, ordered HBM reads for gather; cache duplicate word requests.
- Retain OPT_6 weights, reuse factors, validated FIFO depths and first-pixel
  guard. No repeat FIFO profiling or custom conv0 optimization.
- Retain R06 XLA + ConcreteFunction FP32 inference, external-DMA visibility
  checks and autonomous mailbox polling for GPU_P2P.
- Add a versioned HBM benchmark ABI: source address, raw length, trial identifier,
  start/status and timestamp-validity fields. Old collectors reject unknown ABI.
- Include transport-only diagnostic modes in the same builds.

Primary interval: **FPGA-local start acceptance → verdict accepted at FPGA**.
Exclude preload, file reading, GPU compilation and PR; retain preload diagnostics.

| Measurement | Purpose |
| --- | --- |
| First/last HBM request and return; bytes and outstanding requests | Memory latency and bandwidth |
| First/last pixel, CNN input and result | Preprocessing/inference overlap |
| FPGA P2P transmit interval and GPU input readiness | Forwarding versus GPU-visible completion |
| Fused GPU device span, kernel sum and synchronized call time | Preserve R06 scopes; do not invent a split of fused work |
| Publication, poll requests/window and FPGA acceptance | Return-path overhead |
| Full transfer/drain completion, stalls and FIFO occupancy | Backpressure independent of verdict timing |
| Routed resources and timing closure | Gather, HBM and GPU-control costs |

Separate physical traffic bandwidth from effective inspection rate. Archived
comparisons use compatible FPGA-local timing where available and explicitly
identify different input residency.

## Report and figures

Create `reports/optimizations/YYYY-MM-DD_hbm_resident_verdict/` using its actual
creation date. Preserve existing reports. Export a PDF and titled standalone
PNG/SVG/PDF figures; distinguish report and measurement dates.

| Figure | Plot, legend and axes |
| --- | --- |
| 1. Real-bitstream verdict latency | Grouped median bars and p95 markers; blue FPGA_HLS4ML, orange GPU_P2P. X: R1–R8 with MiB. Y: ms. |
| 2. FPGA speedup | One bar per real input. X: R1–R8. Y: GPU median / FPGA median; 1× reference. |
| 3. Topology | Untimed CPU preload, HBM, gather/CNN, PCIe P2P GPU and verdict mailbox. |
| 4. Timing breakdown | FPGA/GPU panels for R1, R4 and R8; parallel activity lanes. X: local elapsed ms. Vertical verdict marker; never sum overlap. |
| 5. Traffic and throughput | X: real inputs. Separate panels: physical MiB and measured GB/s. Distinguish HBM, PCIe and useful sampled bytes. |
| 6. Previous versus HBM deployment | Archived host-fed versus new HBM-resident timings with compatible local boundaries. Different residency is explicit, not an isolated causal optimization. |
| 7. Predictions versus measurements | X: input MiB. Y: verdict ms. Measured points, GPU 4.1/8.5/15.75 GB/s scenarios and FPGA gather sensitivity band. Faster rates hypothetical unless measured. |
| 8. Resources | LUT/FF/BRAM/DSP/URAM small multiples; archived OPT_6 and two new builds. Counts left, device % right; application/full-shell accounting separate. |

Appendix: established synthetic latency/speedup; small-input diagnostics with
separate matched HLS-cycle and measured HBM-verdict panels; real distributions,
GPU diagnostics, HBM stalls, parity and timing evidence. Omit file-to-verdict
plots because the defined starting state is HBM residency.

## Validation, execution and expected results

- [ ] Test empty/short inputs, 64-byte and 65,536-byte boundaries, exact cutoff ±1.
- [ ] Include 1 MiB, 2 MiB, 4 MiB−64 B and 4 MiB diagnostics.
- [ ] Compare all pixels to the reference; test variable memory latency,
  backpressure, reset/idle, consecutive frames and delayed/stale mailboxes.
- [ ] Verify HBM contents before/after; require exact FPGA parity and existing
  GPU numerical/verdict checks (finite results, existing 1e-4 tolerances).
- [ ] Run 520-call admission per variant. Then 20 warmups and 200 measured trials
  for each of eight real and four established synthetic workloads; small-input
  diagnostics are separate. Profiling uses separate calls.
- [ ] Repeat FPGA controls at opening/closing; investigate drift above 5%.
- [ ] Build both variants concurrently after toolchain/access preflight; benchmark
  sequentially under the board lease. Attach ntfy build and campaign monitors
  to `coyote-build-sdeheredia`.

Expected: FPGA latency becomes less dependent on raw size through selective
reads; GPU latency remains sensitive to full-input P2P. The small-input fix
removes avoidable work, without guaranteeing size-independent verdict latency.

ETA from implementation start: first results approximately 3–5 working days;
validated report 4–7 working days, conditional on access and timing closure.
Allow roughly 6–16 hours per build attempt. The preprocessing fix is included
in the same two builds. Achieving hypothetical 15.75 GB/s is not an acceptance gate.
