# Latency and resource optimization plan

Improve the [res256 checker](../reproducibility/prod_res256_coyote_accel_downsampler_hls4ml_e2e_20260524/MILESTONE_REPORT.md): beat the [GPU baseline](../../GPU_BASELINE.pdf) including transport, approach GPU compute latency, and use ≤10% of each FPGA resource. This is the campaign plan for those three goals. Restored from commit `31a8d154`, with verified build results added on **2026-10-07**. S_I is one optimization within this plan, not a replacement for it. **Build recovery is paused; no builds, board programming, or benchmarks are running.**

### Progress checklist

- [x] Implement and launch the five-slot [build campaign](build_campaign/README.md) with tmux and hourly ntfy reporting. [Live status](runs/20261001_184524/STATUS.md).
- [x] Generate seven smaller hello-world PR bitstreams; smallest built result: **HR, 5.284 MiB** (§1).
- [ ] Validate PR compatibility and hello-world loopback on hardware (§1).
- [x] Calculate the provisional eight-size grid and latency targets from the smallest built result (§2).
- [ ] Confirm the minimum on hardware and regenerate benchmark inputs/analysis for that grid (§2).
- [x] Build I, U, N, P, C and optimized S_I; verify source hashes, parity/control checks, routed timing and bitstream artifacts.
- [ ] Align comparison clocks and transport boundaries before benchmarking (§2).
- [ ] Run one session per implementation: 20 warm-ups + 200 measured trials per size (§2).
- [x] Extract routed wrapper resources and identify the outstanding BRAM/DSP limits (§3).
- [ ] Measure latency breakdowns and finish component cost attribution (§3).
- [ ] Select optimizations against the latency and ≤10% resource targets (§4).
- [ ] Implement selected optimizations and repeat the benchmark; compare with the original checker and GPU baseline (§5).

## 1. Performance targets

### Latency

Measure **raw bytes available on FPGA → decision visible to FPGA control**, including memory reads, transport, preprocessing, inference, and publication. Report the current host-driven path separately.

**Target: FPGA p95 ≤90% of GPU median at every tested size.**

| Size | GPU median (ms) | FPGA p95 ceiling (ms) |
| --- | ---: | ---: |
| 64 KiB | 0.190 | 0.171 |
| 256 KiB | 0.200 | 0.180 |
| 1 MiB | 0.250 | 0.225 |
| 4 MiB | 0.450 | 0.405 |
| 16 MiB | 1.240 | 1.116 |
| 64 MiB | 4.390 | 3.951 |
| 128 MiB | 8.590 | 7.731 |

Interpolate targets linearly in bytes between these anchors. The GPU figures exclude HBM stalls; matching GPU measurements are needed to confirm wins at intermediate sizes with realistic memory access.

| Compute | Current FPGA estimate | GPU stretch reference |
| --- | ---: | ---: |
| Preprocessing + inference | 3.346 ms mean | 0.165 ms |
| Inference only | 1.082 ms | ≈0.147–0.148 ms* |

*GPU inference is derived from rounded labels. FPGA estimates exclude host overhead and vary with input size. Existing observed batch-16 times: **63.30 ms predict**, **160.85 ms Python wall**; remeasure at batch 1.

### Resources

Cap the **routed checker wrapper**, including preprocessing, inference, buffers, and control. Also report full-design utilization and matched no-op deltas. The historical column below is the production HLS user-logic instance; §3 distinguishes that from the larger integrated campaign wrapper.

| Resource | Current wrapper | ≤10% allocation limit |
| --- | ---: | ---: |

| LUT | 58,323 (4.47%) | 130,368 |
| Registers | 72,600 (2.78%) | 260,736 |
| BRAM, 36-Kbit tile equivalents | 360 (17.86%) | 201.5 |
| URAM | 11 (1.15%) | 96 |
| DSP | 1,328 (14.72%) | 902 |

### Experiment: smallest valid PR bitstream, ≤28 MiB

Existing corpus: **524 files, 28.92–53.10 MiB**. Rebuild **one functional hello-world example** with smaller floorplans; copying its existing `.bin` does not establish a minimum.

1. Start from [no-debug hello-world](../../datasets/full_dataset_it1/hw/apps/benign_variants/V01_hello_world_nodbg/vfpga_top.svh). Removing the ILA alone saved only **1.24%**: 34.277 → 33.852 MiB.
2. Shrink [FP00's 52-clock-region allocation](../../datasets/full_dataset_it1/hw/floorplans/FP00_full.xdc) to compact regions of **16, 8, 4, 2, 1**, then narrower if feasible. Prefer one SLR. Region reduction is the main size-reduction mechanism ([AMD](https://docs.amd.com/r/2024.2-English/ug909-vivado-partial-reconfiguration/Partial-Bitstreams)).
3. Inspect `get_dfx_footprint` and record the actual placement/routing footprint.
4. Keep compression enabled; it is already enabled, so assume **no new compression gain**.

Approximate area scaling: `size ≈ 33.852 MiB × clock regions / 52`.

| Clock regions | Estimated size | Estimated reduction |
| --- | ---: | ---: |
| 16 | 10.42 MiB | 69% |
| 8 | 5.21 MiB | 85% |
| 4 | 2.60 MiB | 92% |
| 2 | 1.30 MiB | 96% |
| 1 | 0.65 MiB | 98% |

**Historical estimates, superseded by the builds below:** the 1–4 MiB target and optimistic ≈0.65 MiB minimum were not achieved. The smallest built candidate is **5.284 MiB**, not a proven hardware-valid or absolute minimum. Size is not monotonic in clock-region count; frame composition and routing matter.

- **Seven hello-world variants** pass implementation; hardware PR validation remains pending.
- Check capacity before implementation; rebuild compatible shells when changing partition boundaries. Preserve interfaces and tool settings.
- Require DRC, timing closure, PR compatibility, and successful hardware loopback.
- Record sizes, hashes, actual footprints, settings, build times, and failures. Use the **smallest validated result** as the benchmark endpoint.

### Current build results — recovery paused

Evidence: [campaign state](runs/20261001_184524/status.json),
[job artifacts](runs/20261001_184524/jobs/), and
[archived attempts](runs/20261001_184524/attempts/).
**All 13 builds included in this plan pass implementation.** Passed means nonempty
bitstreams, intact prepared-source hashes, and passing final routed setup/hold/pulse-width
checks. It does not mean board/PR validation or measured performance.

| Hello-world build | Partial bytes | MiB | Result |
| --- | ---: | ---: | --- |
| H16 | 18,876,484 | 18.002 | Passed |
| H8 | 10,160,176 | 9.689 | Passed |
| H4 | 12,004,440 | 11.448 | Passed |
| H2 | 6,222,564 | 5.934 | Passed |
| H1 | 5,544,256 | 5.287 | Passed; relocated to BRAM-capable region |
| HN | 5,572,388 | 5.314 | Passed; narrower slices did not reduce bytes |
| HR | 5,540,996 | **5.284** | Passed; smallest, region X2Y1 |

The hello-world copy restores normal stream-valid behavior and uses the same
minimal ILA as the diagnostics; frozen dataset sources are unchanged.

| Diagnostic | Function | Attempt | HBM AXI MHz | Setup / hold slack (ns) |
| --- | --- | ---: | ---: | ---: |
| I | Sequential, instrumented | 5 | 400 | +0.008 / +0.009 |
| U | Sequential, uninstrumented | 4 | 400 | +0.028 / +0.009 |
| N | Transport only | 4 | 400 | +0.044 / +0.009 |
| P | Preprocessing only | 3 | 450 | +0.022 / +0.007 |
| C | Inference only | 3 | 450 | +0.037 / +0.006 |
| S_I | Streaming preprocessing + CNN, instrumented | 2 | 450 | +0.019 / +0.006 |

All six passed bitstream generation. **Checker/control clocks remain 250 MHz.**
I/U/N were rebuilt with actual HBM AXI clocks reduced from 450 to 400 MHz after
HBM-only timing failures; generated IP/MMCM settings and routed clocks verify.
Original attempts are preserved. Completion alerts and the final campaign summary
were delivered by ntfy on October 3; the finished tmux session is no longer live.

## 2. Bottleneck and cost-attribution experiment

### Trial protocol

- **8 linearly spaced sizes; 1 session per implementation; batch size 1.**
- `S[i] = S_min + round(i × (55,676,772 − S_min) / 7)`, for `i = 0…7`, in bytes. `S_min` is the validated minimum; the maximum is **53.10 MiB**.
- Provisional `S_min = 5,540,996` bytes (HR); finalize only after hardware validation. The old S_I input set and `build_campaign/benchmark.py` still hard-code **28.92–53.10 MiB**: update both preparation and analysis before running the restored experiment.

| Provisional bytes | MiB | Interpolated FPGA p95 ceiling (ms) |
| ---: | ---: | ---: |
| 5,540,996 | 5.284 | 0.481 |
| 12,703,250 | 12.115 | 0.886 |
| 19,865,503 | 18.945 | 1.290 |
| 27,027,757 | 25.776 | 1.693 |
| 34,190,011 | 32.606 | 2.097 |
| 41,352,265 | 39.437 | 2.500 |
| 48,514,518 | 46.267 | 2.904 |
| 55,676,772 | 53.098 | 3.307 |

These are interpolated targets, not measured GPU results at these sizes.

- Use real endpoint files. For exact intermediate sizes, truncate/repeat a fixed benign byte sequence; label these **synthetic timing inputs**, never load them through PR, and exclude them from classification metrics.
- Per size: **20 recorded warm-ups + 200 measured trials**. Report the 200-trial summary, all-220 summary, and first-call latency. No separate unwarmed campaign; these are not independent cold starts.
- Keep bytes, weights, clocks, and seeded size order consistent. Report median, p95, maximum, and a 95% confidence interval for p95. Pass only if its upper bound meets the ceiling. One session establishes no between-session consistency.

| Scope | Measured | Warm-ups | Total calls |
| --- | ---: | ---: | ---: |
| One implementation | 1,600 | 160 | 1,760 |
| Two primary paths: host reference + instrumented FPGA-side | 3,200 | 320 | 3,520 |
| Four supplementary paths* | 6,400 | 640 | 7,040 |
| Original six paths | 9,600 | 960 | 10,560 |
| Added S_I optimized path | 1,600 | 160 | 1,760 |
| Current seven paths | **11,200** | **1,120** | **12,320** |

*Uninstrumented FPGA-side checker, transport/no-op, preprocessing-only, inference-only. Reuse the same eight cases; inference-only uses their prepared tensors. No per-file repetitions or per-trial reprogramming.

### Things to measure

| Component | Latency measurements | Resource attribution |
| --- | --- | --- |
| Memory/transport | Read start/end, accepted beats, stalls | Reader, adapters, FIFOs |
| Preprocessing | First/last byte and output token | Downsampler, normalization, buffers |
| Inference | First input → logit; whole-CNN duration and stalls | CNN layers, weights, buffers |
| Decision/host | Publication, polling, setup/copy/cleanup | Control and integration logic |

- The FPGA-side reader/decision instrumentation is built. It measures **accepted FPGA read request → captured decision**, including memory stalls; host offload/setup and request-acceptance wait are excluded. Measure these missing intervals separately and align the GPU/FPGA transport boundary before claiming a win. Time host work with monotonic clocks.
- S_I timestamps record preprocessing/CNN overlap, payload arrival, logit and decision. Its real-IP RTL tests passed eleven boundary lengths, exact tokens/logits, consecutive frames, stalls, backpressure, and early CNN consumption. These are functional/cycle checks, not board latency results.
- Resolve the **400/450 MHz HBM mismatch** before attributing differences between S_I/P/C and I/U/N. Use matching-clock references or explicitly report separate clock conditions; do not subtract unmatched timings as component costs.
- Extend the current S_I-focused analysis to all planned paths, warm-up-inclusive summaries and p95 confidence bounds. Existing counters time whole stages; per-layer runtime attribution would need additional instrumentation.
- Measure stage overlap; do not add overlapping intervals. Compare instrumented/uninstrumented and isolated/integrated designs.
- Collect HLS, synthesis, and routed reports separately. Reconcile wrapper totals and matched no-op deltas; identify shared logic and benchmark-only instrumentation. Resources are per design, not per input size.
- Check preprocessing parity around **65,536** and **4,194,241 bytes**, including adjacent lengths and partial AXI beats. These are functional checks, not extra 200-trial cohorts. Preserve predictions and timing closure.
- Save per-call data, warm-up flags, hashes, configs, clocks, tool versions, and memory conditions. Produce latency-versus-size plots and component resource tables. Keep frozen artifacts unchanged.

### Builds and time budget

Current scope: **13 completed builds**—seven hello-world variants and six diagnostics including S_I. No builds are currently scheduled. Additional matched-clock references may be needed before comparison; their count/time remain to be decided.

Reuse the host reference; input sizes require no additional CNN builds. Successful diagnostic attempts actually took **3.8–9.8 hours each**, excluding earlier failed attempts and queue time. Budget any future rebuilds from these current attempt timings.

- Assuming **10–50 ms/call**: one implementation **18–88 seconds**; both primary paths **35–176 seconds**; all seven paths including S_I **2–10 minutes** of calls. These are planning estimates, not observed campaign timings.
- Reserve **1–2 hours board time** for timing, programming, staging, and checks; another **1–2 hours** for small-PR validation.
- Excludes harness development, debugging, and queues. A matching GPU sweep adds **1,600 measurements + 160 warm-ups** and setup time.

## 3. Identified bottlenecks and cost attribution

**Latency: pending board measurements.** Build timing closure and RTL parity do
not establish an inference-speed improvement or a GPU win.

Routed integrated wrapper (`inst_user_wrapper_0`), including control, transport
adapters/FIFOs and debug instrumentation; BRAM = RAMB36 + RAMB18/2:

| Variant | LUT | Registers | BRAM tiles | URAM | DSP |
| --- | ---: | ---: | ---: | ---: | ---: |
| I | 67,709 | 88,552 | 385 | 11 | 1,328 |
| S_I | 67,323 | 88,846 | 385 | 11 | 1,328 |
| U | 66,842 | 87,969 | 385 | 11 | 1,328 |
| N | 9,006 | 15,487 | 18 | 0 | 0 |
| P | 14,627 | 21,150 | 55 | 0 | 16 |
| C | 66,221 | 85,983 | 385 | 11 | 1,312 |

Source: each job's `build/reports/shell_utilization_hierarchical.rpt`.
S_I uses **19.10% BRAM and 14.72% DSP**, above the ≤10% goals; LUT, registers,
and URAM are below 10%. Its HLS-model subinstance alone remains at **360 BRAM
and 1,328 DSP**, comparable in scope to the historical production table.
Streaming has not reduced either limiting resource. Resource differences between
isolated variants are not strictly additive; reconcile shared logic and synthesis
pruning before assigning component costs. Full-design reports remain separate.

## 4. Proposed optimizations

- **Implemented candidate:** S_I overlaps preprocessing and CNN execution and fixes the small/intermediate-input sampler. Production weights/normalization are preserved; parity and routed timing pass. Board speedup is unmeasured.
- **Next resource candidates:** reduce buffer/weight-storage cost and increase arithmetic reuse to target BRAM/DSP, checking parity and the resulting latency tradeoff before selecting builds.

## 5. New experiment and benchmarking comparison

1. Hardware-validate the smallest generated PR candidate before fixing the benchmark minimum.
2. Align HBM clocks/reference scope; regenerate the eight-size inputs and analysis.
3. Run the single-session protocol for the original paths plus S_I; compare against the production checker and a matching GPU sweep.
4. Fill latency/component results, check each p95 ceiling and resource limit, then select the next optimization round. **No board benchmark or GPU win has yet been demonstrated by this campaign.**
