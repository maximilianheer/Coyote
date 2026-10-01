# Latency and resource optimization plan

Improve the [res256 checker](../reproducibility/prod_res256_coyote_accel_downsampler_hls4ml_e2e_20260524/MILESTONE_REPORT.md): beat the [GPU baseline](../../GPU_BASELINE.pdf) including transport, approach GPU compute latency, and use ≤10% of each FPGA resource. This document plans experiments; results are pending.

### Progress checklist

- [x] Implement and launch the five-slot [build campaign](build_campaign/README.md) with tmux and hourly ntfy reporting. [Live status](runs/20261001_184524/STATUS.md).
- [ ] Build and validate smaller hello-world PR floorplans; record the smallest working bitstream (§1).
- [ ] Fix the eight-size linear grid and calculate each latency target (§1–2).
- [ ] Prepare benchmark inputs, timing instrumentation, and diagnostic builds; verify parity and timing closure (§2).
- [ ] Run one session per implementation: 20 warm-ups + 200 measured trials per size (§2).
- [ ] Collect latency breakdowns and routed resource reports; identify bottlenecks (§3).
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

Cap the **routed checker wrapper**, including preprocessing, inference, buffers, and control. Also report full-design utilization and matched no-op deltas.

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
3. Inspect `get_dfx_footprint`; test `set_param hd.routingContainmentAreaExpansion false` on the smallest viable candidate. Check routing/timing; the extra size saving is unknown ([AMD](https://docs.amd.com/r/2024.2-English/ug909-vivado-partial-reconfiguration/Expansion-of-CONTAIN_ROUTING-Area)).
4. Keep compression enabled; it is already enabled, so assume **no new compression gain**.

Approximate area scaling: `size ≈ 33.852 MiB × clock regions / 52`.

| Clock regions | Estimated size | Estimated reduction |
| --- | ---: | ---: |
| 16 | 10.42 MiB | 69% |
| 8 | 5.21 MiB | 85% |
| 4 | 2.60 MiB | 92% |
| 2 | 1.30 MiB | 96% |
| 1 | 0.65 MiB | 98% |

**Low-confidence estimates:** target **1–4 MiB** initially; **≈0.65 MiB** is an optimistic minimum if one region fits. There is no proven lower bound, including ≥1 MiB. Compression, frame composition, interfaces, and routing can invalidate area scaling.

- Budget **8 build attempts**: six sizes, one relocation/refinement, one routing-expansion comparison. Adapt failed candidates within this budget.
- Check capacity before implementation; rebuild compatible shells when changing partition boundaries. Preserve interfaces and tool settings.
- Require DRC, timing closure, PR compatibility, and successful hardware loopback.
- Record sizes, hashes, actual footprints, settings, build times, and failures. Use the **smallest validated result** as the benchmark endpoint.

## 2. Bottleneck and cost-attribution experiment

### Trial protocol

- **8 linearly spaced sizes; 1 session per implementation; batch size 1.**
- `S[i] = S_min + round(i × (55,676,772 − S_min) / 7)`, for `i = 0…7`, in bytes. `S_min` is the validated minimum; the maximum is **53.10 MiB**.
- Use real endpoint files. For exact intermediate sizes, truncate/repeat a fixed benign byte sequence; label these **synthetic timing inputs**, never load them through PR, and exclude them from classification metrics.
- Per size: **20 recorded warm-ups + 200 measured trials**. Report the 200-trial summary, all-220 summary, and first-call latency. No separate unwarmed campaign; these are not independent cold starts.
- Keep bytes, weights, clocks, and seeded size order consistent. Report median, p95, maximum, and a 95% confidence interval for p95. Pass only if its upper bound meets the ceiling. One session establishes no between-session consistency.

| Scope | Measured | Warm-ups | Total calls |
| --- | ---: | ---: | ---: |
| One implementation | 1,600 | 160 | 1,760 |
| Two primary paths: host reference + instrumented FPGA-side | 3,200 | 320 | 3,520 |
| Four supplementary paths* | 6,400 | 640 | 7,040 |
| All six paths | 9,600 | 960 | 10,560 |

*Uninstrumented FPGA-side checker, transport/no-op, preprocessing-only, inference-only. Reuse the same eight cases; inference-only uses their prepared tensors. No per-file repetitions or per-trial reprogramming.

### Things to measure

| Component | Latency measurements | Resource attribution |
| --- | --- | --- |
| Memory/transport | Read start/end, accepted beats, stalls | Reader, adapters, FIFOs |
| Preprocessing | First/last byte and output token | Downsampler, normalization, buffers |
| Inference | First input → logit; layer/stall counters | CNN layers, weights, buffers |
| Decision/host | Publication, polling, setup/copy/cleanup | Control and integration logic |

- Implement the FPGA-side memory reader and decision endpoint; include actual memory stalls. Time host work with monotonic clocks.
- Measure stage overlap; do not add overlapping intervals. Compare instrumented/uninstrumented and isolated/integrated designs.
- Collect HLS, synthesis, and routed reports separately. Reconcile wrapper totals and matched no-op deltas; identify shared logic and benchmark-only instrumentation. Resources are per design, not per input size.
- Check preprocessing parity around **65,536** and **4,194,241 bytes**, including adjacent lengths and partial AXI beats. These are functional checks, not extra 200-trial cohorts. Preserve predictions and timing closure.
- Save per-call data, warm-up flags, hashes, configs, clocks, tool versions, and memory conditions. Produce latency-versus-size plots and component resource tables. Keep frozen artifacts unchanged.

### Builds and time budget

| Work | New builds/attempts | Estimated serial build time |
| --- | ---: | ---: |
| Small hello-world search | 8 | 16–32 hours |
| FPGA-side checker: instrumented + uninstrumented | 2 | 8–24 hours |
| No-op, preprocessing-only, inference-only | 3 | 12–36 hours |
| **Total** | **13** | **36–92 hours** |
| Retry allowance | Up to 2 | Up to 24 extra hours |

Reuse the host reference; input sizes require no additional CNN builds. Estimates are provisional: [historical logs](../../datasets/full_dataset_it1/logs/BENIGN_FP00.log) show ≈50 minutes for shell implementation and ≈1 hour per application implementation, plus synthesis/bitgen. Re-estimate after the first build.

- Assuming **10–50 ms/call**: one implementation **18–88 seconds**; both primary paths **35–176 seconds**; all six **2–9 minutes** of calls.
- Reserve **1–2 hours board time** for timing, programming, staging, and checks; another **1–2 hours** for small-PR validation.
- Excludes harness development, debugging, and queues. A matching GPU sweep adds **1,600 measurements + 160 warm-ups** and setup time.

## 3. Identified bottlenecks and cost attribution

Pending measurements.

## 4. Proposed optimizations

Pending bottleneck analysis.

## 5. New experiment and benchmarking comparison

Pending optimization selection.
