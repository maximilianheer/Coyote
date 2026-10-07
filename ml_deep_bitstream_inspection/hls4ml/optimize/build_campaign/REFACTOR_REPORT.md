# Maintained hardware refactor — 2026-10-01

Campaign: `20261001_184524`. Dispatch paused at approximately 22:00 CEST and
resumed at 22:10 CEST. [Live queue](../runs/20261001_184524/STATUS.md).

| Diagnostic | Previous state | Preserved | Replacement |
| --- | --- | --- | --- |
| I | Running, HLS IP export | Attempt 2: full source, logs, artifacts; worker and 8 subprocesses stopped | Attempt 3: fresh build, validation passed, launched first |
| U, N, P, C | Pending; never launched | Attempt 1 queue records | Attempt 2 each: fresh sources/build directories, validation passed, requeued |

Archives: `runs/20261001_184524/attempts/<ID>/attempt_<N>_pre_refactor/`.
Original scripts and process-tree records are preserved under
`maintenance/20261001_220037/`. Archived logs retain their original absolute paths;
the archives are evidence, not resumable build directories.

H16/H8/H4/H2 were left running throughout and reached application implementation.
The resumed queue runs I plus these four jobs. H1/HN/HR/HE/U/N/P/C remain queued
with the original priority and refinement dependencies. The five-slot scheduler
and existing hourly ntfy monitor remain under the same tmux session.

Validation before replacement synthesis:

- All five variants: 11 preprocessing boundary lengths and four wrapper-output
  cases; I/U/C match the pristine CNN, N/P match independent length/checksum results.
- All five host executables compile.
- All five control RTL simulations pass ABI, AXI-Lite backpressure, request/result,
  counter and repeat-trial checks, including disabled instrumentation for U.
- All five tops elaborate against actual Coyote interfaces with an HLS port stub.
- Five queue/isolation tests pass, including pause behavior and full-attempt retry archival.
- All 111 production firmware/weight files match the pre-refactor snapshot;
  `benchmark_control.sv` is byte-for-byte unchanged. Frozen production files were not edited.
- Each replacement has a `source_manifest.json` and hash-bound `validation.json`.

Evidence: [parity/control checks](../runs/20261001_184524/refactor_validation.json),
[top elaboration](../runs/20261001_184524/top_elaboration.json),
[replacement hashes/attempts](../runs/20261001_184524/refactor_resume.json).

**No synthesis-equivalence claim:** new synthesis and routed reports are pending.
Board validation and benchmark execution also remain pending.
