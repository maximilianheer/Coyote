# Direct-host build campaign

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
