# Build, benchmark and report orchestration

**Superseded for implementation (2026-11-07):** use the simpler
[build-only orchestrator](../orchestration/README.md). Benchmarking/reporting are
manually invoked; no benchmark-host worker, YAML or database is required. The
current failure policy tries **three plausible fixes**, even when the root cause
is uncertain. The original broader proposal below is retained as design history.

Date: 2026-11-07. Status: design specification; orchestration is not deployed.
Existing builds and the networking investigation retain their current owners.

## 1. User-facing behavior and defaults

One approved campaign plan drives preparation, builds, review, benchmarking,
report generation and report review. Every stage preserves evidence, supports
bounded repair, and sends major progress/final notifications. Routine retries
within the approved scope do not require another confirmation.

| Setting | Default |
| --- | --- |
| Build/controller/report host | hacc-build-03.inf.ethz.ch |
| Benchmark host | hacc-gpu-u55c-01.inf.ethz.ch |
| Concurrent builds | 5, including retries |
| Hardware benchmark concurrency | 1 per physical FPGA; GPU/network reservations also enforced |
| Agent execution | Dedicated background Codex sessions, transcripts and structured results |
| Early build observations | Immediately, then every 30s through elapsed 300s, per attempt |
| Later build review | Every 60 minutes after the early window |
| Terminal-event delivery | Local process exit event immediately; remote ingestion target within 10s while services/storage are healthy |
| Notification topic | coyote-build-sdeheredia |
| Benchmark start | All required builds for its declared comparison group accepted |
| Final report | PDF plus titled standalone figures and machine-readable data/evidence |

The controller records every early observation. A build agent supervises the
first five minutes, receiving those observations, then returns until an hourly
review or exceptional event. Agent execution can take longer than a 30s tick;
observations continue and are coalesced into its active task, without overlapping
agent turns or an accumulating queue of obsolete checks. Due hourly checks across
jobs are batched. Every new attempt restarts the five-minute window.
During early supervision the agent reads a controller-maintained observation
inbox using bounded waits. CLI sessions do not require live prompt injection;
after an invocation ends, further work resumes its explicit session ID. Urgent
events are persisted immediately even while a tool call is still completing.

Process monitoring continues between reviews. An exited process, fatal error or
host/worker failure is not deferred until the next hourly review. Completion
starts an agent check at the next available dispatch opportunity; an already
busy agent receives a pending event rather than a concurrent conflicting turn.

## 2. Architecture and persistence

Use a small Python controller and one persistent worker service per host. Agents
handle interpretation, repairs and review; deterministic code owns dispatch,
resource reservations, state transitions, artifact gates and notifications.

The workspace is NFS4. Store controller/worker SQLite databases on verified local
disk, by default `/var/tmp/coyote-orchestrator-<uid>/`, mode0700. Never place a
live SQLite WAL database on the shared workspace. Export campaign snapshots,
events, manifests, logs and artifacts to a shared campaign directory.

Use per-host command/event mailboxes on the shared filesystem:

- Controller writes uniquely identified command files using same-directory
  temporary-file creation, flush/fsync and atomic rename. Workers consume only
  commands addressed to their exact configured hostname and campaign generation.
- Workers register each command ID in their local database before launching it.
  Attempt IDs identify separately supervised process units; replay queries the
  existing unit/result instead of launching a second copy.
- Workers persist exit/results locally before publishing immutable event files.
  Controller ingests events idempotently and acknowledges them. Unacknowledged
  events and commands survive restart and storage outages.
- One controller on the designated build host owns campaign transitions. A local
  singleton lock prevents two instances. No automatic cross-host controller
  failover in v1; a peer watchdog reports its absence.
- Agent responses carry campaign revision, attempt ID and expected state version.
  Stale proposals are rejected. A repair creates a new attempt with its own source
  snapshot; it never edits the source snapshot of a running or measured attempt.
- Workers heartbeat every 15s; reconcile every 10s. After 90s without a heartbeat,
  mark connectivity/ownership uncertain and notify. Confirm local process state
  before retrying; a lost connection does not prove a failed build.

Run services and jobs in separately supervised user systemd units so an agent or
controller exit does not kill a build. Enable and verify persistence after logout
and reboot through the site-supported service setup. On this host, inspection
found `Linger=no` and a degraded user manager; persistent operation is a setup
gate, not an existing guarantee. A tmux-only development mode must be labelled
session-bound and is not accepted as unattended production deployment.

Each host owns the execution privileges needed for its registered worker
commands. Agents use workspace-scoped execution and existing approval policies;
hardware programming goes through the known site helper. No blanket sandbox
bypass or global passwordless sudo. Verify noninteractive auth, permissions,
toolchain, storage, device access and notifications before campaign activation.

## 3. Campaign contract and interfaces

Create a readable PLAN.md plus a schema-validated campaign.yaml. Store the approved
revision and its hash; changing workloads, metrics or model/build intent creates
a new revision rather than silently altering an active comparison.

Required manifest sections:

| Section | Contents |
| --- | --- |
| Identity | Campaign ID, revision, source/config/model/runtime hashes, approval scope |
| Hosts/resources | Exact hosts, build limit, CPU/thread limits, FPGA serial/BDF, GPU identity, required network path |
| Builds | Iteration, preparation/build adapter, dependencies, output contracts, required timing/parity/resource gates |
| Benchmarks | Comparison groups, selected images, admission, cases, warmups/trials, execution order, metrics and timing endpoints |
| Reports | Figures, titles/legends/axes, units, baselines, exclusions, formats and destination |
| Recovery | Retry limits, stage timeouts, allowed repair classes, invariants and stop conditions |
| Notifications | Major events, topic, optional hourly digest |

All commands are registered adapters invoked as argument arrays, not free-form
shell assembled from agent text. The report contract must specify measurement
scope, aggregation and speedup direction before the run. Reuse existing local
scripts via adapters, explicitly replacing their historical hardcoded variants,
hosts, board indices and timing semantics with the campaign contract.

Provide a compact CLI:

```
campaign validate PLAN
campaign start PLAN
campaign status ID
campaign events ID
campaign adopt ID --attempt-manifest PATH
campaign pause ID
campaign resume ID
campaign cancel ID
campaign retry ID --job JOB --repair-record PATH
```

Validate is read-only. Start executes the authorized plan after preflight. Pause
stops new dispatch while active jobs finish; cancel explicitly stops owned process
groups, drains hardware where possible and records cancellation. Resume reconciles
state before dispatch. Retry obeys the same budgets and evidence requirements.
Adopt requires an explicit ownership handoff from the current supervisor and exact
source/process/artifact identity. Default integration with ongoing fork work is
observation only; never compete with its scheduler or board owner.

State transitions:

```
planned -> preflight -> building -> build_review -> benchmark_ready
benchmark_ready -> benchmarking -> data_review -> reporting -> report_review
report_review -> complete | complete_with_findings | incomplete
```

Individual jobs may enter repair_pending, retry_queued, waiting_dependency,
waiting_resource, blocked or cancelled. Preserve the reason and evidence. A
build process exit is not build acceptance; required artifacts/timing/parity
must pass. Missing required builds block their comparison group. Independent
groups proceed; the final campaign report documents missing comparisons.

## 4. Agent dispatch and build supervision

Use installed Codex CLI noninteractive mode. Each campaign has persistent build
and benchmark sessions, with report-generation work on the build host and a fresh
report-review session. Launch with JSONL events, schema-constrained final results
and explicit working directories. Resume by recorded session ID, never `--last`.
Keep authentication local to each host; verify it before launch. Model selection
inherits the configured Codex default unless the campaign explicitly sets it.

Each agent receives: approved plan/hash, current state, new events, relevant log
tails, artifact paths, prior repairs and remaining budgets. Final structured
responses contain action, evidence paths/hashes, diagnosis, proposed changes,
required tests and rerun scope. Validate these before committing transitions.
Use a 15-minute deadline for a check/triage task, 60 minutes for a repair task,
and 60 minutes for each report-generation/review task. Benchmark supervision uses
the sum of the manifest's explicit stage deadlines plus 15 minutes. Larger
approved campaigns may override these defaults in their manifest.

The build agent checks early startup, then hourly: source identity, process/unit
health, tool stage, recent errors, disk/memory, output growth and stage duration.
Quiet logs alone do not trigger termination. Stage deadlines come from the plan.
An hourly inspection may classify a run as slow/needs diagnosis without killing it.

At every terminal build event, verify exit status, logs, routed timing, artifacts
and hashes. Publish BUILD_STATUS.md plus status.json with variant, attempt,
outcome, elapsed time, resource/timing summary, repair decision, and exact paths
to image, driver requirements, logs, checkpoints and manifests. Failure events
also produce a report. Notify on terminal results and any queued repair.

When all required images in a comparison group are accepted, emit a durable
benchmark-ready event. The benchmark-host worker resumes its agent with a sealed
handoff manifest. Reverify all referenced hashes on that host before programming.
Do not wake it repeatedly for the same accepted group revision.

## 5. Benchmarking, review and repairs

The benchmark agent holds exclusive reservations for the physical FPGA, selected
GPU and relevant sender resources across programming/admission/measurements.
Locks are host-local and shared across campaigns, keyed by stable hardware
identity. Retain compatibility with existing board leases during migration;
active forks must hand off ownership before managed benchmarking starts.

Run preflight, program/verify identity, admission, warmups, measurements and
closing controls consecutively. Monitor foreground runners continuously; no
hour-long sleep between short benchmarks. Watchdogs and timeouts still apply.
Collect diagnostics outside timing intervals. Existing artifact, timestamp,
parity and programming-log gates are retained through adapters.

Repair defaults, configurable in the approved plan:

| Failure class | Automatic action / bound |
| --- | --- |
| Build infrastructure or implementation defect | Diagnose and repair; at most two additional attempts per build job |
| Benchmark process/environment failure before valid data | Restore known working state and rerun affected stage; at most two additional attempts |
| Proven measurement defect in collected data | One corrected rerun per affected comparison cohort, after regression test/small confirmation |
| Analysis/plot/rendering defect with intact raw data | Correct analysis/figures and regenerate; at most two repair cycles, no hardware rerun |
| Codex transient failure or malformed response | Retry dispatch twice with backoff; reconcile side effects before replay |
| Repeated identical failure without new evidence/change | Stop the affected job and publish diagnosis |
| Unknown cause or exhausted repair budget | Preserve evidence, mark incomplete/with findings and notify |

Global default: at most 12 automatic repair cycles per campaign; healthy jobs
continue when another job exhausts its allowance. Transport outages and ntfy
delivery retries use their own backoff and do not consume hardware repair budgets.
Agent tasks and jobs have explicit deadlines; agent timeouts do not kill supervised
builds. Persistent agent-auth failures notify and await repair, avoiding busy loops.

Allowed fixes preserve model identity, preprocessing semantics, timing definitions,
clock constraints, correctness tolerances and benchmark workload. Compilation,
transport integration, bounded timing recovery and runtime measurement corrections
are in scope when evidence supports them. Changing scientific intent or relaxing
a gate requires a plan revision. Keep a repair journal: symptom, root cause,
patch/hash, test evidence, impacted measurements and retry outcome.

Apply the user's report policy literally:

- Unexpected latency, unexplained variance or a >5% drift flag alone is not a
  reason to rerun. Report it with the relevant limitations and stop investigating
  automatically once the initial diagnostic review finds no clear cause.
- A rerun requires both demonstrably invalid/incomplete measurements and a clear,
  evidenced cause with a specific correction. Preserve invalid raw evidence.
- Recompute from raw data first. Wrong plot units, labels or formulas require
  regeneration, not new measurements.
- For a measurement rerun, replace the complete affected comparison cohort across
  dependent variants/controls. Do not choose favorable trials or mix inconsistent
  runtime/image versions. A firmware repair returns the affected image to build
  review and fresh admission before any new measurement is accepted.
- Hard failures such as wrong image, parity mismatch or missing required timestamps
  exclude those rows from validated performance claims. Still produce a final
  report showing the failure and unavailable comparisons when unresolved.

Older acceptance scripts require drift rechecks or fail on unexplained drift.
Do not modify archived scripts/results. New adapters separate hard validity gates
from quality findings, honoring this policy rather than inheriting rerun-until-pass.

## 6. Reports, notifications and completion

The benchmark agent seals raw evidence and submits report-ready work. Generate
the report on the build host so report rendering does not contend with measured
GPU/CPU workloads. Use the campaign's planned builder/figure specification.
Write to a new ISO-dated campaign report folder; corrections use revision
subdirectories, retaining previous PDFs and raw evidence.

Review automatically and visually using a fresh read-only agent task:

- Reconcile plotted values with exported data, sample counts and accepted manifests.
- Check units, timestamp scopes, counter wrapping/validity, speedup direction,
  baseline selection, overlapping intervals and resource denominators.
- Render every PDF page and inspect titles, legends, axes, clipping and missing
  panels. Reconcile claims with measurements, including uncertain outcomes.
- Emit review.json and REVIEW.md listing passes/findings and classification:
  presentation defect, derived-data defect, proven measurement defect, or unexplained
  observation. The controller applies the repair policy above.

Major ntfy events: campaign activation; builds launched; each build completion or
failure; repair/retry; comparison group ready; benchmark start/completion/failure;
report generated; review result; blocked condition; final completion.
Routine 30s observations stay in logs. Hourly status remains in status reports;
hourly ntfy digests are off by default.

Persist notifications in an outbox, with event IDs and successful-delivery records.
Retry after 10s, 30s, 2m, then every 15m; delayed messages include occurrence time.
Suppress known duplicates; an ambiguous lost HTTP acknowledgement may cause a
duplicate delivery, so retain stable event IDs. Notification failure never causes
a build/benchmark rerun. Report artifact completion separately from notification
delivery; keep delivery pending until acknowledged. A peer watchdog can report
controller failure but does not take over hardware or scheduling ownership.

Final notification contains outcome, passed/failed counts, principal results or
limitations, PDF/figure paths, review path and campaign root. Local paths include
hostname; only include clickable HTTPS links if a real serving endpoint exists.
Do not imply an internal filesystem path is a publicly accessible download.

## 7. Implementation and acceptance

Implement new maintained modules under `hls4ml/optimize/orchestration/` with
adapters around existing build_campaign workers, monitors, identity/parity gates
and report builders. Preserve archived campaign tooling. Campaign outputs live
under the existing dated runs/reports roots.

Deliver in three stages:

1. Controller/worker state, local databases, shared mailboxes, five-slot scheduler,
   event delivery, notifications, pause/resume/cancel, fake-job end-to-end tests.
2. Codex dispatch, bounded repairs, build reviews and exact artifact handoff;
   observation-only attachment to current builds while another fork owns them.
3. Benchmark resource leases/adapters, report/review pipeline, one explicitly
   selected pilot campaign, then normal campaign use.

Acceptance tests:

- Virtual-clock test of all early checks, hourly checks and immediate exit events;
  slow agents coalesce observations without lost terminal outcomes.
- Five builds start; the sixth waits; crashes/retries release capacity correctly.
- Kill/restart controller, worker and agent; confirm no duplicate launches,
  no lost results and no benchmark starts on ambiguous artifact/ownership state.
- Interrupt shared storage; replay spooled events after recovery without duplicate
  hardware work. Reject stale generations, corrupt manifests and partial handoffs.
- Reject wrong host/board/GPU and prevent competing campaigns from programming
  the same board or measuring on the same reserved GPU.
- Inject fixable build error, parity failure, wrong timing units, missing timestamps
  and unexplained variance. Verify the precise retry/exclusion/report behavior.
- Visual review catches a clipped figure; regeneration uses existing data.
- Fail ntfy delivery; verify retry and final pending/delivered status without
  rerunning completed jobs.
- Demonstrate logout/reboot persistence and agent authentication on both hosts
  before claiming unattended operation. A hardware pilot uses available validated
  images and a small approved workload, with full provenance.

## References and inspected state

- Existing iteration_monitor.py: ntfy watchdog and terminal status detection.
- Existing benchmark_handoff.py / benchmark_queue.py: artifact admission and board
  ownership; currently tied to historical variants/hosts.
- Existing accept_benchmark.py / finalize_benchmark.py: sealed data and matched
  cohorts; adapt quality policy as described above.
- Local CLI: codex-cli 0.167.0; exec JSONL, output schemas and explicit session
  resume available. CLI reports ChatGPT authentication on the build host; actual
  unattended execution and benchmark-host authentication remain setup checks.
- [Official noninteractive Codex documentation](https://learn.chatgpt.com/docs/non-interactive-mode):
  structured results, JSON events, saved authentication and session resume.
- [Official App Server documentation](https://learn.chatgpt.com/docs/app-server):
  optional future integration for application-visible conversations; not required
  for the selected background-agent implementation.
