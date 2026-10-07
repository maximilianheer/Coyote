# Optimization build campaign

Five concurrent jobs, isolated Coyote source/build trees, one tmux window per job.
The scheduler fills free slots in this order:

| Jobs | Purpose | Dependency |
| --- | --- | --- |
| S_I, I | Streaming and sequential instrumented checkers | None; first priorities |
| H16, H8, H4, H2, H1 | Hello-world with 16, 8, 4, 2, 1 clock regions | None |
| HN, HR | Narrower / relocated smallest feasible region | All five coarse attempts finish |
| HE | Disable routing-containment expansion | Coarse attempts, HN and HR finish |
| U, N, P, C | Uninstrumented checker, transport sink, preprocessing, inference | None; fill otherwise idle slots |

Refinements require a successful anchor. Failed jobs are reported and do not stop
independent builds. A run with `recovery_policy.json` containing `{"enabled": true}`
automatically diagnoses failures and applies the bounded recovery steps below.
Vivado uses eight threads; newly prepared projects serialize IP synthesis runs.

## Maintained hardware

- `hardware/variants/{instrumented,uninstrumented,transport_only,preprocessing_only,inference_only,streaming_instrumented}.cpp`
  are the six explicit HLS tops. Preparation selects one and copies it unchanged
  as `model_wrapper.cpp`; common headers provide preprocessing, CNN, adapters and
  diagnostic helpers. The production firmware and weights are copied unchanged.
- `hardware/benchmark_control.sv` maintains the register ABI and counters.
  `hardware/vfpga_top.svh` uses ordinary SystemVerilog constants from the selected
  variant's `.svh` file, with generate branches for the optional phase port.
- `hardware/debug_probe.svh` and `hardware/init_ip.tcl` supply the same one-bit,
  1024-sample ILA in all designs. This keeps Coyote's mandatory user debug bridge
  connected and addresses the observed `Chipscope 16-320` checkpoint-reopen error.
  It observes accepted input beats and does not drive the datapath or control ABI.
  Include its resources in design totals and attribute them as shared debug overhead.
  Hello-world uses `hardware/hello_world/vfpga_top.svh` over the isolated dataset copy.
  Its maintained `hello_world/hdl/perf_local.sv` restores normal TVALID propagation
  while retaining the original add-one datapath and register stages. The frozen
  nodbg source's RO-driven TVALID is omitted from new H builds, as approved.
- Python handles isolation, file selection, floorplans, tool configuration,
  validation, scheduling and notifications. It does not construct C++ or SV logic.
- `source_manifest.json` records SHA-256 hashes for each attempt's inputs, the
  maintained hardware and build scripts. Diagnostic workers verify these inputs
  before synthesis. Validated sources may not be edited in place.

## Current campaign

- Run: `hls4ml/optimize/runs/20261001_184524`
- Live overview: [STATUS.md](../runs/20261001_184524/STATUS.md)
- Attach: `tmux -L coyote-opt attach -t coyote_opt_20261001_184524`
- Logs: `jobs/<ID>/{worker,project,synth,link,shell,app,bitgen}.log`
- Artifacts: `jobs/<ID>/build/{bitstreams,reports,checkpoints}`
- Timing recovery artifacts: `jobs/<ID>/recovery/route_<N>/`; the original
  checkpoint, sources, logs and bitstreams remain untouched.
- Timing retries use four distinct strategies: post-route optimization, rerouting
  from placement, new placement, then incremental timing closure using the best
  completed checkpoint from the same source attempt. The last strategy preserves
  the current netlist, clocks and DFX floorplan; reference hashes and reuse are
  recorded. See [AMD's incremental DFX guidance](https://docs.amd.com/r/2024.1-English/ug909-vivado-partial-reconfiguration/Incremental-Compile).
- H1/HN/HR can reuse H2's identical common shell/app checkpoints after checking
  source, script, shell HDL, block-design, constraint, static-checkpoint and
  configuration hashes. `shell_reuse.json` records provenance. Each new floorplan
  still runs subdivision, linking, placement, routing, final timing and bitgen.
  HE and all diagnostics are excluded from this hello-world reuse path.
- Narrowing uses ordinary Tcl after `link_design`, before saving the linked
  checkpoint. XDC files contain only supported constraint commands. The Tcl
  trims edges only while all original BRAM sites (and DSP/URAM sites when those
  primitive types are used) remain available after snapping. It checks that
  effective slice sites decrease and required resource sites are retained;
  workers require its success marker. `floorplan_implementation.json` hashes the
  refinement source and generated implementation script.
- Each diagnostic also builds `jobs/<ID>/host_build/opt_bench` and runs C simulation.
- `monitor` sends hourly summaries, failure/blockage alerts, per-job completion,
  scheduler-heartbeat alerts and final status to `https://ntfy.sh/coyote-build-sdeheredia`.
  Delivery responses are saved in `notifications.jsonl`; failed deliveries retry.
- The monitor exits after the final summary is delivered. tmux survives terminal
  disconnection, but does not survive a host reboot.

To start a new campaign from the repository root:

```bash
python3 hls4ml/optimize/build_campaign/launch.py
```

If only the scheduler stops, restart it in a tmux window using
`python3 -u hls4ml/optimize/build_campaign/campaign.py run <RUN_ROOT> --jobs 5`.
Its lock prevents duplicate schedulers; live workers are adopted. If a worker
fails, inspect its log and fix the cause before writing a JSON list of job IDs
to `<RUN_ROOT>/retry_requests.json`. Retries archive the entire previous job under
`attempts/<ID>/attempt_<N>` and prepare fresh sources/build directories.

Create `<RUN_ROOT>/dispatch_paused` to stop dispatch; wait until `STATUS.md` reports
`paused`. Running workers and hourly monitoring continue. Remove the file to
resume dispatch. Restart the scheduler after changing its Python inputs; it adopts
live workers and respects the pause file. Replacing a running implementation also
requires stopping its full process tree and preserving its attempt before preparing
the replacement; simply changing its queue status is insufficient.

While paused, run `python3 build_campaign/validate_campaign.py <RUN_ROOT>` from
`hls4ml/optimize/` to validate all five prepared diagnostics. Run it in tmux; results
are recorded in `refactor_validation.json` and each job's `validation.json`.
It sends an ntfy success/failure notice and leaves dispatch paused for inspection.
Workers also enforce validation before synthesis when no matching validation record
exists. Host compilation, C simulation and XSim use the same isolated attempt.

## Measurement contract

All five diagnostic designs use the same card-memory request path and CSR result
endpoint. Raw inputs have a 64-byte length header and 64-byte payload alignment.
Inference-only consumes exactly 65,536 preprocessed float32 values. The host
offloads data once, then issues 20 recorded warmups and 200 measured requests.

The primary hardware interval is **accepted FPGA read request → captured result**;
host offload and the wait to accept the request are excluded. CSV also records
host start/poll time, read completion, first/last beat, phase cycles, input stalls
and result bits. Phase counters measure whole preprocessing/CNN calls, not
individual layers. HLS and hierarchical routed reports provide resource detail.
Use the implemented clock to convert cycles into time. This is a resident-input
benchmark; end-to-end host transport needs the existing host reference path.

Preprocessing tests cover sampling boundaries and partial beats; diagnostic
outputs are checked against the pristine production CNN or independent checksum.
The AXI-Lite simulation tests all five variant IDs, instrumentation enabled/disabled,
split address/data writes, backpressure, DMA request acceptance, counters, result
capture and repeat trials. Run queue/isolation tests with
`python3 -m unittest discover -s hls4ml/optimize/build_campaign/tests -p 'test_*.py'`
from the repository root. Optional `tests/check_top.py <RUN_ROOT> <lynx_pkg.sv>`
elaborates the maintained top against actual Coyote interfaces and an HLS port stub;
this checks wiring, not synthesized CNN behavior.

The refactor preserves the software-visible contract and is checked by C simulation
and control RTL tests. **Synthesis equivalence, resource usage and timing must be
assessed using the replacement synthesis and routed reports.**

Build success requires bitstreams and timing reports. **PR compatibility, board
loopback, actual DFX footprints and benchmark execution remain hardware follow-up**;
the scheduler never programs the board or marks a result hardware-validated.

The timing validator accepts Vivado 2024.2's exact success sentence, "All user
specified timing constraints are met." It rejects failed, contradictory or missing
timing evidence. The debug fix still requires routed-checkpoint reopening and
bitstream generation to confirm resolution on each full design.

## Automatic recovery

The current queue includes S_I and I first, with a single five-worker limit.
Existing U/C workers are adopted. Every recovery transition is recorded in
`recovery_events.jsonl` and delivered by the hourly ntfy monitor.

- PR jobs use `reports/config_0/shell_timing_summary_c0.rpt`; diagnostics use
  `reports/shell_timing_summary.rpt`. Intermediate reports remain available.
  Final timing is checked before bitgen. Old false failures can be recovered
  without rebuilding only after checking source hashes and bitgen completion.
- Diagnostic timing failures try three distinct strategies: post-route fanout
  optimization/NoTimingRelaxation; post-placement fanout optimization/
  MoreGlobalIterations; then fresh Explore placement/AlternateReplication/
  NoTimingRelaxation. All preserve clocks and hardware. Each attempt hashes its
  seed checkpoint and Tcl, checks final timing, and reopens its own checkpoint
  for bitgen. These strategies follow the AMD
  [physical optimization](https://docs.amd.com/r/2024.1-English/ug835-vivado-tcl-commands/phys_opt_design)
  and [routing directive](https://docs.amd.com/r/2024.1-English/ug904-vivado-implementation/Using-Directives)
  references; closure is determined by the generated reports.
- BRAM capacity failures receive at most two enlarged-floorplan attempts, with
  previous directories archived. HN avoids a known BRAM-insufficient rectangle
  and can narrow logic columns while retaining the feasible BRAM columns.
- Exhausted or unknown failures trigger `needs_new_fix` alerts, retain all
  evidence, and do not rerun unchanged inputs. This is a deterministic recovery
  service, not an unattended agent that can invent arbitrary RTL fixes.

S_I now uses the consumed frame token as a control dependency for the CNN call.
Its real-IP RTL simulation must show exactly one stage event per frame and no
events before header acceptance, as well as all previous parity/overlap checks.
The previous failed S_I attempt remains in `runs/20261002_streaming_instrumented`;
the replacement is in the shared queue's `jobs/S_I`.

## Streaming instrumented variant (S_I, ID 6)

Launch only the new variant in its own run with
`python3 hls4ml/optimize/build_campaign/launch.py --streaming-only`.
This preserves the original queue and any current workers. S_I selects maintained
`streaming_instrumented.cpp/.svh` and `streaming_api.hpp`, using outer DATAFLOW,
independent stage event toggles, and target-index cached-beat preprocessing.
Production firmware, weights, normalization, and existing FIFO depths are unchanged.
See [the current plan](../OPTIMIZATION_PLAN.md) for ABI v2 words 20–27 and interpretation.
The controller captures read acknowledgement and result independently for all IDs;
new host code waits for `done && !busy`, and appends fields while retaining old columns.

The S_I worker gates implementation on synthesized-HLS RTL tests using the actual
pixel FIFO read handshake, saves `streaming_rtl/streaming.wdb`, and requires all
boundary-frame logits to match pristine C simulation. `streaming_control_tb.sv`
checks exact timestamps, concurrent stages, stalls, empty payloads and all ack orders.
`check_streaming_rtl.py <JOB_DIR> --output early_streaming_rtl --notify-root <RUN_ROOT>`
can run that same check as soon as `csynth_design` completes, while IP packaging
continues. It hashes an isolated RTL/test snapshot and verifies the source RTL
is unchanged at completion. The worker's implementation gate remains mandatory.
The unchanged real ILA remains required; the top elaboration stub is never built
into hardware. Bitgen must reopen the real routed checkpoint and generate bitstreams.

Prepare inputs without executing any board work:

```bash
python3 hls4ml/optimize/build_campaign/benchmark.py prepare INPUT_DIR --executable /absolute/path/to/opt_bench
```

This writes eight inputs, hashes, and a deferred `run_later.sh` (20+200 calls/size).
After a separately authorized board session, summarize with the verified clock:

```bash
python3 hls4ml/optimize/build_campaign/benchmark.py summarize OUTPUT_DIR INPUT_DIR/trials_*.csv --clock-mhz 250 --manifest INPUT_DIR/inputs.json
```

Use `--reference` for matching existing I/N CSVs and `--reference-provenance`
for a JSON object keyed by variant ID (`"1"`, `"3"`). Each entry must contain
`input_sha256` (byte-size strings to hashes), `clock_mhz`, and `same_ila` (boolean
from comparing build-manifest ILA hashes). The analyzer rejects mismatched inputs,
clocks, or incomplete grids. No board results exist for S_I yet.
