# Build orchestrator

Implemented 2026-11-07. Build-only replacement for the earlier
[cross-host orchestration proposal](../plans/2026-11-07_campaign_orchestration_spec.md).

- One Python controller in tmux; existing build commands run in separate sessions.
- A Markdown plan and CLI registration; JSON files are generated runtime state.
- Up to **5 simultaneous jobs**, including validation and verification stages.
- Check progress immediately and every **30 seconds through minute 5**, then hourly.
- Check process completion every **10 seconds** throughout the run.
- Invoke a background Codex agent for startup/progress, failures and acceptance.
  One agent task at a time; observations accumulate while it is busy. Terminal
  reviews and repairs take priority over coalesced progress reviews.
- Send ntfy updates for starts, failures, repairs, acceptance and final completion
  to `coyote-build-sdeheredia`. No benchmark-host worker or automatic benchmarks.

**Existing fork campaigns are not registered, adopted, edited or restarted.**
No real builds were launched while implementing this controller. Its concurrency
limit applies to its own campaign. Do not start another five-job campaign beside
the existing fork; wait for capacity or use a lower `--jobs` value. Existing
build commands may retain their shared implementation-permit mechanism.

## Failure policy

Try **three plausible fixes after the initial failure**: at most four attempts
per job. Root-cause certainty is not required. Each repair records a hypothesis,
edits a new input copy, runs validation, then retries the build and verification.
Use earlier outcomes to choose the next plausible correction. An explicitly
justified transient retry may keep the source unchanged.

Stop on success. After three unsuccessful corrections, mark `needs_attention`
with the evidence and notify. An agent may stop earlier only when no correction
within the approved scope is possible, explaining the external dependency or
required change of scientific intent. An uncertain diagnosis alone is not a
reason to give up. Malformed/unavailable agent runs get two additional agent
attempts without spending another hardware-repair opportunity.

Model, clock, preprocessing semantics and acceptance requirements remain those
in the plan. Register important files with `--invariant`; their hashes are
checked before stages and at acceptance. Local validation/verification scripts
named directly in the commands are automatically frozen too. Include any helper
modules those scripts import as additional invariants. The agent must not weaken
the acceptance checks or change the registered commands.

## Use

Requires Linux, Python 3.10+, tmux, curl, a working authenticated `codex exec`, and
the build command's normal toolchain. Uses the installed Codex model default.
Preferred host: `hacc-build-03.inf.ethz.ch`; each campaign binds to the host where
it was initialized. Source-only templates and plans are prepared before launch.

From the project directory, for a **new** campaign:

```bash
python3 hls4ml/optimize/orchestration/buildctl.py init \
  hls4ml/optimize/runs/NEW_CAMPAIGN \
  --plan /absolute/path/to/approved-plan.md --jobs 5

python3 hls4ml/optimize/orchestration/buildctl.py add \
  hls4ml/optimize/runs/NEW_CAMPAIGN \
  --id NEW_VARIANT --template /absolute/path/to/prepared-source \
  --validate 'python3 validate.py' \
  --build 'bash build.sh' \
  --verify 'python3 verify.py' \
  --artifact build/bitstreams/cyt_top.bit \
  --artifact verification.json \
  --invariant model.sha256 --invariant constraints/clocks.xdc

python3 hls4ml/optimize/orchestration/buildctl.py start \
  hls4ml/optimize/runs/NEW_CAMPAIGN

python3 hls4ml/optimize/orchestration/buildctl.py status \
  hls4ml/optimize/runs/NEW_CAMPAIGN
```

These are example job-specific filenames, not newly supplied hardware scripts.
Wrap the selected existing preparation/build/validation entrypoints in that
template. Do not point them at a currently running campaign's output directory.
Register dependencies first, then use `--depends JOB_ID` for dependent jobs.
All jobs are registered before starting. `--timeout` sets each stage's limit in
seconds (default 24 hours); agent tasks have separate 15/60 minute limits.

Commands are parsed as argument lists without a shell. Use a readable shell
script when environment setup is necessary. `{work}` expands to the isolated
attempt directory; relative paths also resolve there. Commands must remain in
the foreground, wait for their tools, and write only inside that directory.
Do not use tmux, nohup, detached child sessions or a second scheduler inside a
registered command. Templates cannot contain symlinks. Shared immutable weights
and tool installations can be read by absolute path; generated files must be local.

The three registered commands must provide these gates:

| Stage | Required behavior |
| --- | --- |
| `validate` | Check config, toolchain, model hashes and applicable C-sim/parity/wiring gates; nonzero on failure. |
| `build` | Run the existing foreground HLS/Vivado flow in the owned work directory; propagate its exit code. |
| `verify` | Check the requested bitstream/checkpoints, routed timing, resource limits and required validation evidence; nonzero on failure. |

The controller additionally rejects missing/empty artifacts and hashes all
requested files. A zero build exit code alone does not pass a job. A final agent
review must accept the evidence. The generic controller cannot infer a design's
correct timing constraints or parity requirements: those belong in `verify.py`.

Have `verify.py` write `verification.json` with the design's timing results,
resource counts, validation outcomes and evidence paths. Include it as an
`--artifact`. Its content is included in the build summary and handoff manifest.
Accepted manifests explicitly state `board_validated: false`; later benchmarking
is invoked manually on the booked host, `hacc-gpu-u55c-01`.

## Outputs and control

```text
NEW_CAMPAIGN/
  PLAN.md                       copied plan, checked against its recorded hash
  monitor_state.json            queue, identities, repair budgets, notifications
  BUILD_SUMMARY.md              current/final status and evidence paths
  artifact_manifest.json        accepted images, hashes and verification results
  events.jsonl                  major events and notification IDs
  observations.jsonl            startup/hourly status and recent log tails
  agent_decisions.jsonl          review outcomes and repair hypotheses
  templates/JOB/                registered prepared source copy
  jobs/JOB/attempt_01/input/     input snapshot, retained after launch
  jobs/JOB/attempt_01/work/      validation/build/verification outputs
  jobs/JOB/attempt_02/           first plausible correction, if required
  commands/NNNNN_JOB_STAGE/      log, process identity and durable exit record
  reviews/JOB_NNNNN/             agent prompt, response schema and decision
  monitor.log                   controller's tmux output
```

Each command's `command.log` holds its output. For agent commands it contains
the JSONL transcript from `codex exec`. The controller uses
[Codex noninteractive mode](https://learn.chatgpt.com/docs/non-interactive-mode)
with structured output and workspace-write permissions; it does not disable
sandboxing or approvals globally. Agents receive a fresh task with the durable
plan, history and evidence rather than resuming another fork's conversation.

Use `pause ROOT` to stop new job/agent dispatch while active jobs finish their
stages. `resume ROOT` removes that pause. If the monitor itself exited, use
`start ROOT` again. Build wrappers run independently of the controller; a normal
restart reads their existing identities/results and does not rebuild them.

Use `cancel ROOT` to request termination of this campaign's owned processes.
The monitor must be running to service it. Cancellation signals only a supervisor
whose PID, boot ID and process start time match; that supervisor drains its own
process group. Cancellation is permanent for that campaign. `pause` never kills
jobs. No automatic kill occurs merely because a log is quiet.

A singleton file lock prevents duplicate controllers. A launch interrupted after
its identity/result was recorded is reconciled automatically. The very narrow
crash window before either exists stops with `monitor_error`, rather than guessing
whether a build was started. Inspect the indicated command directory/processes
before repairing state. A host reboot loses the processes; this tmux design is
not a reboot-persistent system service. Filesystem outages or invalid state also
require investigation; the controller must not guess ownership.

Notifications retry with backoff. After completion, the controller allows up to
15 minutes for delivery, then exits with pending messages still in runtime state;
restarting it retries delivery without rebuilding accepted jobs. Delivery is
at-least-once: an interrupted HTTP acknowledgement can produce a duplicate.

## Validation performed

```bash
python3 -m unittest discover -s hls4ml/optimize/orchestration -p 'test_*.py' -v
```

Tests use temporary fake builds and a fake agent. They exercise concurrency,
three repairs, restart reconciliation, gates, pause/cancel and notification
retries without invoking synthesis, programming hardware, contacting ntfy or
touching the fork's builds. Real Codex/Vivado campaign execution remains to be
exercised on the first separately scheduled campaign.
