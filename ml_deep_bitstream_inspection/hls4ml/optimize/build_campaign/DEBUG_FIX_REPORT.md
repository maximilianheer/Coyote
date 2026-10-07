# Debug-bridge fix and clean restart — 2026-10-02

Campaign: `20261001_184524`. [Live queue](../runs/20261001_184524/STATUS.md).

- Stopped **I, H1, U, N, P** and their complete trees: **69 processes**.
- Preserved all previous source/build directories under
  `attempts/<ID>/attempt_<N>_before_ila/`, including the failed H16/H8/H4/H2
  attempts and C's prepared attempt. Pending refinement queue records were also saved.
- All 13 jobs requeued with the original priorities and refinement dependencies.
  Prepared fresh coarse hello-world and diagnostic attempts; HN/HR/HE are prepared
  once their dependencies establish suitable floorplans. No previous generated IP
  or implementation checkpoints are reused in replacement builds.

Applied changes:

1. Every variant uses the same **one-bit, 1024-sample ILA**, clocked by `aclk` and
   observing accepted input beats. It supplies a debug core for Coyote's mandatory
   bridge, addressing the observed `Chipscope 16-320` checkpoint-reopen failure.
   Its cost must be included in resource totals and minimum-bitstream measurements.
2. Timing validation now accepts Vivado 2024.2's complete success sentence and
   rejects failure, contradictory and missing evidence.
3. With explicit user approval, hello-world's campaign-only `perf_local.sv`
   restores direct TVALID propagation and removes the frozen nodbg source's RO.
   The add-one datapath, buffering and interfaces are preserved. Frozen datasets,
   checker preprocessing, CNN weights, register ABI and measurement boundaries
   were not changed.

Validation before restarting:

- Seven Python regression tests passed; the parser also accepts the four real
  H-build timing reports that previously would have been rejected.
- All five diagnostics passed host compilation, preprocessing/output parity,
  control RTL/ABI simulation and top elaboration with an ILA port stub.
- Vivado accepted the actual ILA configuration and generated its synthesis target.
- Hello-world simulation passed 64 valid/ready combinations, metadata checks and
  all 16 add-one lanes. Register slices were transparent test models; their unchanged
  implementation is built by Coyote.
- Source hashes and attempt mappings: [debug_fix_resume.json](../runs/20261001_184524/debug_fix_resume.json).
  Detailed stop records and IP/hello tests: `maintenance/20261002_010028/`.

**Full-design resolution remains pending:** new routed checkpoints must reopen and
bitstream generation must succeed. Timing, resource results and hardware validation
must be checked on the replacement builds. Hourly ntfy and issue/completion alerts
continue in the existing tmux session.
