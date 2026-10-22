# Direct-host build campaign

## Final FPGA/GPU benchmarks — 2026-10-19

- Campaign: `../runs/final_benchmarks_gpu_u55c_20261019`; snapshot controller `tooling/final_benchmark.py`, main state `status.json`.
- OPT_1 → OPT_0 → OPT_6 → GPU_HOST → GPU_P2P → OPT_1 repeat. Same 15 inputs, 520-call admission, pilot, 20 warmups + 200 measurements per input and scope. GPU0 FP32; FPGA quantized references remain separate.
- Use U55C **device2, 81:00.0**, CPU64/NUMA1 on `hacc-gpu-u55c-01`. Device1's PCIe root port is absent following reboot; its failed programming/admission preflight is preserved. See MEMORY.md before reusing older device mappings.
- Both resident and warm-cache file-to-verdict scopes are recorded. GPU phase diagnostics use separate TensorFlow device traces; their synchronized timings must not be substituted for unprofiled e2e timings.
- One board lease spans programming and collectors. The GPU collector intentionally does not reacquire it. The standard reset-enabled driver is required.
- `final_benchmark_run` and `final_benchmark_monitor` tmux sessions; ntfy sends variant outcomes and campaign failures/completion. Resume only after diagnosing the recorded failure; all successful evidence is hash checked.
- Outputs: observations, calibration, environment, phase traces, `summary.json` and `summary.csv`. A >5% baseline-repeat drift stops acceptance for review. No automatic PDF or existing-report replacement.
- The initial closing baseline flagged two file-inclusive cases. `rechecks/file_02` repeats exactly those cases across all five images and a closing baseline, with the original 128 MiB frame allocation pinned. `file_01` used smaller FPGA buffers and is diagnostic only. Existing resident measurements and GPU profiles are retained.
- `analysis_tooling/finalize_benchmark.py` watches that recheck, verifies evidence hashes and its drift gate, then replaces only the predefined file comparisons. It writes `measurement_manifest.json`, records each row's cohort/evidence, and leaves OPT_1 installed. Inspect the main `status.json` for overall acceptance; a passed individual collector is insufficient.
- **Completed and accepted:** 30,000 primary measured calls, 6,000 baseline-repeat calls, 600 separate GPU profile calls. All drift gates passed after the predefined recheck; 207 evidence/output hashes verified. Completion ntfy delivered. See campaign `summary.csv` / `summary.json`; GPU FP32 and FPGA W8A8 precision is explicit. The maintained setup now pins the 128 MiB allocation and uses the validated HPF GPU transport adapter.

## Combined FIFO1024 + aggressive B2 — 2026-10-13

- Iteration: `../iterations/OPT_6_BRAM_FIFO1024_DSP_B2_RF72_RF288/iteration.json`.
- Run root: `../runs/combined_fifo1024_b2_20261013`; one selected build, four implementation threads.
- Native FIFO optimization with profiling capacity 1024 and two frames; conv3/4/5/6 reuse factors 72/72/288/288.
- A fresh profile is required for this combination: the standalone FIFO1024 profile used different reuse factors. Existing profiles and completed builds remain preserved.
- Complete local model/configuration; `derived_from` and `provenance` are descriptive only. Shared model weights remain hash-pinned.
- Same streaming preprocessor, FIFO32 interface, first-pixel guard and ABI v3 timestamps. No custom CNN kernels.
- Gates: 146 exact model logits, wrapped C simulation, startup/second-reset/consecutive-frame RTL checks, actual-build RTL checks, routed timing and sealed bitstream.
- Existing selected-build supervisor performs one timing-recovery attempt when needed. Independent ntfy monitor reports completion, failure and supervisor exit.
- Scope: build only. Board parity and benchmarks follow on the FPGA host.


## OPT board benchmarks — 2026-10-13

- Campaign: `../runs/opt_benchmarks_u55c02_20261013`; U55C-02, device 1, PCIe c4:00.0, CPU2/NUMA0.
- Eight OPT images, then repeat OPT_1_STREAMING. R_S is historical only. One exclusive board lease spans the entire sequence.
- `opt_benchmark.py`: snapshots verified images/software/inputs; programs with the standard driver; 520 exact parity calls in 3 sessions, pilot, then full timings. A failure stops progression for diagnosis.
- `opt_benchmark_collect.py`: 15 workloads, 20 warm-ups + 200 measured calls per workload **per scope** (6000 measured + 600 warm-up calls/image).
- Resident scope: prepared input invocation → host-observed verdict. File scope: file open/read → prepare/copy → invocation → host-observed verdict, every trial. Filesystem cache is warm; initial allocation/programming and diagnostic CSR readback are excluded.
- Both scopes send the full raw input on every call. Calibrated FPGA timestamps report reception, preprocessing, CNN interval, overlap, FIFO occupancy and stalls. Streaming intervals overlap; never sum them.
- `campaign_configure_fifo` explicitly selects 32 or 65536 pixels; default ABI behavior remains 32. Non-streaming admission requires peak=65536 and CNN-first after both last-preprocessed-pixel and raw completion. `campaign_now_ns` supplies the same host clock as the runtime.
- All OPTs retain ABI variant 7. Identity uses the explicit OPT ID plus hashes, never an alias to D_I.
- Standard-driver insertion supplies the second reset after FPGA configuration. No reset-suppressed diagnostic driver is used.
- `monitor` sends ntfy outcomes and unexpected-controller-exit alerts. `write_opt_benchmarks_report.py ROOT --watch` publishes the measured PDF; completed reports also replace the prior current-results PDF, preserving a build-only copy.
- Campaign-local `report_dependencies/` holds PDF packages; benchmark runtime dependencies are unchanged.
- Resume via `tooling/opt_benchmark.py run ROOT`; passed evidence is hash-checked, failed attempts are preserved, and new attempts are created. Resume only after diagnosing the failure; do not start two controllers.


## Selected configurable builds — 2026-10-12

- Active manifest: `../runs/selected_builds_20261012/campaign.json`.
- Original scope: **builds only**. The subsequent board campaign is documented above.
- **4 simultaneous implementations:** 3 primary slots + 1 reserved non-streaming slot, 4 threads each. Recovery uses the same permits. Preparation, HLS synthesis and RTL validation run independently.
- Existing FIFO 1024 and B2+72 workers keep their original shared implementation lock. While either is alive, primary slot 0 is reserved for them; new work uses slots 1–2. This preserves active exports without exceeding the cap.
- Native FIFO profiles are verified and reused. Depths 4096, 65536 and 262144 are **not selected** for routing; evidence is retained.
- R_S remains a historical reference. The benchmark-ready streaming baseline is **OPT_1_STREAMING**.

| Final iteration | Selection / change |
| --- | --- |
| `OPT_0_NONSTREAMING` | Separate queue; full 65536 × 16-bit synchronous frame buffer; wait for all raw input and preprocessed pixels |
| `OPT_1_STREAMING` | Matched streaming baseline; stock hls4ml CNN; ABI v3 timestamps |
| `OPT_2_DSP_RESOURCES_B2` | Already built; conv3/4/5/6 RF = 36/36/144/144 |
| `OPT_3_BRAM_FIFO_A` | Already built; native FIFO profile capacity 100000 |
| `OPT_FIFO_A_P1024` | Continue existing build and verified profile |
| `OPT_FIFO_A_P16384` | Build from verified profile |
| `OPT_4_DSP_B2_CONV34_RF72` | Continue existing build; RF = 72/72/144/144 |
| `OPT_5_DSP_B2_RF72_RF288` | Aggressive B2; RF = 72/72/288/288; no FIFO optimization |

- Model architecture, weights, quantizers, precision and threshold stay pinned. New configs are complete; `derived_from` is provenance only. No D_I conv0 specialization.
- `interface.pipeline_mode` defaults to `streaming`; `nonstreaming` requires `external_fifo_depth: 65536`. CNN internal dataflow remains enabled. No overlapping frames.
- CSR layout is unchanged. Peak occupancy accepts 17 bits for the full-frame buffer. First-pixel launch guard is preserved.
- New attempts log raw/preprocessing/CNN/score/verdict timestamps in RTL `cycles.csv`; host file reading requires later host-side benchmarking.
- Non-streaming gates: buffer reset during fill/drain, backpressure, raw-tail gating, consecutive frames, BRAM inference, 11-frame exact wrapped RTL parity, actual-build RTL parity, final timing, sealed artifacts.
- Standalone buffer check inferred **30 RAMB36 tiles**; this is not a routed whole-design resource claim.
- Separate supervisors and ntfy monitors: `primary.json`, `nonstreaming.json`, `jobs/*.json`, `*_monitor.json`. Topic: `coyote-build-sdeheredia`. Controller failures and terminal outcomes are reported; no periodic status notifications.
- Report: `../reports/optimizations/streaming_optimization_results_20261012.pdf`; watcher refreshes after **each queue** terminates. Primary reporting never waits for non-streaming.

Resume a controller using its sealed campaign snapshot; living workers are adopted:

```bash
python3 hls4ml/optimize/runs/selected_builds_20261012/controller/selected_builds.py run hls4ml/optimize/runs/selected_builds_20261012 --lane primary
python3 hls4ml/optimize/runs/selected_builds_20261012/controller/selected_builds.py monitor hls4ml/optimize/runs/selected_builds_20261012 --lane primary
```

Use `--lane nonstreaming` for the independent baseline queue. Launch long-running controllers and monitors in tmux. Completed artifacts are verified before reuse. A disappeared worker with partial output requires inspection; the controller never blindly reruns it. `iteration_worker.py JOB implement` resumes only after sealed actual-build RTL and source verification, with the campaign permit environment set.


## Configurable model iterations — original October 10 campaign

- Entry point: `iterations.py`; configs: [`../iterations/`](../iterations/).
- Freeze architecture, quantizers, weights, preprocessing semantics and zero threshold.
- Regenerate firmware with hls4ml 1.3.0 for every iteration; no custom conv0 kernel.
- Each config is complete. `derived_from` is descriptive; no previous iteration is read.
- R_S preprocessing + standard CNN; D_I ABI v3/variant 7, timestamps, first-pixel guard, FIFO32.
- Shared integration tooling is snapshotted into each attempt. Weights remain shared and hash-pinned.

| Iteration | Change | Current scope |
| --- | --- | --- |
| `OPT_1_STREAMING` | Standard streaming baseline | Generation, C simulation, HLS and RTL |
| `OPT_2_DSP_RESOURCES_B2` | conv5/conv6 Resource RF144 | Independent routed build |
| `OPT_3_BRAM_FIFO_A` | Native Vitis FIFO optimization | Independent routed build |

- A uses profiling depth 100000 and two prepared frames; native selected depths are preserved.
- Correctness: 146 production logits, 11 synthetic boundary cases, startup idle/second reset,
  consecutive frames, stalls/backpressure, counts, CSR verdict and timestamp ordering.
- Functional validity has **no latency/resource/overlap threshold**. Timing closure is separate.
- Baseline must pass before candidate launch. Two candidate workers; one shared implementation lock;
  four implementation threads. A candidate failure does not cancel its sibling.
- Completion monitor sends outcomes to `coyote-build-sdeheredia`; notification failures are recorded.
- No board programming or benchmarks. A+B3 remains deferred.

```bash
python3 hls4ml/optimize/build_campaign/iterations.py campaign \
  --root hls4ml/optimize/runs/configurable_streaming_20261010
python3 hls4ml/optimize/build_campaign/iterations.py status \
  --root hls4ml/optimize/runs/configurable_streaming_20261010
```

Single-iteration commands: `prepare`, `validate`, `build` with `--root` and `--id`.
Each creates `ID/attempt_NN/`, including config/tool snapshots, resolved hls4ml config,
model/generator identities, source manifest, validation evidence, stage logs and `status.json`.
`resume --attempt PATH --stage validate|build --root ROOT` verifies completed preparation/
validation evidence. Failed partial attempts are preserved and restarted in a fresh directory.
Do not run two campaign supervisors against the same root. Run background commands in tmux
with the campaign monitor; standalone commands are intended for supervised diagnostics.

Resource analysis and plots: [`../reports/optimizations/D_I_resource_analysis_and_optimization_proposals.pdf`](../reports/optimizations/D_I_resource_analysis_and_optimization_proposals.pdf).
D_I figures remain historical measurements; they are not measurements of these new iterations.

Recovery additions (11 October):

- `iteration_recover.py JOB --output JOB/recovery/route_NN`: same-source timing recovery;
  validates the known shell/static boundary path before applying placement guidance.
  Model, firmware and clock constraints stay unchanged; full implementation shares the campaign lock.
- A profiling: native Vitis pass/parser retained. `iteration_cosim.py` removes graphical tracing
  from the generated simulator launcher and adds bounded Tcl runs with progress output.
  No installed hls4ml files or CNN kernels are edited.
- `retry --id ID --root ROOT --profile-cache CACHE`: optional same-iteration profile recovery.
  Requires exact regenerated firmware, weights, inputs and predictions; copies sealed evidence
  into the new attempt. Native hls4ml still selects the final depths; full wrapped validation follows.
- FIFO generation has a six-hour tool watchdog; expiry stops its subprocess group and reports failure.
- Monitor a retry/recovery with `iteration_monitor.py ROOT --campaign-file RECORD.json --prefix NAME`.
  Monitors resolve relative process paths and wait for stable termination before exiting.

The sections below document the earlier D_I/R_S campaigns.

## Native FIFO sweep — 11 October

- Runner: `fifo_sweep.py`; active root: `../runs/native_fifo_sweep_20261011/`.
- **Builds only.** Board programming and benchmarks were removed at the user's request.
- Native Vitis depths: **1024, 4096, 16384, 65536, 100000, 262144**, two pinned prepared frames.
- Native occupancy/depth selection is unchanged. Saturated profiles are labeled capacity-constrained;
  their latency is CNN-only simulation, not production end-to-end latency.
- Current A supplies the verified 100000 profile/build. B2 remains an independent comparator.
  A fresh routed OPT_1_STREAMING control is also queued.
- Each new point snapshots a complete configuration, tooling, integration, and model identity.
  Equal generated firmware/tool/interface identities share one implementation result.
- Profile → exact parity → integrated RTL → automatic build of every valid distinct result.
  Profiles cannot directly invoke FPGA implementation. No performance admission threshold.
- At most two HLS/simulation workers including active A; one shared implementation lock with A/B2;
  four implementation threads. One failed point does not cancel its siblings.
- All build/validation evidence and failures remain under the sweep root. Optional same-source timing
  recovery is attempted once and only if the existing boundary-placement checks pass.
- ntfy monitor records minute-by-minute inspections during the first hour and continues monitoring
  termination afterward. Notification delivery is retried and deduplicated by point/stage/outcome.
- CSVs and plots: `../reports/optimizations/fifo_sweep/native_fifo_sweep_20261011/`.

```bash
python3 hls4ml/optimize/build_campaign/fifo_sweep.py status hls4ml/optimize/runs/native_fifo_sweep_20261011
# New roots only: init snapshots all configurations without starting tools.
python3 hls4ml/optimize/build_campaign/fifo_sweep.py init /path/to/new_sweep
python3 hls4ml/optimize/build_campaign/fifo_sweep.py run /path/to/new_sweep --until profile
# The default --until build additionally validates and implements distinct passing points.
python3 hls4ml/optimize/build_campaign/fifo_sweep.py run /path/to/new_sweep --until build
python3 hls4ml/optimize/build_campaign/fifo_sweep.py monitor /path/to/new_sweep
```

Attach the monitor in a separate background session whenever starting a background sweep. A running
root permits only one supervisor; failed points are preserved for diagnosis, not silently retried.
`iterations.py profile --root ROOT --id ID` also supports native profiling without packaging/building.

## Streaming reset recovery

- Driver insertion resets the application after FPGA configuration.
- Early CNN padding advances static position/stride counters; control reset retains them.
- Second-reset RTL reproduces board logits: **D_I `3f97e000`; R_S `3f944000`**; expected `bf2f4000`.
- `hardware/common/frame_start.hpp`: wait for first pixel before CNN launch; preserve input/output ABI.
- `check_frame_start.py`: fresh C-sim/HLS/RTL; **8 R_S / 11 D_I frames**, second reset after **20,000 idle cycles**.
- `launch_isolation.py --variants D_I R_S --conv0-gate ... --frame-start-gates ...`: fresh replacement attempts; **5-slot** queue, shared implementation memory permit.
- Corrected builds require standard-driver board parity; diagnostic reset suppression never admits benchmarks.
- `direct_board_validation.py`: exact rebuilt D_I + standard driver → **520 checks** → explicit D_I/D_N hardware selection.
- `benchmark_handoff.py`: wait for that admission → smoke/pilot/full D_I then D_N; board operations share an exclusive lock.

## Production streaming candidate

- **R_SO_T:** R_S single-IP wrapper + first-pixel guard + R_O optimized conv0 + passive five-event observer.
- Original production host implementation, raw framing and result DMA; read-only CSR extension only.
- `production_candidate.py`: verify separate R_O/R_S **260/260 standard-driver board gates** and maintained source identities before preparation.
- `hardware/production/vfpga_timed.svh`: unchanged DMA connections; monitor outputs drive only CSR responses.
- `package_campaign.tcl`: add FIFO event ports after fresh HLS export, before Coyote imports the IP.
- Combined RTL gate: **8 frames**, second reset, exact pixels/logits, stalls, consecutive frames and five timestamp events; reject any change to existing exported HLS logic.
- `candidate_handoff.py`: wait for board prerequisites; launch one instrumented build; share the replacement campaign's implementation memory permit.
- `launch_isolation.py --variants R_SO_T --production-prerequisites SPEC.json --implementation-lock LOCK ...`.
- `SPEC.json`: `board` path; `R_O` and `R_S` each contain explicit `job` and `evidence` paths.
- [Live gated handoff](../runs/frame_start_recovery_20261009_0134/R_SO_T_handoff/status.json); no candidate hardware launch before prerequisite board parity.
- `isolation_board.py ... R_SO_T ... --wait`: verify final build → **260 persistent production-DMA predictions and passive captures**; standard driver only.
- `isolation_evidence.py`: replay all **260** saved captures; compare frame IDs, register decoding and production result rows.
- `production_collect.py`: one persistent production context per sweep; **20 warm-ups + 200 measured/case**, read-only timestamps after result DMA; hardware/runtime/input/software identity sidecars.
- `production_benchmark_queue.py`: require R_SO_T admission; prioritize D_I when ready, otherwise allow the candidate independently; smoke/pilot/full; exclusive board lease; restore verified D_N; outcome-only ntfy monitor.
- [Candidate benchmark handoff](../runs/board_benchmark_20261008_130137/R_SO_T/handoff.json); no candidate measurements admitted yet.

## Recovery campaigns

- **Active correctness recovery:** [first-pixel validation / automatic launch](../runs/frame_start_recovery_20261009_0134/launch_status.json).
- Original [production isolation queue](../runs/production_isolation_20261008_132304/status.json): builds complete; R_O board pass, R_S standard-driver board failure preserved.
- R_O: frozen sequential production wrapper + optimized conv0. R_S: monolithic streaming wrapper + original conv0.
- R_S helper: preprocessing DATAFLOW → 32-token FIFO → sequential CNN + production float publication; preserve nested CNN call control.
- R_S initial outer-DATAFLOW form stalled its first frame in RTL; preserve attempt 2. Replacement uses fresh sources/IP/checkpoints.
- Both retain production raw header/exact transfer length, unchanged host source, LOCAL_TRANSFER and result DMA.
- Launch: `launch_isolation.py --cases CASES.tsv --boundary-reference direct_expected.txt`.
- Maintained wrappers: `hardware/variants/production_optimized.cpp`, `production_streaming.cpp`; top: `hardware/production/vfpga_top.svh`.
- Gates: 52 corpus C-simulation calls + 8 independent boundary references; eight HLS RTL frames; final routed timing/hashes.
- Production output: LAST=0, KEEP unspecified; destination DMA length=4 bytes. Preserve this ABI.
- After build success: `prepare_production_runtime.py JOB_DIR VERIFIED_BITSTREAM`; returns the project layout for unchanged `RawCoyoteOverlay.predict_raw` / `production_control.py`.
- Two workers, four threads each; whole-device implementation stages share a memory permit on the 62-GiB host.
- No new board measurements accepted until parity passes. Original D_I campaign below remains preserved.

- Plan: [OPTIMIZATION_PLAN.md](../OPTIMIZATION_PLAN.md).
- `resource_attribution.py JOB`: routed wrapper, preprocessing/CNN, FIFO, control/monitor, ILA and residual costs; device capacities and discrete ≤10% limits; reject synthesis reports and overlapping hierarchy totals.
- Full benchmark analysis writes `full.resources.json`, bound to the exact measured image/source; HLS estimates remain separate.
- `host_environment.py`: read-only before/after-case snapshots in `*.environment.jsonl`; affinity/governor/frequency, CPU counters/load, memory/hugepages, kernel and PCIe link; no work inside timed calls.
- Current run: [status.json](../runs/direct_stream_20261008_002352/status.json).
- Three isolated builds; maximum five concurrent workers; no board programming.
- **2026-10-08:** all three builds passed; source/artifact hashes verified; ntfy success alerts delivered.
- D_I final outputs: `jobs/D_I/recovery/route_01/`; original failed routing is preserved.
- Routed D_I: WNS **+0.035 ns**, WHS **+0.009 ns**; clocks unchanged.
- Build evidence: each job’s `artifact_manifest.json`; board/GPU execution remains unvalidated.

| Job / ABI ID | Hardware | Priority |
| --- | --- | --- |
| D_I / 7 | Direct-host preprocessing + conv0-optimized CNN | First |
| D_N / 8 | Direct-host transport sink | Parallel |
| D_G / 9 | Byte-preserving FPGA→GPU bridge + P2P result capture | Parallel |

## Implementation

- `hardware/direct/`: shared AXI-Lite control, elastic FIFO, top, variant constants.
- `hardware/variants/preprocess_wrapper.cpp`: raw bytes → 65,536 normalized pixels.
- `hardware/variants/cnn_wrapper.cpp`: pixel stream → production CNN → score.
- CNN wrapper: one model invocation per verdict; sequential call control, internal CNN DATAFLOW retained. Prevents premature next-frame launches.
- `hardware/common/conv0_dataflow.hpp`: copied 5×5 windows; depth-four FIFO; unchanged arithmetic.
- Preprocessing/CNN boundary: observable AXIS handshakes; 32-pixel elastic FIFO.
- Internal production CNN FIFO depths, weights, types, and other layers unchanged.
- Python isolates sources, selects variants, patches only the isolated conv0 call, and manages tools.
- `EN_MEM=0`, `EN_PR=0`, two host-stream destinations; target 250 MHz.
- S_I is retired from active preparation/launch. Previous campaign artifacts remain unchanged.

## Gates and attempts

- `check_conv0.py`: independent window/output parity and paired HLS synthesis.
- `conv0_gate.json`: verified helper hash, baseline/candidate synthesis evidence.
- Worker gates: host compile, control RTL, pristine-vs-candidate full-CNN C simulation.
- D_I implementation gate: actual HLS RTL, eleven boundary frames, parity, stalls, consecutive frames, cycle reduction.
- `check_direct_rtl.py JOB_DIR --reference-only`: overlap pristine reference synthesis with IP packaging; reuse only intact RTL/reports from that source attempt.
- `check_direct_rtl.py JOB_DIR --early`: detect functional failures during packaging, using separately synthesized preprocessing and the build's CNN RTL. Final gate still checks both actual build cores.
- Final gate reuses early results only when all actual RTL/data files, test inputs, source hashes, PASS logs and eleven paired cycle rows match. Changed or incomplete evidence triggers fresh simulation.
- Successful build: intact source manifest, final routed timing, nonempty bitstreams.
- New source changes require fresh attempts; old directories retained under `attempts/<ID>/`.
- Checkpoints/IP are not reused across source changes.
- Timing retries may reuse checkpoints within the identical source attempt.
- Build success does not imply board validation, end-to-end speedup, or a GPU win.

## Launch and monitoring

```bash
python3 hls4ml/optimize/build_campaign/launch.py --root RUN_ROOT --conv0-gate VALIDATED_GATE.json
tmux -L coyote-opt attach -t coyote_direct_direct_stream_20261008_002352
```

- Existing scheduler resume: `campaign.py run RUN_ROOT --jobs 5`.
- Pause dispatch: create `RUN_ROOT/dispatch_paused`; running workers continue.
- Retry terminated job: JSON list of IDs in `RUN_ROOT/retry_requests.json`.
- `direct_monitor.py`: process/heartbeat checks; silent inspection snapshots every **1,800 seconds**.
- ntfy topic: `coyote-build-sdeheredia`.
- Notifications: **actual hardware-build termination/success and required-input blockers only**.
- No periodic notifications or validation-job alerts; delivery/dedup state persists across monitor restarts.
- Local records: `status.json`, `progress.json`, `inspections.jsonl`, `notifications.jsonl`, source manifests, tool logs.
- Known timing failures: bounded automatic recovery; unknown source failures require agent diagnosis/fix, not unchanged retries.
- D_I recovery 1 may use verified boundary-register placement guidance: exact failing setup path, current source hash, and intact successful-sink evidence required. Uses D_I's own optimized checkpoint; clocks unchanged; guidance and hashes recorded in recovery provenance.
- No generated narrative report files.

## Register ABI v3

- Offsets below: 64-bit CSR word indices.
- Signature: `0x4342595400030000 | variant`.
- Timing: absolute 64-bit aclk ticks; zero/absent events distinguished by bitmap.

| CSR | Meaning |
| --- | --- |
| 0 | Write bit 0 to arm; read busy/done/error bits 0/1/2 |
| 1–2 | Raw byte count, trial ID; writable while idle |
| 4–7 | Signature, free-running tick, arm tick, event bitmap |
| 8–9 | First/last raw payload acceptance |
| 10–11 | First/last pixel produced |
| 12–13 | First/last CNN input accepted |
| 14–15 | Score accepted at controller, verdict captured |
| 16–17 | Payload read/write DMA acknowledgment |
| 18–19 | First/last forwarded beat, including header/padding |
| 20–21 | Input/output beat counts |
| 22–25 | Input starvation/backpressure, pixel backpressure, CNN starvation |
| 26 | Float32 logit bits [31:0], classification [32] |
| 27–29 | Produced/consumed pixel counts, peak pixel FIFO occupancy |

- Event bits 0–11 correspond to CSR 8–19.
- Classification: production `logit >= 0`; nonfinite results flag an error.
- Payload: 64-byte little-endian length header + raw bytes + zero alignment padding.
- GPU bridge preserves all frame bytes and transaction IDs; destination 0 carries payload.
- Destination 1 accepts a 64-byte GPU result: float32 score, `0x43565233`, uint64 trial ID, reserved zeros.
- Premature/stale/malformed GPU results flag an error.
- CSR 14 marks the externally observed HLS result, including float publication latency; it is not an internal CNN arithmetic timestamp.
- Wait for DMA completion and verdict before rearming. Timeouts require diagnosis/reset, not reuse of incomplete frames.

## Deferred host/GPU runner

- Host start: before per-trial arming/submission; complete host upload every trial.
- Separate setup: file loading, buffer registration, GPU allocations/model initialization.
- `direct_bench`: stores host timestamps, CSRs, and bracketed host/FPGA calibration samples.
- GPU stages use HIP events; external DMA completion is timed separately.
- `DIRECT_GPU=ON`: compile with ROCm, `HIP_PATH=/opt/rocm`, and explicit `gfx90a` target for MI210.
- `gpu_backend.hpp`: adapter ABI for the **original** baseline; no replacement model or dummy verdict.
- Adapter must establish completed external-DMA visibility, run GPU preprocessing/CNN, and publish the result before returning.
- GPU backend source/model and target host remain missing. Bridge bitstream does not imply GPU integration is validated.
- No automatic board execution or benchmarking.

## Checks

### Direct runtime recovery

- `runtime/`: maintained production-derived `CoyoteInference` adapter; D_I/D_N ABI v3; batch 1.
- `RawCoyoteOverlay.open_direct_session(library_path, backend, max_input_bytes, allocation="HPF")`.
- Session API: `prepare(raw)`, `run()`, `clock_sample()`, `close()`; context-manager cleanup.
- `direct_checker`: CSR logit/verdict; `direct_sink`: transport completion, no prediction.
- Preserve aligned 64-byte framing; use `LOCAL_READ`; production `predict_raw` unchanged.
- `runtime_benchmark.py`: persistent allocation; native timestamps; recorded warmups; existing CSV schema.
- `production_control.py`: frozen production library/image, identical inputs, 10 repetitions.
- `parity_gate.py`: per-input production tolerance; all verdicts must match; shared runner/analyzer policy.
- `benchmark_queue.py`: requires passing `runtime_validation.json` and hashed production tolerances before programming benchmark images.
- `run_diagnostic.py`: bounded tmux diagnostics, process-group cleanup, no ntfy alerts.
- Historical runtime-only recovery: `../runs/board_benchmark_20261008_130137/diagnostics/`; parity remained wrong. First-pixel hardware launch guard resolves it: U55C-02 **D_I 520/520**, **R_S 260/260**; D_I/D_N **5,280 benchmark calls passed** (`../runs/board_benchmark_u55c02_20261009_2345/`). Performance targets remain unmet above the two smallest tested sizes.

```bash
cmake -S hls4ml/optimize/build_campaign/runtime -B RUN_ROOT/software/runtime_build -DCOYOTE_SW=ABSOLUTE_COYOTE_SW_PATH -DCMAKE_BUILD_TYPE=Release
cmake --build RUN_ROOT/software/runtime_build -j 4
```

### Validation commands

```bash
python3 -m unittest discover -s hls4ml/optimize/build_campaign/tests -p 'test_*.py'
python3 hls4ml/optimize/build_campaign/tests/check_direct_top.py JOB_DIR GENERATED_LYNX_PKG
python3 hls4ml/optimize/build_campaign/tests/check_direct_top.py D_G_JOB_DIR GENERATED_LYNX_PKG --gpu-path --output VALIDATION_DIR
```

- Top elaboration uses actual Coyote interfaces and HLS port stubs; actual HLS behavior has a separate RTL gate.
- GPU path simulation: maintained forwarding/control RTL, actual Coyote interfaces, stalled output, varying TIDs, FIFO wrap, three consecutive frames, verdict return and timestamp events.
- Frozen production package and historical `runs/20261001_184524` remain reference-only.

### High-memory build-host continuation

- Runner: `resume_parallel.py`; D_I + R_S; **builds only**, no board handoffs.
- Active run: `../runs/parallel_resume_20261009_1550`; host `hacc-build-02`.
- Local SSD working trees: `config.json → local_root`; durable results: `jobs/`.
- Reuse verified HLS exports; preserve hardware source hashes; regenerate Vivado projects through a separate `build_config/` path adapter.
- Two workers; independent CPU groups; concurrent implementation. Synthesis starts with **2 processes/design × 4 threads**; subsequent processes raised to **8 threads** after measuring headroom.
- R_S synthesis overlaps its repeated RTL check; `synth_stage.lock` prevents duplicate synthesis. RTL must pass before implementation.
- `resume_progress.json`: live worker state; `progress.json`: completed result; sealed artifact manifest + bitstream hashes required for board admission.
- Worker tmux: `coyote_parallel_resume_20261009_1550`; monitor: `watch_parallel_resume_20261009_1550`; socket `coyote-opt`.
- Outcome-only ntfy; retries failed delivery; preserves notification state. No periodic notifications.
- Bounded timing recovery; optional host-bound `parallel_implementation.json` permits two recovery jobs with **≥64 GiB** available RAM.
- Original low-memory queue stays historical; the continuation uses independent workers and its own monitor.

### Board host replay

- Fresh board root; preserve prior host results and installed-image records.
- `board_target.json`: explicit `hostname`; verified by direct admission, isolation parity and benchmark workers. Legacy runs default to `hacc-u55c-03.inf.ethz.ch`.
- Current adapter: device **1**, PCIe **c4:00.0 Gen3 ×16**, CPU **2**, NUMA **0**. Verify these before selecting a different host.
- Reuse hash-verified input/reference files and compatible native libraries; rerun board admission with the standard driver before benchmarking.

### Production host comparison and report

- `production_host_queue.py run BOARD OUTPUT`: R_O → R_S, fresh board/persistent parity → smoke/pilot/full, restore D_N. Run companion `monitor` in tmux for benchmark outcome notifications.
- `--original`: frozen May 24 res256 image + production runtime built against current Coyote; image/runtime hashes checked.
- `production_host_benchmark.py`: one persistent context; **20 + 200 calls/size**; exact logits; host flush/submission/predict-return/result-observation timestamps. No internal FPGA timing claim.
- `report_board_comparison.py BOARD OUTPUT`: archive five-variant evidence; calibrated D_I event tables; PNG/PDF figures.
- `write_board_report.py OUTPUT`: Markdown report and tables from saved report inputs.
- Current report: `../reports/u55c02_20261009/REPORT.md`; raw runs remain preserved.

## FP32 GPU host/P2P builds — 2026-10-18

- New iterations: `OPT_7_GPU_HOST` and `OPT_8_GPU_P2P`; GPU ABI v4, preserved timestamp offsets, original FP32 Keras model.
- P2P verdict polling is FPGA initiated. No host submission per poll; one outstanding read, 1 µs configured gap, bounded timeout and drain-before-rearm.
- Campaign `../runs/gpu_fp32_20261018`; both builds run concurrently with independent ntfy monitors. Preflight verified P2P on GPU0/U55C device1, fine-grained DMA-BUF publication and 520 FP32 software admission calls.
- [Runtime, ABI, evidence and handoff](gpu/README.md). New-image board admission and benchmarks follow build completion.
