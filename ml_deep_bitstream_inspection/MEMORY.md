# Optimization project memory

## Networking priority — latest user instruction, 2026-11-08

- **2026-11-09 06:38 CET:** Networking-first phase completed with four
  accepted images (OPT12,OPT13,NET_DIAG_HBM,stock RDMA control). Native250/450
  application-HBM control remains unresolved: original WNS-0.104ns; targeted
  physical retry-0.277ns, all in HBM adapter. Preserve this negative evidence;
  no repeated directive retries. `network_phase_summary.json` discloses it.
- Deferred reader repairs now resumed as isolated attempt_04 for OPT14/15,
  maintained runner `hbm/readers_repair.py`, snapshot launched as
  `tooling/readers_recovery_worker.py` for existing monitor compatibility.
  OPT14 reuses original routed DCP for one physical repair; no source changes.
  OPT15 only changes reader_window.sv: bounded active-data/CQ differences and
  peak comparison remove64-bit critical arithmetic, retain64-bit telemetry.
  New differential gate compares every handshake/data/telemetry output to
  original RTL over300 descriptors and4/32/128 tracking settings, wraparound,
  independent data/CQ timing and backpressure. Full original parity/control/
  wiring gates and final verify.py retained. No clocks/model/RFs/FIFOs changed.
  Sources/checkpoints copied independently; preserved original HLS exports and
  completed components. OPT15 resynthesizes user only, then links/routes; OPT14
  starts from routed DCP. Tooling, identities, model pins and old evidence kept.
  `reader14_repair04` / `reader15_repair04` tmux. Native250/450MHz acceptance,
  four tool threads,24h stage watchdog, shared6 permits, ntfy monitors retained.
- Native application-HBM reference repair attempt_02 stopped before routing:
  selected launching counter FFs have low fanout, not the late512-load driver.
  Full timing path shows that driver is a downstream read-data gating LUT.
  Attempt_03 uses corrected strategy6 to select high-fanout read-data gating
  nets driven by FD/LUT cells, from same original placed DCP at250/450MHz.
  Both snapshots and prior failure preserved; tool-only selector correction,
  not another routed HDL failure. `read_control_probe/` holds read-only evidence.
- **2026-11-09 04:40 CET:** Application-HBM reference attempt_01 failed
  WNS-0.104ns only in HBM450 read width-converter control; application250 setup
  passes, hold+0.001ns. Stock reference already closes at native clocks.
  Queued/launched one unchanged-clock physical repair as NET_REF_RDMA_HBM
  attempt_02, strategy6: explicitly replicate high-fanout first/current-word
  read control FFs before routing, from own placed checkpoint. No RTL/clock
  changes or timing exceptions. Tool snapshot:
  queued_recovery_tooling/hbm_reference_read_control/. Keep monitoring; reader
  repairs still deferred while this networking repair runs. Generic strategy6
  requires measured target nets to exist; clock/timing gates remain mandatory.
- **2026-11-09 03:26 CET:** NET_REF_RDMA_STOCK attempt_02 PASSED bitgen and
  build acceptance at native application/user/network250 and HBM450MHz.
  WNS+0.027ns, hold+0.009ns. All artifact/source hashes independently verified;
  image SHA256 58d982f46bf9386c76108ac6a7da64810e2b0dc75c07cc56c23e0e49b0f8e325.
  Official Example09 application logic retained, native8/16 capacities, no
  application HBM; retransmission HBM retained. This establishes build closure,
  not board-level throughput/functional validation. Only NET_REF_RDMA_HBM
  implementation remains in networking queue; failed reader repairs still defer.
- **2026-11-09 03:08 CET: BOTH PRODUCTION NETWORK VARIANTS ACCEPTED.**
  OPT12_NET_STREAMING attempt_07 completed bitgen/acceptance, all artifact and
  source hashes independently reverified. WNS+0.032ns/hold+0.009ns; accepted
  image SHA256 1dcce96f9a5e02d06b51943718cc16b0cb24094003c94e5e953a5e1dbe042181.
  Source is exact attempt_05 routed design; model/RFs/FIFOs/first-pixel guard
  preserved. Actual application/user200MHz, network250MHz, HBM350MHz: benchmark
  ticks at200MHz and label fallback clocks. verification.json has resources.
  OPT13 attempt_09 is also accepted; no board validation/benchmarks on build host.
  Stock native-clock reference bitgen and application-HBM reference routing
  continue; failed original-clock OPT12 attempts and reader repairs preserved.
- **2026-11-09 02:59 CET:** STOCK RDMA reference met native250/450 routed
  timing (WNS+0.027ns, hold+0.009ns). Its user-clock audit had an overly specific
  ARP hierarchy line337; stock EN_MEM=0 generates that slice at line193. Audit
  now derives the hierarchy line from generated dynamic_top.sv and follows
  explicit recovery ancestry, hashes the source, and still checks actual
  physical clock pins/period. Resolver checks passed for stock193 and prior
  application-HBM337 configurations. Stock attempt_02 continues clock audit
  and bitgen from attempt_01's timing-valid checkpoint, without rebuilding.
- **2026-11-09 02:35 CET:** OPT12 fallback attempt_05 met routed timing:
  WNS+0.032ns/hold+0.009ns at application/user200, NCLK250, HBM350. Its old
  clock-name check failed after timing passed. Fresh attempt_07 now continues
  physical clock audit/bitgen from the exact routed DCP. No repeated synthesis,
  routing or FIFO profiling. OPT13 and diagnostic already accepted; original
  250/450 OPT12 attempts03/06 remain failed evidence, not accepted images.
- **2026-11-09 02:04 CET:** NET_DIAG_HBM attempt_09 PASSED acceptance and
  bitgen. All artifacts and source hashes independently reverified; image hash
  dd615fa1e79c9456b3630b3660870bd9329b0cb1d7e73096334c3f705f637515.
  WNS+0.017ns, hold+0.009ns; application/user200, network250, HBM350.
  Diagnostic only; board validation pending. OPT13 and diagnostic now accepted;
  OPT12 fallback and both native-clock reference controls continue. Reader
  repairs remain deferred under the network-first policy.
- **2026-11-09 01:32 CET:** NET_DIAG_HBM attempt_08 met routed timing:
  WNS+0.017ns/hold+0.009ns at matched200MHz application/user and350MHz HBM.
  Old name-only clock checker rejected the merged clock, as for OPT13. Fresh
  attempt_09 is queued/started for clock audit and bitgen from its exact DCP.
  Generic maintained `deployment_finish_prepare.py` gates such continuations
  on already-passed routed timing and source hashes, preserving previous jobs.
- **2026-11-09 01:11 CET:** OPT12 original-clock physical retry attempt_06
  failed WNS-0.129ns in CMAC powergood control and-0.025ns in HBM450 write
  adapter. Application250 still meets setup. Physical retry did not resolve
  the original limits; no indefinite repeated directives. Keep attempt_05
  matched-clock fallback and stock/HBM reference controls running; use their
  results to select further structural/platform changes. Reports/journal kept.
- **2026-11-09 00:40 CET: FIRST ACCEPTED NETWORK VARIANT.** OPT_13
  NET_GPU_P2P_R06 attempt_09 completed bitgen and acceptance. Routed WNS+0.031ns,
  hold+0.009ns, actual ACLK/UCLK200, NCLK250, HBM350. Exact attempt_08 routed
  DCP reused; no synthesis/routing repeated. All artifacts and sealed source
  hashes independently verified; accepted image/clock evidence in attempt_09
  verification.json and acceptance_evidence_hashes.json. GPU runtimeR06 unchanged.
  This is the fallback-clock image: benchmark ticks at200MHz and label it.
  Board validation remains pending. Five other networking jobs continue;
  OPT14/15 repairs stay deferred until networking work is resolved.
- **2026-11-09 00:07 CET:** OPT_13 attempt_08 ROUTED TIMING PASSED:
  WNS+0.031ns, WHS+0.009ns. Its older name-only user-clock checker then rejected
  the merged clock name. This is an acceptance-script failure, not routed timing
  failure. Prepared attempt_09 as priority0 acceptance/bitgen continuation using
  the exact routed DCP and source snapshots. Corrected helper verifies actual
  ARP user-domain register clocks. `deployment_finish.py` performs no synthesis
  or routing; it checks final timing/clocks/source hashes, isolates bitgen output,
  preserves ancestry and hashes. All other networking builds continue.
- OPT_16_HBM_GATHER_OUTSTANDING128 recovery attempt_03 PASSED build
  acceptance around22:40 CET. Final setup WNS0.000ns, hold+0.001ns; all artifact
  hashes independently reverified. Image SHA256:
  8c26c5d942c048efe3dfd17536cac060037f10ca6e33bc6ca0db1db8b8f66e3c.
  Full resources:246511LUT,401348FF,713BRAM tiles,664DSP. CSR14 windows32/64/128;
  unchanged250/450 clocks, model, ABI6 and cache orders10/9. Board validation
  remains pending. Its freed slot automatically launched OPT12 original-clock
  physical retry attempt_06; all six active jobs are now networking jobs.
- OPT_14 attempt_03 subsequently failed WNS-0.092ns only in HBM450 read
  adapter control; application250 setup passes. Its slot automatically launched
  NET_REF_RDMA_HBM. OPT14/15 repair diagnoses are preserved and deferred.
- First policy-driven handoff: OPT_15 attempt_03 failed final timing around
  21:19 CET (WNS-0.234ns); its slot automatically launched NET_REF_RDMA_STOCK.
  Reader diagnosis is saved in reader root `deferred_repairs.json`: wide active
  request/peak arithmetic plus HBM450 adapter path. No reader repair launched.
  Scheduler startup handoff grace fixed: a pre-existing prepared status file
  must not end the watch before the worker publishes its PID. Only scheduler
  restarted; active builds untouched; launch notification delivered.
- Six build jobs maximum. Let every currently running networking/HBM job finish.
- Networking has priority over ALL subsequent HBM reader launches or repairs.
  Failed reader jobs retain evidence, get diagnosed and wait behind networking.
- Ordered prepared queue in `hls4ml/optimize/runs/hbm_network_20261107/repair_queue.json`:
  1. NET_REF_RDMA_STOCK/attempt_01: official Example09 application unchanged,
     native250/450 clocks, capacities8/16, 4KiB MTU, one region, two host streams;
     no application HBM. RoCE still uses HBM for retransmission.
  2. NET_REF_RDMA_HBM/attempt_01: same control plus one card stream; incoming
     WRITEs target CARD0, incoming READ responses retain HOST0. No ring/CNN/GPU.
  3. Existing queued OPT12 original-clock physical retry, then network repairs.
- Both controls passed real-interface elaboration and128 RTL transport cases
  each (metadata, payload, backpressure; no duplicate host WRITE). No board
  acceptance or production timestamp equivalence is claimed for controls.
- Controls reuse the sealed platform/RoCE snapshot; stock wrapper bytes are
  identical to Example09. CMake selects U55C and isolated project paths/names.
  New tool snapshots include24-hour stage watchdog and routed clock checks.
- Persistent tmux `network_priority_scheduler_v3`, maintained code
  `hls4ml/optimize/build_campaign/network_priority_scheduler.py`. Counts all
  live workers INCLUDING project generation against6; launches ready network
  jobs every10s; startup observations every30s for5min; durable ntfy launch
  outbox. Existing `hbm_network_monitor` and `hbm_reader_recovery_monitor`
  retain terminal notifications. Do not manually race the scheduler to launch
  queued attempts. Add validated future networking repairs to repair_queue.json.
- Scheduler heartbeat/state: network root `priority_scheduler.json`; events:
  `priority_events.jsonl`. It never retries hardware blindly; agent diagnoses
  failures. Reader queue policy and network scheduling_policy.json updated.


## GPU dispatch limitation and possible follow-ups — 2026-11-08

- **Editorial instruction from the user: keep this limitation and these
  follow-up proposals out of the paper unless the user explicitly requests
  their inclusion.** This is internal engineering context, not permission to
  describe the current implementation as fully CPU-free. No paper edits or
  follow-up experiments are authorized by this memory entry.
- Current GPU offload moves the input from FPGA HBM into GPU memory through
  PCIe P2P. CPU-side TensorFlow/XLA runtime code still dispatches preprocessing
  and inference and coordinates result publication. The FPGA autonomously
  polls the GPU-resident verdict mailbox; autonomous polling does not imply
  autonomous inference launch. Writing input bytes into GPU memory does not
  by itself invoke the compiled model.
- This is a limitation of our current implementation, not an established
  fundamental inability of an FPGA to trigger GPU execution. XLA compilation,
  cached ConcreteFunction calls, and ordinary HIP graph replay do not by
  themselves provide an FPGA-controlled launch interface.
- Possible follow-up 1: CPU initialization/prelaunch once, then GPU-side work
  waits for an FPGA-written readiness signal and executes inference for each
  input. Investigate whether the full compiled model can be executed repeatedly
  behind that trigger, including all kernels/dependencies, memory visibility,
  synchronization, and result publication. A waiting GPU kernel alone does not
  establish this capability. Feasibility with our TensorFlow/ROCm stack is
  unverified; this is an investigation candidate, not an implemented solution.
- Possible follow-up 2: FPGA submits GPU dispatch packets directly through
  AMD AQL queues and signals their doorbells. Investigate queue/doorbell
  accessibility from the FPGA, mappings and permissions, packet publication
  ordering, kernel arguments, dependencies, and completion handling. Existing
  P2P access to GPU buffers does not prove access to these control resources.
  Expect custom runtime/driver/FPGA integration; no feasibility claim yet.
- Distinguish removing CPU involvement per inference from eliminating CPU
  setup, driver initialization, and memory/queue allocation altogether.
- References: [AMD AQL dispatch and doorbells](https://rocm.docs.amd.com/projects/llvm-project/en/docs-6.4.3/LLVM/llvm/html/AMDGPUUsage.html)
  and [HIP graph execution](https://rocm.docs.amd.com/projects/HIP/en/latest/how-to/hip_runtime_api/hipgraph.html).

## Reader recovery using free build slots — 2026-11-08

- Historical scheduling instruction (superseded by latest networking priority
  above): use all **six concurrent build slots**. Launch OPT_14 and OPT_15 in
  the two free slots alongside four networking builds; OPT_16 starts when a
  shared permit becomes free. Preserve networking workers and supervisors.
  Shared permit configuration:
  `hls4ml/optimize/runs/hbm_network_20261107/permits/capacity.json`.
- **OPT_10 and OPT_11 have already been benchmarked on the FPGA/GPU host.**
  See `hls4ml/optimize/runs/hbm_benchmark_20261108/` and
  `hls4ml/optimize/reports/optimizations/2026-11-08_hbm_resident_verdict/`.
  Individual 64-byte FPGA gather requested about 4 MiB per real input at
  1.4–1.6 GB/s; sequential HBM-to-GPU forwarding reached about 7.5 GB/s.
  Initial real-input medians: OPT_10 about 2.7–3.1 ms; OPT_11 about 1.3–8.0 ms.
  These are requested-payload/interface rates, not physical HBM-wire bandwidth.
  Preserve the unexplained 9.825% identical-image reprogramming variation.
- Follow-up objective: improve FPGA inspection with fewer/larger transactions
  or more outstanding requests. Recover the SAME IDs: OPT_14_HBM_SCAN (64 KiB
  chunks, four outstanding, short final request); OPT_15_HBM_COALESCED_GATHER
  (CSR14 groups 1/2/4/8, zero=4, <=16 KiB descriptors, 2 MiB boundary splits,
  duplicate suppression); OPT_16_HBM_GATHER_OUTSTANDING128 (native outstanding
  and TLB-active capacities 128, CSR14 windows 32/64/128, zero=32).
- Original root: `hls4ml/optimize/runs/hbm_reader_optimizations_20261108_032142/`.
  Its attempt_01 synthesis logs end with Terminated around 06:54 CET Nov 8;
  controller host is hacc-gpu-u55c-01 and its running statuses are stale.
  No candidate bitstreams or completed top-level synthesis checkpoint exist.
  An external interruption is suspected; the initiator is unconfirmed.
  Do not restart the old host-bound controller or overwrite old logs/statuses.
- Recovery queue: `hls4ml/optimize/runs/hbm_reader_recovery_20261108/queue.json`;
  source plan/controller/journals are copied into its `ancestry/` with hashes.
  Network campaign `followup_queue.json` points to it. OPT_14/15 isolated
  attempt_03 recovery workers resumed synthesis in shared slots 4/5 at about
  16:30 CET; first five synthesis minutes passed 30-second supervision. OPT_16
  attempt_03 acquired slot 2 at 17:11 CET after OPT_13 failed, and passed its
  first five minutes of supervision. All six permits are occupied (three
  networking + three reader builds). Check each
  attempt's status.json for live stages. Verified 813 sealed source files for
  each of OPT_14/15, plus pinned weights and 127/127/128 model/config/helper source
  hashes for OPT_14/15/16; found 27/44/41 completed component-run markers.
  Checkpoint/project migration and full continuation validation must pass;
  this inventory is not build acceptance. Shared capacity file now selects six.
- Recovery attempt_02 for all three passed the original parity/RTL validation
  but failed our new project-dependency probe: `get_files -all` includes pending
  generated DCP/stub/simulation outputs. Vivado identifies these with
  IS_GENERATED=1 and an existing PARENT_COMPOSITE_FILE XCI. Corrected attempt_03
  requires every real input; permits pending generated outputs only when their
  generator exists. Preserve attempt_02 evidence; this is a recovery-script
  correction, not an HDL failure or hardware-repair-budget use. Reuse the freshly
  passed validation only after identical full source/config/gate hashes and
  pinned weights/CPU reference checks. Always rerun the corrected project probe.
- Recovery tooling: `build_campaign/hbm/readers_recovery_{prepare,worker,monitor}.py`.
  Full copies preserve original work; generated paths are remapped locally.
  No configure/project/HLS export rerun; reset only unfinished component runs
  and top-level synthesis. Shared permits cover synthesis through acceptance.
  Recovery monitor tmux `hbm_reader_recovery_monitor`; watch both campaign roots
  with `build_campaign/wait_campaign_events.py`. That helper also wakes on a
  recovery acquiring a permit, so its first five synthesis minutes get reviewed.
- Actual Vivado continuation retained 25 completed shell component runs for
  OPT_14, 40 for OPT_15 and 37 for OPT_16; unfinished runs were reset. Earlier 27/44 inventory
  numbers count all completion markers, not just reusable shell component runs.
  Original HLS exports and project generation were reused; no model/clock changes.
- HLS exports, generated projects and component synthesis checkpoints survive.
  Use a separate dated recovery root and isolated fresh attempts with explicit
  ancestry. Verify hashes, dependencies, paths and Vivado 2024.2 before reuse.
  Continue unfinished synthesis without rerunning configure/project blindly.
  Original gates: 158 per-job cases plus 60 actual-file reader C-sim cases.
- Preserve OPT_6 CNN/weights/RFs/FIFOs/first-pixel guard, preprocessing, ABI6,
  **250 MHz application / 450 MHz HBM**, one application-memory stream and
  translation-cache orders 10/9. No FIFO profiling and no clock reduction.
  OPT_15's 5.234 ns HLS request-generation estimate is a risk, not an observed
  routed failure. Repair from actual evidence in fresh attempts; keep the
  original three-correction budget/history and 24-hour stage watchdog.
- Four tool threads per recovered build. Inspect every 30 seconds for the first
  five minutes, completion every 10 seconds and progress hourly; attach durable
  ntfy launch/failure/repair/acceptance notifications with independent retries.
  Acceptance requires unchanged-clock routed timing, source identity, native
  capacities/cache settings, complete artifacts, hashes and resource reports.
- This build-host recovery is **build-only**. Future GPU-host benchmarks use
  fresh OPT_10/11 controls and every reader setting in two programming rounds.
  Timing remains accepted arm to FPGA verdict, excluding preload/file I/O and
  GPU compilation/warmup; successful drain is separate. No embedded CPU or PR
  enforcement has been implemented. Do not run programming/benchmarks here.

## Editable presentation assets for the paper — 2026-11-08

- **User requirement: deliver paper diagrams as editable `.pptx` files that
  can be opened, edited, and rendered/exported in Microsoft PowerPoint.**
  Keep text, shapes, icons, and connectors editable; a slide containing only
  a flattened image does not satisfy this requirement. Supply a matching
  vector PDF for LaTeX and optionally a PNG preview. Preserve the editable
  source alongside each figure, including the Section 5 standalone network
  architecture in `paper/figures/coyote_network_standalone.pptx`.
- For the Section 5 Coyote figure, the user specifically wants **almost all
  original `coyote-figure.pptx` artwork retained**, not a newly drawn layout.
  The derivative now reuses the original FPGA objects, colors, icons, services,
  checker/admission branches, and TLB/vFPGA groups. Only the CPU/PCIe submission
  path is replaced with network ingress and HBM staging is annotated. Preserve
  this minimal-edit approach for further revisions.
- The user supplied the editable presentation at
  [[hls4ml] ML-Based Deep Bitstream Inspection for Serverless FPGAs .pptx](<[hls4ml] ML-Based Deep Bitstream Inspection for Serverless FPGAs .pptx>).
  The space before `.pptx` is part of the filename. This is the editable
  counterpart/reference for the hls4ml talk PDF; slide numbering can differ
  because the PDF includes animation steps.
- **Reuse and adapt this presentation's icons, diagrams, and other assets for
  paper figures.** Preserve the original presentation. Prefer editable native
  PowerPoint objects and vector PDF exports over screenshots or raster crops.
- Slide 4 contains happy/devil faces, binary data, shield, gears, lightning,
  and threat icons. Slide 7 contains the logic-gate FPGA symbol as native
  grouped shapes. `coyote-figure.pptx` is another reusable architecture asset.
- The current background diagram is generated by
  `paper/generate_background_figure.py` as
  `paper/figures/background_threat_model.{pptx,pdf,png}`. It reuses these
  assets, adds a thermometer, and keeps icons editable as grouped vector
  paths. The FPGA boundary encloses inspection and partial reconfiguration.
  No overall title is shown; the complete admission/control path remains
  proposed. See `paper/FIGURES.md` for regeneration and PowerPoint editing.

## First build results and diagnostic recovery — 2026-11-08

- **Online reference investigation 2026-11-08:** local `RoCE BALBOA.pdf` is
  arXiv:2507.20412v1; it demonstrates U55C/Coyote/XDMA/CMAC with 512-bit streams,
  250 MHz datapath and 4 KiB MTU. The paper pins network commit
  9eda6ce9a55c0761ee9e66d1eba38ad5c9474aa9. GitHub's compare API confirms our
  37b59d3828b003d2d6f7dd9748824a0e39d99167 is two commits later, changing only
  22 CMake/Tcl build files (Vitis 2025.1 support), not C++/RTL datapath sources.
  Do not assume a rollback fixes our CMAC/HBM timing paths.
- Official `examples/09_perf_rdma` is a better minimal control than our current
  NET_DIAG: host forwarding, one region, two host streams, EN_RDMA=1,
  BUILD_OPT=1, default matched 250 MHz clocks; application EN_MEM remains0.
  Coyote still enables HBM for RoCE retransmission. Its native memory-client
  count is1, versus3 with our EN_MEM=1, one region and one card stream.
  Local default outstanding/TLB-active capacities are8/16; our network builds
  use32/64. Reproduce the unmodified example first, then add application HBM,
  then checker/P2P to isolate integration effects. This is a recommendation,
  not another launched build or permission to modify active snapshots.
- We already use the example's BUILD_OPT=1 directives; this is not a missing
  switch. Local original-clock Coyote templates/config match the local upstream
  tree; pnr template differs only by the added hierarchical utilization report.
- Upstream network timing commit83d884db574e1fcd5a8766582c0c906c267c69e5
  ("Timing improvements for 200G RDMA") reduces FIFO depths, replaces CRC wide
  selection with arithmetic/encoding, uses LUTRAM for smaller tables, and lowers
  default QPs500→256. Potential separate experiment; it does not directly repair
  our latest CMAC powergood or HBM width-converter critical paths. Preserve
  retransmission and protocol tests if evaluating it; no blanket upgrade.
- Primary sources: https://arxiv.org/html/2507.20412v1 ;
  https://github.com/fpgasystems/Coyote/tree/master/examples/09_perf_rdma ;
  https://github.com/fpgasystems/fpga-network-stack/pull/48 ;
  https://github.com/fpgasystems/fpga-network-stack/commit/83d884db574e1fcd5a8766582c0c906c267c69e5 .

- Clock-checker caveat found while preparing OPT_12 original-clock retry:
  Vivado can merge equivalent ACLK/UCLK generated clocks; its final report then
  omits the `clk_out3_design_ctrl_clk_wiz_0_0` name. A strict name-only check
  would falsely reject a valid netlist. Maintained `network_timing.py` now falls
  back to a read-only routed-DCP query at the user-domain ARP register clock
  pins (`nolabel_line337` in pinned generated RTL), checking period and hashes.
  The boundary port itself was optimized away. Query validation passed against
  210 physical ARP register clock pins: the propagated clock is CLKOUT1 at 4 ns.
  Evidence: `hbm_network_20261107/clock_alias_probe/verified_arp_clock.log`. Running network workers
  retain their older sealed helper; if they fail solely with "Missing routed
  user clock" AFTER timing passes, preserve that attempt and finish acceptance /
  bitgen in a fresh continuation with the validated helper. Do not resynthesize
  valid hardware, silently mark it passed, or edit running snapshots.

- **19:28 CET:** Original-clock OPT_12 attempt_03 failed narrowly: WNS -0.100 ns
  in CMAC powergood state→wait-counter control; HBM450 width-converter control
  misses 0.033 ns. Application250 paths meet setup. Clock-aligned fallback
  attempt_05 launched into its freed slot and reuses verified CNN/preprocess IP.
  Queued one original-clock physical retry as attempt_06, strategy1 from its own
  routed checkpoint; no RTL/clock/exception changes. Tool snapshot and seed
  hash: `hbm_network_20261107/queued_recovery_tooling/opt12_original_clock_retry/`.
  New physical runner checks routed application/user/HBM clocks before bitgen
  and has a 24-hour stage watchdog. All six jobs remain active; do not launch
  attempt_06 until capacity frees. Do not repeat physical retries indefinitely.

- **18:30 CET:** OPT_12 fallback attempt_04 failed WNS -0.975 ns, entirely in
  the direct ACLK200/UCLK250 path groups in the timing summary; HBM350 and
  same-clock groups meet setup. Diagnostic attempt_08 launched into its slot.
  OPT_12 attempt_05 is being prepared with UCLK=ACLK=200, keeping the validated
  CNN/preprocessing HLS cache, RTL and HBM350. Original-clock OPT_12 attempt_03
  continues independently. OPT_13 attempt_08 reached synthesis and its generated
  MMCM ratios verified ACLK200/NCLK250/UCLK200. Reader OPT_14/15 reached physical
  implementation and OPT_16 user synthesis in the 18:20 hourly review.

- **17:45 CET:** NET_DIAG_HBM attempt_07 failed final timing: WNS -0.897 ns,
  mainly the same UCLK250/ACLK200 direct-path mismatch; a separate 200 MHz CSR
  path misses 0.123 ns. HBM350 setup passes. Validated OPT_13 attempt_08 launched
  in the freed capacity; NET_DIAG attempt_08 is prepared with matched native
  ACLK/UCLK200 and queued. Both preserve NCLK250/HBM350 and all payload RTL.
  Original-clock OPT_12 attempt_03, fallback OPT_12 attempt_04 and all three
  reader recoveries continue. Keep checking actual status, not this snapshot.

- **17:11 CET update:** OPT_13 network/GPU attempt_07 failed final setup timing
  (WNS -1.002 ns); its permit was immediately acquired by reader OPT_16
  attempt_03. Six builds remain active. The dominant failure is a fallback
  configuration error: ACLK=200 MHz but native UCLK remained250 MHz. Coyote's
  dynamic_top ARP meta_reg_array uses UCLK directly beside ACLK MMU registers,
  yielding a1ns cross-clock setup requirement. Do not blame this failure on HBM:
  the350MHz HBM domain has no failing setup paths in that report. A separate
  Ethernet padding FSM→payload fanout path misses0.208ns at fixed MAC TX clock.
- Prepared OPT_13 attempt_08 aligns native UCLK_F=ACLK_F=200, retaining
  NCLK250/HBM350, and targets only measured Ethernet padding state fanout for
  pre-route replication. No payload RTL/model edits or timing exceptions.
  `repair_queue.json` in the network campaign records the capacity wait.
  Other network attempts remain running; do not alter their snapshots.
- New `network_timing.py` checks actual generated MMCM output ratios for ACLK,
  NCLK and UCLK and final routed UCLK. It rejects the old200/250 mismatch;
  original250/250 OPT_10 passes. New deployment preparation explicitly sets
  UCLK_F with ACLK_F. The earlier fallback check covered ACLK/HBM but missed
  this coupled control clock; preserve that limitation in the repair history.

- Why network closure is harder: generated base.tcl has cfg(n_mem_chan)=2 for
  HBM-only OPT_11 but3 for network NET_DIAG_HBM. EN_RDMA adds an HBM interface
  path, not merely network ingress. Diagnostic attempt06 worst setup failure is
  path_2, but this index must not be identified as the added RoCE client:
  generated shell_top maps axi_ddr_rdma to axi_mem[0], shifting other indices.
  RoCE's dedicated HBM client buffers outgoing/retransmission payloads;
  incoming bitstreams reach HBM through our dual-reader ring's storage branch.
  Full network_top itself uses about125k LUTs.
  Routed OPT11 vs OPT13 attempt06: LUT182013 vs330310; registers281970 vs610050;
  BRAM tiles179.5 vs467. Network figures are resource evidence from a timing-
  failed attempt, not an admitted benchmark image. Global occupancy is modest;
  local fanout/routing and new450MHz interface paths are the closure problem.

- OPT_13 attempt_06 subsequently failed: HBM -0.375ns, old ring control -0.175ns.
  Matching clock-fallback builds launched and watched for five minutes:
  NET_DIAG_HBM attempt_07, OPT_13 attempt_07, OPT_12 attempt_04. All200/350MHz;
  final variants include the tested bounded ring repair. OPT_12 attempt_03 retains
  original250/450MHz and continues. No new board validation or benchmark claim.
- OPT_12 attempt_04 copies verified HLS IP compiled for4ns and runs it at5ns.
  The original RTL schedule is preserved. Cache checks accept a slower runtime
  clock and reject a faster one than the compilation target (tested300MHz reject,
  200MHz accept). Actual integrated clocks and final timing must still pass.

- NET_DIAG_HBM attempt_06 fresh placement still failed: HBM -0.529 ns,
  application -0.252 ns. Attempt_07 is a clearly labelled clock fallback:
  application200MHz/HBM AXI350MHz. Regenerate real clock IP and HBM IP metadata;
  never merely loosen constraints. New workers verify generated MMCM/IP values
  and routed application/HBM clocks before admitting bitgen. OPT_13 matching
  fallback is being prepared. Passed Option1 OPT_10/11 remain250/450MHz.
- ABI5 events remain raw ticks. The schema clock_hz is only the original default;
  future collectors must use the selected attempt's verified config.json clock_hz.
  At200MHz use200ticks for an equivalent1us polling interval. Explicitly label
  clock-fallback results; do not silently combine them with250MHz measurements.
- OPT_12 attempt_03 cache retry reached integration synthesis. Redundant attempt02
  was stopped as superseded after this; logs and sources preserved. Its CPU-active
  export was slow, not proven deadlocked. Read status.json for current stages.

- OPT_12 attempt_02 re-exported its unchanged CNN for over 90 minutes with no
  new export log output (process remained CPU-active; not proven deadlocked).
  Attempt_03 is an independent retry with the same ring repair and verified
  attempt_01 CNN/preprocessing IP packages. New deployment_ip_cache.py checks
  sealed HLS source equality, part, tool2024.2, 4ns target, package file closure
  and hashes. Copies packages locally; skips only HLS compilation. Integration
  synthesis/routing/final timing still run. Installation, RTL tampering rejection,
  HLS source mismatch rejection and wrapper wiring passed. Attempt03 launched;
  five-minute worker/cache-install watch passed. Prior attempts remain preserved.

- Later checks: OPT_13 attempt_02 failed timing (-0.384 ns); NET_DIAG_HBM
  attempt_03 failed (-0.342 ns). Attempt_05 targeted replication completed
  successfully before routing, but intermediate routed timing remains negative.
  Both attempt_06 jobs restart placement from their own shell_opted.dcp with
  strategy3 (Explore placement, AlternateReplication). RTL/clocks unchanged.
- OPT_12 attempt_01 routed timing is -0.460 ns, including a 64-bit ring occupancy
  path into Coyote receive-FIFO control. Prepared attempt_02 changes only
  dual_reader_ring.sv and its attempt-local CMake path: bounded occupancy/read
  pointers control ready/prefetch; 64-bit counters remain statistics. Component
  RTL regression passed (two frames, stalls, full capacity, exact counts), and
  Coyote wrapper wiring elaboration passed. Read live status for launch/finish.
  Original attempt_01 and all failed physical attempts remain preserved.
- OPT_12 attempt_01 subsequently terminated as timing-failed. Attempt_02 launched
  after its slot was released; five-minute worker-identity watch passed. Both
  fresh-placement attempt_06 jobs also passed their five-minute startup watches.
- New deployment workers check final timing before bitgen, avoiding generation
  of timing-invalid images. Already-running worker snapshots remain unchanged.

- Correction: targeted attempt_04 for NET_DIAG_HBM/OPT_13 failed before doing
  replication: Vivado2024.2 rejects force_replication_on_nets after routing.
  Earlier startup-watch success did not establish operation completion. Both
  corrected attempt_05 jobs use shell_placed.dcp, verified in provenance, then
  force replication before routing. RTL and clocks unchanged. Preserve attempt04
  logs/diagnosis; do not retry the routed seed with forced replication.

- OPT_13 attempt_03 (alternate placement) also failed timing, WNS -0.681 ns.
  Targeted attempt_04 launched for OPT_13 and NET_DIAG_HBM: force replication
  on high-fanout register-slice state/enable nets, then reroute. This is physical
  optimization only, retaining RTL and clocks. Both five-minute watches passed
  and commands were accepted by Vivado. Explicit selected-net evidence is saved
  in reports/forced_replication_nets.txt within each attempt. Max five active jobs.

- OPT_10 attempt_01 subsequently PASSED bitgen; all artifact hashes checked and
  ntfy delivery verified. Both Option 1 builds (OPT_10/11) are now build-passed.
- OPT_13 attempt_01 FAILED final timing: WNS -0.431 ns, TNS -2089.893 ns.
  Worst path is a 250 MHz RDMA register-slice state→wide-data path dominated by
  routing; a 450 MHz HBM path also fails at -0.263 ns. Sources/model remain valid.
- OPT_13 physical attempts_02/03 launched, alongside NET_DIAG_HBM attempts_02/03.
  Strategy1 starts from routed DCP; strategy2 from placed DCP with alternate
  fanout/routing directives. All retain original RTL and clocks. OPT_12 continues.
  These five active jobs share the five-slot limit. Five-minute startup watches
  for the new recoveries passed; diagnosis/provenance/status retained per attempt.

- OPT_11_HBM_GPU_P2P_R06 attempt_01 passed routing/timing and bitgen. Artifact
  hashes independently rechecked; terminal ntfy delivery verified. Board admission
  and external GPU DMA visibility still require the benchmark host.
- OPT_10 attempt_01 finished routing with WNS +0.015 ns, WHS +0.007 ns and no
  timing violations; bitgen in progress at this entry. Read live status for finish.
- NET_DIAG_HBM attempt_01 final timing FAILED: WNS -0.367 ns, TNS -830.413 ns,
  in the 450 MHz HBM width-converter first_word_reg → register-slice payload CE
  path (fanout576). Do not use its images even if bitgen produces files.
- NET_DIAG_HBM attempt_02 is a fresh physical recovery from its own routed DCP:
  AggressiveFanoutOpt, NoTimingRelaxation, unchanged RTL and clock constraints.
  Started epoch1794097761; tmux hbm_network_diag_recover_02; same five-slot limit.
  Diagnosis/provenance are in the campaign. Five-minute restart watch required.
- Completion monitor now recognizes deployment_recover.py via explicit process
  markers; monitor session refreshed, previous ntfy delivery receipts preserved.

## HBM/network build campaign launched — 2026-11-07

- Build host hacc-build-03; campaign [hbm_network_20261107](hls4ml/optimize/runs/hbm_network_20261107/README.md).
  NET_DIAG_HBM and OPT_10/11/12/13 workers launched. Read per-attempt status.json
  for current stage; launch does not imply routing or board admission success.
- User authorized all five builds concurrently, including speculative network
  builds before physical-link validation, ten-minute initial monitoring, and
  diagnosis/repair/restart with five-minute monitoring after each failure.
- Opt-in five shared implementation slots, four Vivado threads per job. Tested
  sixth-job waiting and slot release on worker death. Historical lane defaults
  remain for older campaigns. No board programming from this build campaign.
- Sealed snapshots contain pinned Coyote/network sources; each CNN snapshot
  contains full configuration and verified cached stock OPT_6 compiler output,
  weights identity and FIFO evidence. No repeat profiling/custom conv0 kernel.
- New deployment ABI5 and event/counter meanings: `hls4ml/optimize/build_campaign/deployment_abi.json`;
  old ABI3/4 collectors must reject these images. GPU inference readiness is
  defined there, separately from final verdict/drain status.
- Independent tmux `hbm_network_monitor` sends terminal events to ntfy and records
  delivery. Active-session event waiter `wait_deployment_event.py` returns on
  completion/failure/lost worker for assistant diagnosis; it does not by itself
  schedule a new model turn if the active session is terminated.
- Networking fork owns live QSFP/RDMA/HBM and GPU visibility validation. Component
  tests and wiring elaboration passed; full combined RTL/board admission remains.

## Option 2 additional host validation — 2026-11-07

- [Validation log and reproduction commands](hls4ml/optimize/runs/option2_host_validation_20261107/README.md)
  and machine-readable summary.json in the same folder. No FPGA programming/builds.
- ConnectX-5 local two-RC-QP probe: **108/108 exact-byte transfers**, boundary
  sizes through 128MiB−64B, one/four outstanding chunks, changing patterns and
  intact tail guards. This can loop within the NIC; not physical fabric validation.
- Actual Coyote address-helper test passed. Integer-sampling model: 17 cases;
  abstract two-consumer credit model: 100 randomized schedules. These do not
  validate new receiver RTL or a completed production NIC→Coyote sender.
- Accepted R06 runtime on GPU0: 15 sizes, 45 calls, exact selected-byte parity and
  CPU score/verdict agreement; max absolute score error 1.52587890625e-05.
  Normal TensorFlow host→GPU allocation; external FPGA DMA visibility untested.
- Archived OPT_8 variant11 polling/forwarding RTL regression passed outside the
  sandbox (initial sandbox xsim Tcl exception preserved). Includes stale replies,
  CQ ordering, backpressure, invalid trial, timeout/drain, reset/consecutive frames.
- All eight real report inputs have expected sizes and newly recorded hashes.
  Remaining gate: NET_DIAG_HBM live QSFP/ARP/RDMA→HBM validation and new receiver
  RTL/ABI tests; subsequent full FPGA/GPU admission remains required.

## Option 2 concrete build handoff — 2026-11-07

- Authoritative next implementation plan: [Option 2 build handoff](hls4ml/optimize/plans/2026-11-07_option2_build_handoff.md);
  [plan index](hls4ml/optimize/plans/README.md). Diagnostic NET_DIAG_HBM first,
  then OPT_12_NET_STREAMING and OPT_13_NET_GPU_P2P_R06 after link/byte-test gate.
  Option 1 remains assigned to the other build-host agent; this investigation
  did not start builds or program hardware.
- Coyote HEAD inspected: 502a94af61107e7b9a54d5b669ca60d2dbc47753; network submodule
  pinned at 37b59d3828b003d2d6f7dd9748824a0e39d99167 is empty locally. Restore
  the pinned source in the isolated build checkout before RDMA IP generation.
- **NIC interoperability traps confirmed:** writeQpContext's argument sets the
  remote UDP destination. Use 4791 for ConnectX-5, not initRDMA's default control
  port18488. Pinned stack listens on 4791. Coyote IPv4 extraction uses bits127:96;
  use its repeated-IPv4 internal format, while NIC AH uses standard IPv4-mapped
  GID. Do not blindly copy the NIC GID into Coyote registers.
- Concrete MVP defaults: local NIC sender, device2 QSFP0 .114 receiver, GPU0;
  64KiB chunks, four-bank 256KiB ingress ring, one-credit admission then four-credit
  main runs. Credits follow both branches' consumption, not NIC acknowledgements.
  Separate HBM commit, GPU DMA completion and verdict timing. No PR eligibility
  until complete stored bytes, no errors and a benign decision.
- Confirmed current Coyote restricts builds to one QSFP and rejects networking
  on Versal. EN_MEM plus EN_RDMA derives an additional network memory client;
  validate generated HBM mapping rather than reusing Option 1 addresses blindly.
- Live NIC/RDMA and XRT statuses were rechecked; FPGA QSFP connectivity and actual
  NIC→Coyote interoperability still require the diagnostic image. No throughput
  result or cabling confirmation is implied by this plan.

## Option 2 benchmark host preflight — 2026-11-07

- Live host: `hacc-gpu-u55c-01.inf.ethz.ch`. Read-only inspection; no programming,
  driver/network changes or benchmark traffic. Some device/netlink queries need
  execution outside the sandbox; missing sandbox device nodes do not imply
  absent host hardware.
- Preferred sender is this host's ConnectX-5 Ex: PCI `0000:61:00.0`, `data1`,
  `mlx5_0` port 1, `10.253.74.110/24`, MTU 9000, live 100000 Mb/s Ethernet.
  RDMA is ACTIVE, active RDMA MTU 4096; IPv4 RoCE v2 GID index 3. NUMA0,
  PCIe Gen4×16. `libibverbs`, `ib_write_bw` and accessible uverbs nodes exist.
  `data2` / `mlx5_1` is down and ethtool reports no cable. data1 FEC is off;
  global RX/TX pause is on, which is not proof of PFC or switch configuration.
- Receiver remains hdev device2 / `0000:81:00.0` / `XFL13BA4HVZYA`, U55C,
  NUMA1 Gen3×16. Site CMDB assigns ports `10.253.74.114/.115`, MACs
  `00:0A:35:0F:52:18/00:0A:35:0F:52:1C`. Route to .114 uses data1.
  These are assigned identities, not proof of physical QSFP link/reachability.
- **Current firmware supersedes older installed-image notes:** both U55Cs are
  XRT-ready on `xilinx_u55c_gen3x16_xdma_base_3`; xocl/xclmgmt loaded, no Coyote
  driver. Device1 at `a1:00.0` / `XFL1BE3ESRZ4A` is also XRT-ready, with assigned
  `.112/.113`; this does not prove Coyote programming/network readiness.
  Two VCK5000 cards also enumerate, but are unnecessary for the MVP.
- MI210 GPUs remain at `03:00.0` and `25:00.0`, NUMA0 Gen4×16. Thus FPGA→GPU
  still crosses the NUMA topology; no new P2P throughput was measured.
- Proposed physical path: NUMA0 host buffer → local ConnectX-5 → external
  Ethernet fabric → U55C device2 QSFP → HBM plus streaming checker/GPU forwarder.
  No second server needed if the fabric connects these ports. Cable/switch/VLAN
  and receiver link remain unverified until a network-capable image is loaded.
- Coyote example09's client is Coyote-specific, not a stock NIC verbs client.
  Implement a small libibverbs sender and compatible QPN/PSN/GID/rkey/address
  exchange; match Coyote's compiled MTU. Do not assume ib_write_bw speaks the
  example's setup protocol. Stock Coyote documents ConnectX-5 interoperability.
- Preflight next step: known-compatible RDMA diagnostic image and driver, then
  verify CMAC link, ARP/QP setup, exact-byte transfers and paced throughput.
  Installed site images found: Coyote hello-world and OpenNIC, not a ready
  example09 image. No FPGA QSFP carrier test or RDMA transfer was performed.
  Queue details: [Option 2 plan](hls4ml/optimize/plans/2026-11-07_network_streaming_mvp.md).

## HBM and network inspection plans — 2026-11-07

- Saved Option 1 plan: [HBM-resident inspection](hls4ml/optimize/plans/2026-11-07_hbm_resident_inspection.md).
  Planned OPT_10 gather + OPT_6 CNN and OPT_11 HBM → GPU P2P + R06;
  host emulates embedded CPU placement outside the measured interval.
  Primary interval: FPGA-local start acceptance → FPGA verdict acceptance.
  This is a saved plan, not a build launch or benchmark result.
- **Small-input preprocessing fix required:** production template
  `hls4ml/pipeline/coyote_accelerator/templates/zero_in_raw_downsample.hpp.in`
  scans every raw byte for `65,536 < N < 4,194,241` (approximately 4 MiB).
  Implement equivalent sample-driven processing in the new FPGA path, iterating
  over 65,536 pixels and caching aligned 64-byte input words. Existing
  `hls4ml/optimize/build_campaign/hardware/common/direct_preprocess.hpp`
  supplies a small-input reference. Preserve exact integer indices, inversion,
  normalization, fixed-point conversion, short-input padding and launch guard.
  Validate cutoff ±1 and 1/2 MiB cases; do not overwrite archived implementations.
  Existing eight real workloads exceed this cutoff, so do not attribute their
  projected HBM gains to this fix. Finding confirmed from source; new fix pending.
- Option 2 (RoCE receive → streaming inspection, retaining raw bytes in HBM)
  is queued in [the network MVP proposal](hls4ml/optimize/plans/2026-11-07_network_streaming_mvp.md).
  Do not treat this note as authorization to launch
  additional builds. Reuse Option 1 components, with separate network builds.

## Presentation timing decomposition and file-latency investigation — 2026-10-22

- Current presentation: `hls4ml/optimize/reports/optimizations/2026-10-22_gpu_opt_xla_concretefunction_presentation_input_timing/`.
  GPU_HOST only; accepted October 21 R06 GPU and OPT_6 FPGA measurements. User
  authorized overwriting this revision. Earlier reports remain preserved.
- Figure 12 now uses paired horizontal stacked bars of actual mean elapsed time:
  until full input is ready, then input-ready-to-verdict (CSR14). This replaces
  the confusing signed waterfall at the user's request. FPGA readiness uses CSR9;
  GPU readiness is host-observed after copy synchronization. Blue includes startup
  and is not pure transfer duration; Figure 10 retains measured transfer intervals.
  At 64 MiB FPGA is 5.247 + 0.040 = 5.287 ms, GPU 2.430 + 0.628 = 3.058 ms.
  At 16 MiB FPGA finishes 0.099 ms earlier (means). Short FPGA tails reflect
  inference overlapping reception; at 4 MiB reception includes CNN backpressure.
- October 23 presentation revision: Figure 9 (streaming overlap) includes only
  Buffering / OPT_0 and Streaming / OPT_1. Other figures keep their selections.
- File-latency irregularities are largely before invocation. For OPT_6, moving
  from 28.92 to 32.58 MiB raises mean file-to-verdict by about 9.18 ms, of which
  about 8.88 ms is file reading/preparation. GPU_HOST has near-perfect odd/even
  preparation alternation at 32.58, 39.37 and 46.29 MiB; 32.58 MiB groups take
  about 1.50/5.16 ms preparing the same file. A pooled median can fall between modes.
- Runtime code retains the preceding GPU NumPy input while allocating the next;
  FPGA file trials release the local input when their helper returns. Allocation
  and CPU-cache behavior are plausible explanations; buffer addresses and cache
  counters were not recorded, so the exact mechanism is unproven. Diagnostics:
  `data/file_timing_investigation.json`, `diagnostics/file_preparation_alternation.*`.
  Future host-only control: same preallocated/readinto buffer and allocation
  lifetime on both paths, logging addresses/page faults/cache counters on the
  actual GPU host. No FPGA rebuild is needed for that control.
- Offline investigation ran on the build host; no new benchmark calls or builds.

## R06 report selection and dated report folders — 2026-10-22

- User explicitly selected **R06 XLA + direct ConcreteFunction** for a new GPU
  comparison report: `hls4ml/optimize/reports/optimizations/2026-10-22_gpu_opt_xla_concretefunction/`.
  Earlier instructions excluding R06 still describe the preserved preprocessing-v2
  reports, not this new report. Archived `report_eligible: false` fields remain
  untouched; the new selection is recorded in the report's `data/report_selection.json`.
- GPU measurements come from the accepted `hardware_xla_concrete` campaign;
  FPGA OPT_0/1/6 results remain from the preprocessing-v2 campaign. The shared
  OPT_1 resident host-completion control differs by at most **0.02723%** across
  normal workloads. Main endpoint: prepared host invocation → FPGA result
  acceptance **CSR14**, with reception and final completion shown separately.
- At 4/16/64 MiB and 128 MiB−64 B, GPU_HOST medians are
  **0.811/1.447/3.051/5.423 ms**; GPU_P2P **1.602/4.732/17.067/33.437 ms**;
  OPT_6 **1.118/1.356/5.287/10.530 ms**. GPU_HOST wins three of four synthetic
  sizes; OPT_6 is slightly faster at 16 MiB and faster than P2P at all four.
- Report date is **22 October 2026**; accepted measurements are from October 21.
  Joint compute diagnostics are R06-only and separate from board timings:
  CPU0-7/NUMA0 versus CPU64/NUMA1. No split profiling of the fused graph.
- Report directories now start with `YYYY-MM-DD`. The mapping and preserved
  hashes are in `hls4ml/optimize/reports/report_path_migration_2026-10-22.json`;
  the report index is `hls4ml/optimize/reports/README.md`. Historical PDFs,
  plots and raw data are preserved; old path-bearing source/doc versions and
  manifests are retained in `.before_date_prefix/` where needed. Old ZIP/tar
  archives retain their original internal paths. Benchmark run roots are unchanged.

## Live P2P controls and DMA32 build — 2026-10-21

- **Completion verified on October 22:** OPT_9 built successfully and the automated candidate/closing transport tests completed at **20:34:41 CEST October 21**. Completion ntfy delivery is recorded in `notification.json`; board restored to OPT_8. Original/candidate/closing matrices passed correctness checks. This is transport validation only, not full CNN benchmark admission.
- **No material bandwidth benefit from DMA32:** largest-input local-host control original/new/closing **12.797/12.781/12.779 GB/s**; GPU1 fine **4.303/4.293/4.288 GB/s**. GPU0 fine **4.115/3.827/3.854 GB/s**: the unchanged closing reference also slowed **6.36%**, so the original-to-new decrease is confounded by drift and is not evidence of a DMA32 regression. New versus closing GPU0 differs by only −0.69%. Raw `comparison.json` records both comparisons; its original-reference speedup field must not be presented as a controlled causal effect. Pipeline `passed` means build/transport correctness, not a demonstrated performance improvement or a <5% drift gate.
- User authorized the live transport tests **and an additional FPGA build** on the GPU host. Campaign: `hls4ml/optimize/runs/p2p_transport_20261021_154140/`. Prior reports and accepted benchmark datasets remain unchanged; these are transport diagnostics, not new CNN end-to-end measurements.
- **980/980 transfers passed** exact-byte verification and autonomous FPGA mailbox validation: seven configurations, four sizes (4/16/64 MiB and 128 MiB−64 B), five warmups plus 30 measured trials per cell. Changing data patterns cover header, payload and padding; verification runs after the timed bulk transfer. A separate 12-call smoke test also passed.
- Same OPT_8 image, NUMA1 HPF source and CPU64 throughout. Largest-input median FPGA forwarding rates: **local NUMA1 host destination 12.797 GB/s; remote NUMA0 host destination 6.872 GB/s; GPU0 fine/default 4.115/4.149 GB/s; GPU1 fine/default 4.303/4.300 GB/s**. Closing GPU0 control: 4.150 GB/s. These use frame bytes divided by CSR19−CSR18 at nominal 4 ns/cycle: acceptance at the FPGA DMA output interface, not a direct VRAM-arrival timestamp. Host DMA completion times are recorded separately.
- **Zero bulk page faults and zero wrapper input-blocked cycles in every trial.** Driver logs show all seven 128 MiB destination mappings use **64 large 2 MiB translations and zero small translations**; NUMA placement of host controls is verified from `/proc/self/numa_maps`. Fine versus ordinary GPU bulk allocation did not materially change bandwidth; the polling mailbox remains fine-grained. This supersedes the previously unmeasured mapping/allocation hypotheses below. Evidence: `results/original_matrix/{summary.json,manifest.json,status.json}`, per-test CSV/log/DMA counters/dmesg, and `results/mapping_summary.json`.
- Physical links remain FPGA Gen3×16 and both GPUs Gen4×16. FPGA MPS/MRRS 512/512; GPU paths 256/512; GPU endpoints on NUMA0 and FPGA on NUMA1. No link downgrade or page-fault explanation found. Fast local-host loopback shows the same forwarding design can sustain 12.8 GB/s. Remote-host slowdown supports topology sensitivity, but does **not** isolate the GPU-specific bottleneck. No ACS/IOMMU/PCIe-control writes or reboot were performed.
- **OPT_9_GPU_P2P_DMA32 launched at 17:53:29 CEST**, currently synthesis at this entry. Self-contained job under `jobs/OPT_9_GPU_P2P_DMA32/`, catalog entry under `hls4ml/optimize/iterations/`. Native Coyote settings only: `N_OUTSTANDING=8→32`, `N_TLB_ACTV=16→64`, unchanged 4096-byte requests and 250 MHz clocks. Generated read/write credit FIFOs both grow from 512 to **2048 ×64-byte beats (128 KiB)**. Actual generated package/XCI settings verified in `preflight/generated_parameters.json`. Full-wrapper RTL regression passed using the new generated package. Performance improvement is not assumed.
- Original application RTL, timestamp ABI4 variant11 and autonomous polling are preserved; OPT_9 therefore shares OPT_8's ABI signature and must be identified by sealed image hash. Coyote inputs, hardware/test sources, accepted preprocessing-v2 runtime, controllers, probe, binary, library and driver are hash-pinned. No CNN/model changes. Four Vivado threads; one bounded physical timing recovery is allowed, with unchanged clocks, if routing completes with a timing failure.
- tmux **`p2p_dma32_pipeline`** builds, checks routed timing/artifact hashes, programs device2, reruns the same transport matrix, restores hash-verified OPT_8, and runs closing reference controls. It writes `comparison.json` and terminal `status.json`. Independent **`p2p_dma32_monitor`** sends success/failure/interruption to **`coyote-build-sdeheredia`** only after the pipeline terminates; success includes measured original/new/closing GPU0 bandwidth. Launch notification delivered (`launch_notification.json`); final delivery will be recorded in `notification.json`. Check these live files before reporting completion. Do not modify pinned tooling while it runs.
- Target remains **hdev device2 / XFL13BA4HVZYA / 0000:81:00.0**; device1 remains unavailable. Standard reset-enabled driver, existing board lease `gpu_fp32_20261018/board_device.lock`. Filtered localhost Vivado server: `p2p_transport_hw_server`. Board is currently OPT_8 during synthesis and will be restored to OPT_8 after successful comparisons. A failed candidate test may leave it on OPT_9: consult `preflight/installed_image.json` before reuse. No full CNN admission or report promotion is implied by transport success.

## Deeper P2P bandwidth investigation — 2026-10-21

- Static source/config audit and existing-trace reanalysis only, on `hacc-build-02`; no new FPGA builds, live transport experiments, or report changes. GPU-host SSH is not established in this session. Exact cause of the ~4.1 GB/s plateau is still **unconfirmed**.
- **Target ceiling:** saved environment records show FPGA **8.0 GT/s x16**, and OPT_8's `coyote/hw/bd/ultrascale_plus/cr_pci.tcl` explicitly configures Gen3 x16. Encoded one-direction capacity is `8e9 * 16 * (128/130) / 8 = 15.754 GB/s`, before packet overhead. The 512-bit/250 MHz internal stream is 16 GB/s, but that is not sustainable useful PCIe payload. `PCIE_GEN=4` in `build/export.cmake` does not establish a Gen4 negotiated link. Matching the existing GPU_HOST FPGA ingress rate (~12.8 GB/s) would already improve P2P transport ~3.1x, reducing largest-input bulk elapsed time from ~32.675 to ~10.486 ms; this is a target calculation, not a measured improvement. References: AMD DS978 PCIe Connector/Data Rates; AMD AM002 TX 128B/130B Encoder.
- **Coyote request settings:** both exact GPU builds have `EN_CRED_LOCAL=1`, `PMTU_BYTES=4096`, `N_OUTSTANDING=8`, `N_TLB_ACTV=16`, 250 MHz clocks. `req_parser.sv` splits commands into 4 KiB chunks; `req_credits_rd.sv` allows at most eight outstanding chunks per destination (~32 KiB). `req_credits_wr.sv` waits for a complete chunk's buffered data before issuing a write request. These can constrain latency hiding, but the identical settings achieve ~12.8 GB/s on GPU_HOST ingress, so they do not alone prove the P2P cause. Larger windows require a new FPGA build and compatible FIFO/credit sizing; do not blindly increase PMTU or disable credit protection. TLB mutex is released on a hit in ST_CHECK, **not** held until DMA completion.
- **Software experiment candidate:** measured `software/gpu_runtime/transport.cpp` allocates both bulk input and mailbox via `fine_alloc`; `mailbox.hpp` uses `hipExtMallocWithFlags(..., hipDeviceMallocFinegrained)`. Native Coyote's `sw/src/cThread.cpp` GPU allocator uses ordinary `hipMalloc`. Test ordinary/coarse bulk input while retaining a fine-grained mailbox, with an appropriate external-DMA visibility protocol and repeated changing-input byte/pixel/verdict parity. HIP 7.2 coherence documentation explains the cache-policy distinction, but does not establish this as our DMA throughput cause. GPU_HOST already copies into the same fine-grained allocation class at ~28.3 GB/s via a different engine/path, so fine-grained memory is not a universal 4 GB/s write limit.
- **Mapping evidence:** importer can coalesce aligned contiguous 4 KiB pages into 2 MiB translations. `MAX_N_MAP_PAGES=256` limits each initial/refill mapping operation, so uncoalesced allocations may initially cover only 1 MiB. Existing Coyote `cThread::printDebug()` exposes the page-fault counter (AVX STAT_REG_1 lane 1); collect deltas around bulk DMA before result polling. Neither actual bulk allocation SG alignment nor fault deltas were logged in accepted runs. Counter CSR29 is tied to zero in the GPU wrapper and is **not** a measured forwarding FIFO occupancy.
- Rechecked all synthetic resident traces using nominal 4 ns cycles: measured median rates **4.141 / 4.128 / 4.108 / 4.108 GB/s** at 4/16/64/128 MiB; warmup medians **4.114 / 4.130 / 4.110 / 4.096 GB/s**. Lack of a warmup improvement argues against one-time mapping/setup explaining the plateau. Tiny admission frames are unsuitable for bandwidth estimates from first-to-last beat timestamps (endpoint quantization can produce apparent >16 GB/s); do not report those as link rates.
- **Topology remains a candidate:** GPUs are NUMA0; benchmark U55C is NUMA1. Cross-root P2P works, but routing/posted-write throughput can differ from host-memory DMA. CPU pinning does not move PCIe endpoints to another root complex. Inspect all upstream links, MPS/MRRS, ACS and routing before any tuning; Linux P2PDMA documentation explains topology-dependent routing. No indiscriminate ACS/IOMMU changes.
- Next discriminating existing-image test: transport-only HPF host→FPGA→HPF host versus HPF host→FPGA→GPU, keeping source, lengths, CSR endpoints and mailbox behavior fixed. Split host destination by NUMA node; compare GPU0/GPU1 and fine/default GPU bulk allocations; record page-fault deltas, mapped small/large-page counts, DMA request/beat counters and exact received-byte parity. No inference during bulk timing. If host loopback is fast, focus on peer routing/mapping; if it also plateaus, focus on shared Coyote/XDMA scheduling. These tests need host/runtime changes only, not new FPGA synthesis.
- Upstream Coyote's local `../docs/source/intro/img/gpu_bw.png` (linked by its Features documentation) shows **GPU→FPGA→GPU ~7.5 GB/s** at large sizes. Different topology, transfer direction and concurrency from our host→FPGA→GPU workload; useful context, not a matched baseline or ceiling. `GPU_BASELINE.pdf`'s rounded ~16 GB/s and excluded HBM stalls still require original timing-scope clarification.

## Verdict availability report — 2026-10-21

- New focused PDF and titled PNG/SVG/PDF figures: `hls4ml/optimize/reports/optimizations/2026-10-21_focused_verdict_availability/`. Reanalyzes the existing preprocessing-v2 campaign; no FPGA builds or new board calls. Prior report folders remain unchanged.
- Headline latency/speedup now end at **CSR14: validated classification result accepted inside FPGA**, including P2P polling/retrieval. **CSR9** remains full-input arrival; **CSR15** is committed verdict/done; host observation is a separate later endpoint. CSR14 does not imply early public-register update or PR admission. Figure 4 includes all three implementations and separate reception lanes; appendix and optimization latency plots use CSR14 too.
- GPU_HOST's previous multi-ms “Final verdict wait” mostly includes unfinished FPGA reception: at 128 MiB−64 B, mean result acceptance **7.520 ms**, last input **10.535 ms**, remaining reception **3.015 ms**. GPU_HOST input backpressure is zero in all 800 synthetic calls. Large-input GPU copy throughput is ~28.3 GB/s (Gen4 x16) versus FPGA reception ~12.8 GB/s (Gen3 x16).
- New result-availability medians at 4 MiB: OPT_6 **1.117914 ms**, GPU_HOST **2.050338 ms**, GPU_P2P **2.844905 ms**; at 128 MiB−64 B: **10.530024 / 7.501984 / 35.478926 ms**. Do not mix these with older host-observed-completion medians. All 12,000 selected calls retain original completion timing and calibration bounds in exported data. Later GPU runtime experiments remain excluded.
- **P2P throughput investigation:** in all 800 accepted synthetic resident GPU_P2P calls, forwarding's last beat (CSR19) trails the last received payload beat (CSR9) by exactly **one ~4 ns cycle**; wrapper input-blocked counter CSR23 is zero. Reception and forwarding each take ~**32.675 ms** for 128 MiB−64 B (~**4.108 GB/s**), versus **10.486 ms / 12.800 GB/s** reception in GPU_HOST. These are different paths: do not describe P2P as receiving at 12.8 GB/s then forwarding at 4.1 GB/s. CSR18/19 measure acceptance by the FPGA output DMA interface, not GPU VRAM arrival. P2P write acknowledgement follows by ~0.72 us; host input readiness follows by ~8–12 us at representative sizes. About 74% of input-active cycles wait for valid data upstream; the user bridge adds no ms-scale drain.
- The exact ~4.1 GB/s transport bottleneck remains unisolated. P2P adds GPU peer writes across PCIe root complexes and Coyote DMA/translation work. The DMA-BUF importer can coalesce aligned contiguous pages, so `huge=false` does **not** prove all GPU mappings stay 4 KiB. Existing-image host-to-FPGA-to-host versus host-to-FPGA-to-GPU transport-only controls, plus actual mapping/fault inspection, are the next discriminating checks; no new FPGA build is justified by these traces alone. Live checks were unavailable from this build-server session (no established SSH host-key trust for GPU host).
- **GPU_BASELINE.pdf transport comparison:** root PDF pages 1–2 imply P2P transfer ~0.266 / 1.054 / 4.214 / 8.418 ms at 4 / 16 / 64 / 128 MiB (printed total × rounded transfer share). Current forwarding medians are 1.013 / 4.064 / 16.335 / 32.675 ms: **3.81–3.88× longer**, ~4.1 GB/s versus baseline ~16 GB/s. Baseline explicitly says transfer excludes card-memory (HBM) stalls; exact counters and inclusion of host→FPGA input are undocumented. Current interval includes elapsed gaps while input streams through FPGA. Do not claim matched replication or assume this scope difference fully explains the gap. Current largest raw input is 128 MiB−64 B; the 64-byte difference is negligible here.

## GPU preprocessing CPU fallback — confirmed 2026-10-21

- **Preprocessing-v2 report refresh PASSED:** `hls4ml/optimize/runs/final_benchmarks_gpu_preprocess_v2_20261021_030038`. All five existing images plus the closing streaming repeat passed admission, timestamp and parity gates. **36,000 accepted measured calls**, including **30,000 primary**; **600 separate GPU profile calls**. Maximum closing-baseline drift **3.8363%**. Strict preprocessing pixel/device-placement validation passed **23 cases**; profiles confirm no CPU Gather fallback.
- New PDFs: `hls4ml/optimize/reports/optimizations/2026-10-21_final_benchmarks_gpu_preprocess_v2/` (**19 pages**) and `focused_hls4ml_checker_gpu_preprocess_v2_20261021_030038/` (**13 pages**). All pages visually reviewed; evidence hashes and ZIP bundles verified. Previous report files are preserved byte-for-byte and folders carry `STALE.md`. These PDFs contain **only the FP32-before-gather fix**, no later graph/compiler/runtime experiments.
- At 4 MiB, host-in-memory medians now: OPT_6 **1.119446 ms**, GPU_HOST **2.054427 ms**, GPU_P2P **2.893948 ms**. At 128 MiB−64 B: **10.531587 / 10.536548 / 35.571203 ms**. Relative to the historical GPU implementation, synthetic GPU_HOST latency falls **24–39%**, GPU_P2P **14–23%**. Historical timings still describe the old implementation; they were not fabricated or invalid measurements.
- Later runtime work is isolated in `hls4ml/optimize/runs/gpu_runtime_investigation_20261021_030038/`; every candidate has source/model hashes, command, environment, parity checks, samples and a journal entry. `hardware_xla_concrete/` is a separate experimental hardware-path campaign. Do not import these results into preprocessing-v2 PDFs without a later explicit report choice. **No FPGA builds were initiated.**

- Accepted October 19 GPU runtimes use `tf.gather` on raw `uint8`. XPlane explicitly records GPU→CPU transfer of the entire raw tensor, CPU `GatherV2`, and CPU→GPU transfer of the 65,536 selected bytes. GPU placement context alone did not prevent this fallback.
- Evidence: `hls4ml/optimize/runs/final_benchmarks_gpu_u55c_20261019/jobs/OPT_7_GPU_HOST/attempt_02/profile/tf_profile/`. In representative ≈128 MiB trial 132: raw GPU→CPU copy **4.75969 ms**, CPU gather **1.68253 ms**, 65,536-byte return **0.00928 ms**. These are diagnostic example timings, not unprofiled medians. GPU-derived indices also return to CPU.
- Previous explanation of all device-span gaps as generic framework overhead was incomplete. Distinguish copies, CPU operations, launch gaps, and profiling synchronization. The CNN itself uses GPU kernels; the preprocessing path was mixed CPU/GPU.
- Authorized report revision `gpu_preprocess_v2`: cast bytes to FP32 on GPU before gathering/padding; preserve exact integer sampling, padding-before-inversion, FP32 weights, batch size one, interfaces and timestamp boundaries. Initial strict-placement/parity probe passed lengths 0, 65, 65536, 65537 and 4194304; the full validation and matched campaign subsequently passed (see above).
- Refresh all five existing hardware variants, no new FPGA builds. Regenerate both full and focused reports into new folders using **only** preprocessing-v2 results. Preserve old artifacts and add stale notices. Later GPU runtime investigations are separate, never automatically promoted into these reports.
- Compare with `GPU_BASELINE.pdf`'s 0.165 ms preprocessing+inference using explicit scopes; exact original model/runtime/sample identities are not established by the PDF. TensorFlow first, then a standard alternative runtime if needed; evidence-based stopping, no forced latency threshold. Record every experiment and keep FP32/parity. User may select a later report revision separately.

## Separate GPU runtime investigations — 2026-10-21

- Evidence: `hls4ml/optimize/runs/gpu_runtime_investigation_20261021_030038/{RESULTS.md,JOURNAL.md,index.json,summary.csv,diagnostics.csv}`. **These changes are not in the preprocessing-v2 reports.** Original FP32 weights and batch one remain fixed.
- CPU-local affinity and TensorFlow thread changes had little benefit. One preprocessing+model graph helped; static-length XLA plus the public ConcreteFunction API reduced host-call-to-completed-scalar medians from **1.600/2.360 ms** to **0.432/0.421 ms** at 4 MiB/largest. R06 passed 15 workload score/verdict checks. Separate joint traces show **0.188/0.196 ms** GPU spans and 23 kernels, without CPU Gather copies. Compilation is excluded from steady-state timing and recorded separately.
- GPU_BASELINE's **0.165 ms** preprocessing+inference is a reference, not an established identical scope: exact checkpoint, four sample identities, runtime and timestamp endpoints are not available. Do not compare host-synchronized calls and device spans as if equivalent.
- Standard ONNX Runtime MIGraphX 1.23.2 + tf2onnx 1.17.0 + ONNX 1.17.0 are isolated under `alternative_deps/`, leaving the report environment unchanged. No custom GPU inference kernels were written.
- **MIGraphX sampling correctness trap:** int64 Gather indices produced 45,053 wrong pixels at the largest input; exported ONNX indices and CPU execution were correct. Exact int32 indices (input sizes <2^31) fixed pixel parity. The precise internal compiler cause is unproven; do not simply loosen logit tolerance. Failed R07/R08 evidence is retained.
- R09 (FP32 cast then Gather with int32 indices) passes two representative sizes, but grows from 0.219 to 0.723 ms. R10 uses standard ONNX **uint8 Gather before cast**, which this backend supports on GPU. It passes all **12 normal workloads ×1,000 measured calls**, medians **0.213–0.249 ms**, max score error **2.20e-5**, exact verdicts. All nodes run in one MIGraphX partition with CPU fallback disabled.
- **R10 is compute-only**, not a GPU_HOST/P2P end-to-end result; no boundary/520-call board admission has been performed for it. A later choice to use R10 needs transport integration and board validation before any new E2E report. It is not silently adopted.
- Experimental TensorFlow XLA board campaign: `hardware_xla_concrete/`. Both GPU variants passed 520-call admission and full measurements, including autonomous P2P delayed publication. CPU64/NUMA1 matches the preprocessing-v2 board campaign (standalone R06 used CPU0–7/NUMA0). Initial closing FPGA repeat was rejected by the clock gate: 12 of 220 calls in a 7.304 s 64 MiB file block mapped the verdict 0.12–1.25 microseconds after host observation. Failed evidence is preserved. The subsequent closing repeat passed timestamp gates; two file workloads then required a matched recheck. **The experimental campaign is now accepted: 24,000 measured calls (18,000 primary), maximum accepted drift 4.079%.** `measurement_manifest.json` records complete accepted evidence/cohorts. Both PDFs remain preprocessing-v2 only. Device2 is left on OPT_1_STREAMING.

## D_I / R_S startup-reset failure — fixed, October 2026

- `ap_ctrl_none` wrapper launched the CNN before host input. Internal `DATAFLOW` padding stages can emit zeros before reading input; the first padder can emit **522 tokens** (2 × 260 + 2).
- Convolution layers consumed padding and advanced state. Coyote driver insertion issued a second reset: control restarted, but some static position/stride counters retained their values. Result: correct input pixels, incorrect logits/verdicts.
- Early padding alone is valid execution; the failure requires the inconsistent reset/restart. Do not assume an empty external FIFO keeps every internal layer idle.
- **Fix:** [wait_for_first_pixel](hls4ml/optimize/build_campaign/hardware/common/frame_start.hpp) before invoking the CNN in [cnn_wrapper.cpp](hls4ml/optimize/build_campaign/hardware/variants/cnn_wrapper.cpp) and [production_inference.hpp](hls4ml/optimize/build_campaign/hardware/common/production_inference.hpp). Observe availability without consuming the pixel; preserve internal streaming, weights and preprocessing.
- Original sequential production naturally waits for preprocessing to finish before invoking the CNN. The streaming fix waits for only the first pixel, preserving overlap.

## Evidence and regression requirements

- RTL reproduced the board mismatch: configuration reset → **20,000 idle cycles** → driver reset → input; [recovery evidence](hls4ml/optimize/runs/frame_start_recovery_20261009_0134).
- Same original R_S image/runtime: **260/260 exact** without the driver reset; **0/260 exact** after restoring the standard reset. [Causal A/B](hls4ml/optimize/runs/board_benchmark_20261008_130137/diagnostics/driver_reset_causal_01/status.json).
- Corrected hardware, standard driver: [D_I **520/520**](hls4ml/optimize/runs/board_benchmark_u55c02_20261009_2345/diagnostics/D_I_admission_01/status.json), [R_S **260/260**](hls4ml/optimize/runs/board_benchmark_u55c02_20261009_2345/diagnostics/R_S_parity_01/status.json); subsequent benchmarks passed.
- Keep startup idle, second reset, input/output stalls and consecutive frames in RTL regression coverage. Require exact-build board parity before benchmark admission.
- Never use the diagnostic reset-suppressed driver for accepted benchmarks. This fix does not establish arbitrary mid-frame reset recovery or prove the cause of the separate historical May investigation.

## Current references

- [D_I / D_N / R_S checkpoint](hls4ml/reproducibility/direct_res256_D_I_D_N_20261010/README.md): self-contained sources, required U55C static platform, measured images and existing results. No new builds or benchmark replay during packaging; fresh package-local execution remains unverified. Active campaign files were preserved.
- **R_S:** streaming reference with original production CNN firmware/weights (63 packaged firmware files verified byte-identical); no D_I conv0 specialization. Streaming wrapper + first-pixel launch guard; production result DMA; host timing only.
- [Root AGENTS.md](AGENTS.md): D_N transport latency/resource floor; D_I optimized checker; exact build pointers.
- [Saved comparison report](hls4ml/optimize/reports/2026-10-09_u55c02/REPORT.md): five variants, timestamp breakdown, figures and archived evidence. Streaming hides most CNN work behind transport; D_I−D_N is not isolated compute time.

## GPU/U55C host — verified 2026-10-18

- Host `hacc-gpu-u55c-01.inf.ethz.ch`: two MI210 GPUs (gfx90a, 64 GiB each), two U55Cs, dual EPYC 7V13, ~512 GiB RAM. Entire machine booked for this campaign.
- GPU0 `0000:03:00.0`, GPU1 `0000:25:00.0`, NUMA0, PCIe Gen4 x16. U55C hdev device1 `0000:a1:00.0`, device2 `0000:81:00.0`, NUMA1, PCIe Gen3 x16. Do not confuse hdev numbering with Coyote numbering: programmed device1 is `/dev/coyote_fpga_0_v0`.
- ROCm `/opt/rocm` is 7.2.0; kernel 6.8.0-138-generic; Vivado 2024.2 available. Kernel headers installed. GPU access requires running outside the filesystem/device sandbox.
- `sudo` requires a TTY and general `sudo true` is denied. Site-approved hdev programming and `/sbin/insmod`, `/sbin/rmmod`, `/usr/bin/dmesg` are passwordless. Use the standard driver with reset enabled.
- **Cross-root P2P verified:** existing hash-verified D_G image, GPU0 + U55C device1, 21 exact transfers (64 B through 128 MiB including header), GPU-produced result read back by FPGA. Evidence: `hls4ml/optimize/runs/gpu_fp32_20261018/preflight/p2p_probe.log`. This establishes basic bidirectional P2P, not yet autonomous polling or asynchronous publication correctness.
- Initial driver build with `make -C` inherited the wrong PWD for include paths; build from the isolated driver's working directory instead. Sources are copied under the campaign; upstream driver is untouched.
- Initial board image: D_G from `direct_stream_20261008_002352`; standard campaign driver loaded. Other devices untouched.
- FP32 campaign: `hls4ml/optimize/runs/gpu_fp32_20261018`. Target iterations OPT_7_GPU_HOST and OPT_8_GPU_P2P. GPU preprocessing/inference uses original FP32 Keras weights; native code is only transport/synchronization. GPU ABI v4 retains registers 0..29 and adds polling CSRs. Autonomous polling still needs the new image and hardware admission.
- **Additional preflight passed:** fine-grained GPU DMA-BUF allocation/export, GPU consumption of FPGA-written input and ordered payload publication passed 100 board trials (`preflight/mailbox_probe.log`). Full autonomous readiness polling is still pending the ABI v4 image.
- ROCm TensorFlow 2.18.1 isolated under campaign `venv/`, using official ROCm 7.2 wheel. FP32 boundary tests passed; 520 software admission calls on the existing 26-case input set passed CPU/GPU parity plus DLPack/publication (`preflight/runtime_validation.json`). This is software admission, not new-image board validation.
- Both GPU builds launched concurrently at **2026-10-18 22:03 CEST**, four implementation threads each. Sessions: `gpu_fp32_host_build`, `gpu_fp32_p2p_build`; independent `_monitor` sessions notify ntfy on terminal status or unexpected worker exit. Start notification accepted. Status and logs live in `jobs/OPT_7_GPU_HOST/` and `jobs/OPT_8_GPU_P2P/`.
- Full-wrapper simulations passed for both variants, including generated-package checks. XSim fails to start inside the sandbox with a Tcl exception; run its validation outside the sandbox. Board remains on preflight D_G until explicit new-image admission; background builders do not program it.

## GPU_HOST timing recovery — 2026-10-19

- OPT_8_GPU_P2P completed successfully; its artifact hashes were reverified on the build host. New-image board admission remains pending.
- OPT_7_GPU_HOST failed routed setup timing: WNS -0.285 ns, TNS -3.567 ns, 45 failing endpoints; hold passed. Worst path is Coyote shell→static AXI-stream boundary `inst_shell/inst_shell_data_cc/genblk1[1].inst_s0_axis_dyn_in/genblk1[2].inst_reg/inst_reg_slice/inst/axisc_register_slice_0/state_reg[0]`, not CNN logic.
- Failed source register placement: `SLICE_X174Y257`; target placement from the passed P2P checkpoint: `SLICE_X168Y197`. Reference boundary's five worst outgoing paths have >=0.667 ns slack. Physical placement evidence is hash-pinned in `hls4ml/optimize/runs/gpu_fp32_20261018/diagnostics/host_timing_20261019/placement_evidence.json`.
- Recovery launched on `hacc-build-02.inf.ethz.ch` at 10:19 CEST, using GPU_HOST's own optimized checkpoint. No source/netlist substitution from P2P and no clock/constraint relaxation. GPU_HOST's validated source manifest is unchanged. Recovery outputs: `jobs/OPT_7_GPU_HOST/recovery/host_20261019_101910/` in the campaign.
- Sessions: `gpu_host_repair_build`, `gpu_host_repair_monitor`; four implementation threads, ntfy topic unchanged. One bounded extra routing pass follows a completed timing failure; tool errors stop and notify. New artifact manifest is sealed only after routed timing and bitstream generation pass.
- Controller snapshot: `recovery_controller_20261019`; maintained entrypoint `hls4ml/optimize/build_campaign/gpu/recover.py`. Top-level job `status.json` follows recovery; original failed status/notification retained under diagnostics. Do not rerun `campaign.py build` over the original build tree to resume this recovery.

## Final FPGA/GPU benchmark campaign — 2026-10-19

- Both GPU images passed implementation. GPU_HOST's first placement recovery completed at 11:29 CEST (70 minutes), WNS +0.022 ns; GPU_P2P WNS +0.014 ns. Artifact hashes reverified on GPU host. OPT_6 combined FIFO1024/aggressive B2 also passed its build.
- Campaign: `hls4ml/optimize/runs/final_benchmarks_gpu_u55c_20261019`; controller `tooling/final_benchmark.py`, state `status.json`. Independent tmux sessions `final_benchmark_run` and `final_benchmark_monitor`; ntfy topic unchanged. Admission precedes accepted timings.
- Host was rebooted since the October 18 preflight. **Device1 is currently unavailable on PCIe:** site inventory still lists `a1:00.0`, but that address is now an AMD dummy function and root port `a0:03.1` is absent. JTAG programming succeeds; standard hdev rescan does not restore the endpoint. Never trust an hdev programming exit code without checking the live PCI vendor/link/device node.
- All final comparisons therefore target **U55C device2, serial XFL13BA4HVZYA, PCIe 0000:81:00.0**, paired with GPU0 `03:00.0`. Device1 attempt failed before admission; no timings accepted. The new pairing requires fresh P2P board validation. CPU64/NUMA1 is used consistently; GPU remains NUMA0.
- Order: OPT_1, OPT_0, OPT_6, GPU_HOST, GPU_P2P, OPT_1 repeat. Exactly 15 existing workloads; 20 warmups + 200 measured calls per workload/scope; resident and warm-cache file-inclusive scopes. GPU model is FP32, FPGA models remain quantized. Old U55C-02 measurements are historical only.
- TensorFlow ROCm device profiling was checked on GPU0: XPlane traces contain GPU kernel timestamps and `kernel_details`. Profiled synchronized phase diagnostics are separate from unprofiled end-to-end trials. Do not interpret Python enqueue durations as GPU execution.
- Site programming helper can return exit 0 after Vivado fails. During OPT_6 admission, retained OPT_0 reported FIFO peak 65536, correctly tripping the 32-entry streaming check. Its programming log contained `Cannot support out-of-date hw_server` and no successful `program_hw_devices` completion. Both prior baseline programming logs were successful. The final controller now rejects Vivado ERROR lines, requires completed programming and the exact board serial before declaring an image ready; a persistent matching Vivado 2024.2 server runs in `final_benchmark_hw_server` on localhost:3121.
- Hardware-server crash recovery: kernel logs showed a `libusb-1.0.so.0` fault; a clean environment alone was insufficient. Read-only target open succeeded with `env -u LD_LIBRARY_PATH /tools/Xilinx/Vivado/2024.2/bin/hw_server -stcp:127.0.0.1:3121 -p0 -e "set jtag-port-filter XFL13BA4HVZYA" -e "set auto-open-ports 0"`. Keep this cable filter and localhost binding; auxiliary GDB ports are disabled. Programming commands also remove the GPU/XRT `LD_LIBRARY_PATH` override. Evidence: campaign `diagnostics/check_jtag.log`, `logs/hw_server_filtered.log`.
- Final GPU runtime uses **HPF host input/result allocations**, matching the FPGA runtime. Original GPU transport used REG pages, a materially different Coyote translation workload; those GPU timings are diagnostic only. Input packing now clears only header/tail padding, like FPGA preparation. GPU model and FPGA images are unchanged; original transport/library snapshots are under `diagnostics/gpu_runtime_v1/`.
- GPU clock calibration brackets now cover at most 20 trials. The initial long-block run failed the existing clock-consistency gate (a 20.95-second block put mapped verdicts several microseconds after host observation). Preserve that evidence; do not weaken the timestamp gate or reinterpret those samples as accepted measurements.
- TensorFlow XPlane timestamps are normalized to a trace origin. Correlate GPU kernels with `/host:CPU` Trace markers named `gpu_preprocessing` / `gpu_inference` and their `step_num`, not Python wall-clock nanoseconds. GPU_HOST profile parsing was recovered offline from all 300 recorded calls/600 markers, including fresh CPU FP32 and clock revalidation (`diagnostics/finalize_existing_profile.py`); no measurement replay. Distinguish summed kernel durations from first-to-last-kernel elapsed spans and synchronized host diagnostic spans.
- All five main measurements and both GPU profiles completed. The closing streaming baseline had at most **0.051% resident median drift**. Two file-inclusive workloads (`real_41278872`, `real_5540996`) initially exceeded the 5% gate through read/copy time; invocation time stayed stable. The predefined two-workload recheck across every variant and another baseline bracket passed with **2.22% and 1.95% drift**, respectively. Original evidence is retained.
- **Subset reruns must preserve allocation capacity:** the FPGA collector normally sizes its input buffer from its workload list. Keep the original **134217728-byte frame / 134217664-byte raw capacity** when selecting fewer workloads; GPU transport already uses that frame capacity. `rechecks/file_01` used a smaller FPGA buffer and is diagnostic only. `rechecks/file_02` pins the original capacity. The offline finalizer replaces only those two file comparisons after their drift gate passes; resident results and GPU profiles are reused.
- **Final campaign PASSED:** `summary.json`, `summary.csv`, `board_admission.json`, and `measurement_manifest.json` in the campaign root. Verified 207 evidence/output files; 180 case/scope/iteration cells, each with 200 measured + 20 warmup calls. Accepted primary measurements: **30,000** across five variants, plus **6,000** closing-baseline measurements and **600** separate GPU diagnostic profile calls. All accepted baseline drift is <5% (maximum 4.73%). Completion ntfy delivered; device2 is left on OPT_1_STREAMING.
- **Autonomous P2P validated on the final pairing:** GPU0 + U55C device2 passed 520-call board admission, including 26 deliberately delayed publications and repeated FPGA polling; no poll engine errors. GPU FP32 scores match CPU references within 1e-4 absolute/relative tolerances and exact verdicts. FPGA quantized logits match exactly. This supersedes the earlier pending-new-image notes above.
- Representative resident medians at 4 MiB: OPT_0 **1.431 ms**, OPT_1 **1.104 ms**, OPT_6 **1.119 ms**, GPU_HOST **2.985 ms**, GPU_P2P **3.771 ms**. Warm-cache file-inclusive medians: **2.556 / 2.256 / 2.243 / 4.185 / 5.007 ms**, respectively. GPU uses FP32; FPGA uses W8A8. OPT_6 wrapper BRAM **339.5→54.5 tiles (−83.95%)**, DSP **1328→648 (−51.20%)**, versus OPT_1; these are wrapper reductions, not whole-device BRAM reductions. Profiled GPU kernel sums/device spans remain separate from unprofiled e2e timings.

- Active preprocessing-v2 campaign: `hls4ml/optimize/runs/final_benchmarks_gpu_preprocess_v2_20261021_030038`; report directories: `final_benchmarks_gpu_preprocess_v2_20261021_030038` and `focused_hls4ml_checker_gpu_preprocess_v2_20261021_030038`. Separate runtime experiments: `hls4ml/optimize/runs/gpu_runtime_investigation_20261021_030038`. Report campaign and separate runtime investigation completed; no new FPGA builds.

## Paper-writing handoff: HBM-resident benchmarks — 2026-11-08

- **Context:** this comparison starts with the complete raw bitstream already in
  FPGA HBM, representing an embedded-core deployment/control model. The host
  emulates preload/control; an embedded CPU and PR enforcement are not implemented.
- **Compared paths:** OPT_10 (`FPGA_HLS4ML`) selectively gathers HBM words and
  streams preprocessed pixels into the quantized OPT_6 CNN. OPT_11 (`GPU_P2P`)
  forwards the full input from HBM to MI210 GPU0, runs R06 XLA + ConcreteFunction
  FP32 inference, and uses autonomous FPGA verdict polling.
- **Measurement scope:** accepted FPGA arm to verdict available at FPGA. File
  reads, HBM preload, compilation/warmup and PR are excluded. This is distinct
  from the earlier host-fed PCIe benchmarks and their file-inclusive latencies.
- **Start here:** [PDF report](hls4ml/optimize/reports/optimizations/2026-11-08_hbm_resident_verdict/hbm_resident_verdict_report.pdf),
  [scope and interpretation](hls4ml/optimize/reports/optimizations/2026-11-08_hbm_resident_verdict/README.md),
  [review and limitations](hls4ml/optimize/reports/optimizations/2026-11-08_hbm_resident_verdict/REVIEW.md).
- **Results and figures:** the same report folder contains `data/statistics.json`,
  `data/trial_events.csv`, `data/evidence_manifest.json`, `figures/` and
  `standalone_figures.zip`. Raw accepted primary trials are in
  `hls4ml/optimize/runs/hbm_benchmark_20261108/opt10_main/` and `opt11_main_02/`;
  use the report's evidence manifest to distinguish accepted and diagnostic runs.
- **Writing caveats:** retain the reported **9.825% cross-program OPT_10
  variation**; its physical cause is unproven. Requested-payload rates are not
  physical HBM-wire bandwidth. OPT_14–16 reader optimizations are follow-up work,
  not measured variants in this report. Detailed findings are recorded below.

## HBM benchmarks completed on GPU host — 2026-11-08

- Campaign: `hls4ml/optimize/runs/hbm_benchmark_20261108/`; maintained runtime,
  collector, controller and report code: `hls4ml/optimize/build_campaign/hbm/`.
  Used existing OPT_10/11 attempt_01 images; **no FPGA build launched**.
- Report: `hls4ml/optimize/reports/optimizations/2026-11-08_hbm_resident_verdict/`.
  Previous reports preserved. Raw/calibrated events, titled PNG/SVG/PDF figures,
  report PDF, iteration log and review evidence are retained.
- Scope: raw input already in HBM; **accepted arm CSR6 → verdict CSR24**, ABI5,
  calibrated ~4 ns tick. Host preload/file I/O/GPU compilation/PR excluded.
  The host emulates embedded-core preload/control; GPU still CPU-dispatched.
- Both variants passed **520-call admission**; exact quantized FPGA scores;
  GPU R06 XLA + ConcreteFunction FP32 agrees with own CPU reference at
  1e-4 absolute + 1e-4 relative tolerance and identical threshold verdict.
  HBM before/after readback, completed transfer counts, external GPU byte
  visibility, delayed publication and 26 stale-generation tests passed.
- **4,800 primary measured calls:** 8 unchanged real + 4 established synthetic
  inputs, 200 each/variant after 20 warmups. Cutoff/boundary/repeat/profile calls
  are separate. Accepted sources: `opt10_main/`, `opt11_main_02/`.
- Initial-program real medians, R1–R8 (ms): FPGA
  **2.679 / 3.074 / 2.919 / 2.885 / 2.935 / 2.808 / 2.695 / 2.750**;
  GPU **1.327 / 2.162 / 3.077 / 4.618 / 5.138 / 6.081 / 7.058 / 8.012**.
  GPU wins R1/R2; FPGA wins R3–R8, with only a small R3 margin.
- **Do not claim the cross-program stability gate passed.** Initial versus
  closing FPGA medians changed by up to **9.825%**. A second 200-call repeat
  without reprogramming changed medians by at most **0.076%**. An old-adapter
  control reproduces the second programmed state, ruling out the new arm guard.
  Three identical-image programming cycles are shown in the report. Variation
  occurs in HBM delivery; the physical clock/PHY/initialization cause is not
  proven. Keep this limitation and programmed-state sensitivity markers.
- Selective reads request 4 MiB for every real input, but initial-program HBM
  return rate is only ~1.4–1.6 GB/s. Sequential full-input HBM→GPU forwarding
  reaches ~7.5 GB/s. These are interface/requested-byte rates, **not physical
  HBM-wire bandwidth**. The old 1.12 ms gather prediction was too optimistic.
- Active links from sysfs: FPGA **81:00.0 = Gen3 ×16 (8 GT/s)**; GPU0
  **03:00.0 = Gen4 ×16 (16 GT/s)**. FPGA NUMA1, GPU NUMA0. This image's actual
  link configuration must be distinguished from generic U55C capability.
- Separate fused GPU profiles after drained P2P delivery: 23 kernels, roughly
  **0.185 ms kernel sum / 0.190 ms device span** (R1/R4/R8). The first integrated
  trace failed with HIP `invalid device function` after profiler restart; the
  hardware had drained. Isolating tracing from mailbox publication recovered
  profiling. `opt11_profiles/` is excluded; `opt11_profiles_02/` is accepted.
- Important adapter details: wait for CSR6 to change after arm before trusting
  repeated-size completion counters. LOCAL_SYNC changes mappings back to
  HOST_ACCESS; **re-offload after verification**, outside timing. Allocate the
  same 128 MiB capacity for every subset; raw GPU capacity is 128 MiB−64 B.
- Driver build must run with cwd at its source root (`PWD` is used for includes).
  GPU-enabled Coyote library must compile with HIP compiler; build_01 used g++
  and failed. Isolated driver source/build is in campaign `software/driver/`.
- Board controller exited and released the shared lease. Device2 serial
  **XFL13BA4HVZYA** is left on **OPT_10**. Do not overwrite original build-job
  metadata to pretend this fork's runtime validation was a build-stage result.

## HBM tiny-read overhead hypothesis — source inspection 2026-11-08

- **Observed motivation:** OPT_10 requests about 65,536 individual 64-byte words
  (4 MiB total) for each real input, reaching roughly 1.4–1.6 GB/s requested-payload
  delivery. Bulk HBM→GPU forwarding reaches about 7.5 GB/s. These measurements
  do not establish a physical HBM bandwidth ceiling.
- **Concrete source evidence:** the accepted OPT_10
  [TLB state machine](hls4ml/optimize/runs/hbm_network_20261107/OPT_10_HBM_GATHER_DSP_B2_RF72_RF288/attempt_01/coyote/hw/hdl/mmu/tlb_fsm.sv)
  processes the normal cached-translation path through `ST_IDLE → ST_MUTEX →
  ST_WAIT_1 → ST_WAIT_2 → ST_CHECK → ST_HIT_LARGE → ST_CALC_LARGE → ST_CARD_SEND`,
  then returns for another request. This FSM serializes request processing;
  cached translations still require multiple cycles. This is hardware work;
  it does not imply a CPU call, PCIe transfer or page fault for every HBM read.
  The file is byte-identical in the OPT_14 attempt_01 Coyote snapshot; SHA256
  `93251f57ae1aa1a75e8417d151976f5cb20ae4378b0497de76c055ac2434feb6`.
- **Hypothesis, not measured stage attribution:** request issue/translation rate
  may be a major bottleneck for one-word reads. An illustrative 8–10-cycle issue
  interval at 250 MHz gives `64 B / (8–10 × 4 ns) = 1.6–2.0 GB/s`, consistent in
  scale with the measured rate before other overhead. This is a code-based
  estimate, not a measured interval or a proven explanation of all latency.
- Other candidate costs are memory-command/first-data latency, queue and clock
  crossings, and credit/completion handling. Some overlap; do not add their
  latencies as if every request waited for the previous request to finish.
  Relevant pinned modules under the same `coyote/hw/hdl/` root include
  `user/req/req_parser.sv`, `user/credits/req_credits_rd.sv` and
  `mmu/mmu_credits_rd.sv`.
- **Refinement of the earlier concurrency hypothesis:** the 32-request window
  holds only 2 KiB of individual-read payload. Increasing it can hide more return
  latency, but cannot remove a serialized issue/translation-rate limit. Coalescing
  and scanning amortize transaction costs across more data beats: 64 B is one
  512-bit beat; 4 KiB is 64 beats. Large logical descriptors are internally split,
  so benefit does not scale indefinitely with descriptor size.
- **How to distinguish causes:** compare accepted-request rate and credit stalls
  across windows, coalescing and scan; inspect response and CNN backpressure/
  starvation; compare with an always-ready sink. Existing results do not yet
  isolate MMU issue rate, return latency and downstream backpressure. Paper text
  must describe this as a supported hypothesis until that evidence is available.

## HBM reader optimization campaign interrupted — 2026-11-08

- **Current status overrides the historical launch notes below:** attempt_01
  jobs were interrupted; their old running statuses are stale. Reader recovery
  now uses available shared permits under the six-build policy recorded above.

- Main-thread end-to-end authorized plan and root:
  `hls4ml/optimize/runs/hbm_reader_optimizations_20261108_032142/PLAN.md`.
  Do not stop at build completion: same conversation automatically proceeds to
  two-round hardware benchmarks, new PDF/figures and review.
- OPT_14_HBM_SCAN, OPT_15_HBM_COALESCED_GATHER, OPT_16_HBM_GATHER_OUTSTANDING128
  registered; three concurrent four-thread jobs under existing buildctl.
  Controller tmux: `buildctl_c9fd3d0f7293`; state in root `builds/`.
- All three initial attempts passed 158-case exact pixel/CNN-score, RTL control,
  tracking/backpressure/reset/always-ready-sink and wiring gates; currently HLS
  project generation/export. No hardware repair used. First5min supervised.
- Additional actual-file C-sim: 60 real/synthetic reader cases passed, all pixels
  and pinned exact CNN scores. Root `preflight/actual_inputs/result.json` pins
  header fingerprint; revalidate if a repair changes that source.
- New source only: `build_campaign/hardware/hbm_readers/` (ABI6) and
  `build_campaign/hbm/readers_*`, `readers_runtime/`. Old source/report manifests
  remain unchanged. No FIFO profiling or CNN/clock changes.
- New collector supports ABI5 controls10/11 and ABI6 readers14/15/16; validates
  latched CSR41 setting, counters and score, preserves successful drain and HBM
  residency;calibration before/after every20-trial block. GPU0 BDF03:00.0 enforced.
- Next: fresh OPT10/11 controls plus scan,groups1/2/4/8,windows32/64/128; two
  independently programmed A/B rounds with reversed order,520-call admission
  per config/session and20warm+200 measured per12workloads. Primary settings
  predeclared scan/group4/window128; retain variability and session identity.
- Never enable TF profiling inside live mailbox process. New report uses dated
  prior isolated GPU diagnostics. Old9.825% reprogram finding remains unproven.
- Bounded main-thread wait helper: `readers_wait.py ROOT --seconds 50`; controller
  completion checks10s and hourly reviews. Hardware has NOT been launched yet.

## CPU-only DRAM benchmark completed — 2026-11-09

- **Paper-agent entrypoint:** `hls4ml/optimize/reports/optimizations/2026-11-09_cpu_dram_preprocess_inference/README.md`; reviewed ten-page PDF `cpu_dram_preprocess_inference_report.pdf`, eight titled PNG/SVG/PDF figures and `standalone_figures.zip` in that folder. Exact tables in `data/statistics.csv`; individual calls in `data/trial_events.csv`.
- Campaign/source/validation: `hls4ml/optimize/runs/cpu_dram_20261109_031305/`. Host `hacc-build-03`, Xeon Gold 6234, CPU2/NUMA2, all worker threads pinned to one logical CPU and numerical libraries set to one thread; SMT sibling34 monitored, not reserved.
- Scope: raw bitstream already in local CPU DRAM → preprocessing → materialized CPU verdict. Before each primary cold call, flush actual zero-copy input lines with CLFLUSHOPT and fences; cache probes/hardware misses support eviction. Model/code warmed; TLBs/instructions not explicitly evicted. File reads, preload, compilation, warmup and cache preparation excluded.
- **Eight real-input pooled median ranges:** original FP32 **2.547–3.103 ms**; frozen QKeras W8A8 **2.694–3.131 ms**. Both use CPU XLA + cached ConcreteFunction. Important: QKeras uses quantized values with **floating CPU kernels**, not native INT8. These are not HLS fixed-point score-equivalence claims.
- 19,200 primary measurements, 33,600 measured calls including diagnostics; eight real + four established synthetic inputs. Two reversed independent process sessions, each20warmups +200measurements/cell, balanced pooling. Cold medians vary by up to **14.1%** across sessions; retain session identity, no proven physical cause. Separate stage diagnostics are not additive fused-total components.
- Native INT8 conversion retained separately under campaign `int8_conversion/`:26/26 verdict agreement, but five clipped scores and maximum absolute score error18.237. Authoritative `review.json` says `diagnostic_only`; no native INT8 latency is claimed. Earlier rounding-sensitive preprocessing attempt was rejected, replaced with exact float32 normalization LUT, and both models passed26-case admission.
- Historical HBM comparison is appendix context only: different host/timing origins/arithmetic. No FPGA/GPU activity or build/network campaign changes were required. See report `REVIEW.md`, machine `data/review.json` and campaign `package_manifest.json` for evidence and provenance.
