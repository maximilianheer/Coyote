#!/usr/bin/env python3
"""Small build queue and agent monitor. Registration never adopts running jobs."""

import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import time

from runner import alive, group_alive, identity, save

HERE = Path(__file__).resolve().parent
TERMINAL = {'passed', 'needs_attention', 'blocked', 'cancelled'}
TOPIC = 'https://ntfy.sh/coyote-build-sdeheredia'
MAX_REPAIRS = 3
LIVE_RUNNERS = {}
DECISION_SCHEMA = {
    'type': 'object',
    'properties': {
        'action': {'type': 'string', 'enum': ['accept', 'retry', 'continue', 'needs_attention']},
        'explanation': {'type': 'string'},
        'hypothesis': {'type': 'string'},
    },
    'required': ['action', 'explanation', 'hypothesis'],
    'additionalProperties': False,
}


def read(path, default=None):
    if not path.exists():
        return {} if default is None else default
    return json.loads(path.read_text())


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def tree_hashes(directory):
    if any(path.is_symlink() for path in directory.rglob('*')):
        raise ValueError('Input snapshots must not contain symlinks')
    return {str(path.relative_to(directory)): digest(path)
            for path in sorted(directory.rglob('*')) if path.is_file()}


def contained(directory, relative):
    path = (directory / relative).resolve()
    if not path.is_relative_to(directory.resolve()):
        raise ValueError(f'Path escapes owned directory: {relative}')
    return path


def copy_inputs(source, target):
    # A writable symlink could let the agent/build mutate another campaign.
    if any(path.is_symlink() for path in source.rglob('*')):
        raise ValueError('Prepared inputs must not contain symlinks')
    shutil.copytree(source, target)


@contextmanager
def locked(root):
    with (root / 'monitor.lock').open('a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def event(root, state, key, message):
    if key in state['notifications']:
        return
    record = {'id': key, 'message': message, 'at': time.time(), 'tries': 0,
              'delivered': False, 'next_try': 0}
    state['notifications'][key] = record
    with (root / 'events.jsonl').open('a') as output:
        output.write(json.dumps(record) + '\n')


def notify_due(root, state, now, sender=None):
    for record in state['notifications'].values():
        if record['delivered'] or now < record['next_try']:
            continue
        if sender is None:
            try:
                result = subprocess.run(
                    ['curl', '-fsS', '--connect-timeout', '3', '--max-time', '5',
                     '--data-binary', record['message'], TOPIC],
                    capture_output=True, text=True)
                success = result.returncode == 0
            except OSError:
                success = False
        else:
            success = sender(record)
        record['tries'] += 1
        record['delivered'] = success
        record['next_try'] = now + [10, 30, 120, 900][min(record['tries'] - 1, 3)]
        # Persist acknowledgement before attempting the next notification.
        save(root / 'monitor_state.json', state)
        break  # A notification outage must not stall monitoring all five jobs.


def launch(root, state, command, cwd, timeout, label, owner):
    directory = root / 'commands' / f'{state["sequence"]:05d}_{label}'
    state['sequence'] += 1
    directory.mkdir(parents=True)
    record = {'directory': str(directory), 'created_at': time.time()}
    owner['command'] = record
    # Write intent first. Ambiguous launch windows are never replayed blindly.
    state['launch_intent'] = record
    save(root / 'monitor_state.json', state)
    try:
        with (directory / 'supervisor.log').open('ab') as log:
            child = subprocess.Popen(
                [sys.executable, str(HERE / 'runner.py'), str(directory), str(cwd),
                 str(timeout), *command], stdout=log, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL, start_new_session=True)
        record.update(identity=identity(child.pid))
        LIVE_RUNNERS[child.pid] = child
    except OSError as error:
        save(directory / 'exit.json', {'returncode': -1, 'error': str(error)})
    state.pop('launch_intent', None)
    return record


def reap_runners():
    for pid, child in list(LIVE_RUNNERS.items()):
        if child.poll() is not None:
            del LIVE_RUNNERS[pid]


def outcome(record, now):
    directory = Path(record['directory'])
    process = record.get('identity') or read(directory / 'identity.json')
    if process and (alive(process) or group_alive(process['pid'])):
        return None
    result = read(directory / 'exit.json')
    if result:
        return result
    if now - record['created_at'] < 30:
        return None
    return {'returncode': -1, 'error': 'Runner disappeared or launch state is uncertain'}


def arguments(template, work):
    # Only the explicitly registered placeholder is substituted; braces in
    # Python/Tcl snippets remain literal. No shell=True or eval of agent output.
    return [argument.replace('{work}', str(work)) for argument in template]


def observe(root, job, now):
    attempt = job['attempts'][-1]
    if now < attempt['next_check']:
        return False
    elapsed = now - attempt['started_at']
    work = Path(attempt['path']) / 'work'
    try:
        status = read(work / 'status.json')
    except (OSError, ValueError) as error:
        # A worker may replace its status while we read it. Preserve the clue,
        # but never declare a live tool failed because a status read raced.
        status = {'read_error': str(error)}
    observation = {'at': now, 'elapsed': elapsed, 'job': job['id'],
                   'phase': job['phase'], 'worker_status': status,
                   'free_disk_bytes': shutil.disk_usage(root).free}
    logfile = Path(job['command']['directory']) / 'command.log'
    if logfile.exists():
        with logfile.open('rb') as source:
            source.seek(max(0, logfile.stat().st_size - 4000))
            observation['log_tail'] = source.read().decode(errors='replace')
        observation['log_bytes'] = logfile.stat().st_size
    with (root / 'observations.jsonl').open('a') as output:
        output.write(json.dumps(observation) + '\n')
    interval = 30 if elapsed < 300 else 3600
    attempt['next_check'] = now + interval
    return True


def new_attempt(root, job, inputs, now):
    number = len(job['attempts']) + 1
    path = root / 'jobs' / job['id'] / f'attempt_{number:02d}'
    path.mkdir(parents=True)
    copy_inputs(inputs, path / 'input')
    attempt = {'number': number, 'path': str(path), 'started_at': now,
               'next_check': now, 'hypothesis': '', 'status': 'pending'}
    job['attempts'].append(attempt)
    return attempt


def verify_inputs(job, inputs):
    for name, expected in job['invariants'].items():
        if digest(contained(inputs, name)) != expected:
            raise ValueError(f'Repair changed invariant: {name}')


def start_stage(root, state, job, phase):
    attempt = job['attempts'][-1]
    path = Path(attempt['path'])
    work = path / 'work'
    if phase == 'validate':
        verify_inputs(job, path / 'input')
        save(path / 'input_manifest.json', tree_hashes(path / 'input'))
        copy_inputs(path / 'input', work)
    verify_inputs(job, work)
    command = arguments(job[phase], work)
    attempt['status'] = phase
    job['phase'] = phase
    launch(root, state, command, work, job['timeout'], job['id'] + '_' + phase, job)


def sealed_artifacts(job):
    attempt = Path(job['attempts'][-1]['path'])
    if tree_hashes(attempt / 'input') != read(attempt / 'input_manifest.json'):
        raise ValueError('Input snapshot changed after launch')
    work = attempt / 'work'
    verify_inputs(job, work)
    files = {}
    for name in job['artifacts']:
        path = contained(work, name)
        if not path.is_file() or path.stat().st_size == 0:
            raise ValueError('Missing or empty artifact: ' + name)
        files[name] = {'path': str(path), 'sha256': digest(path), 'bytes': path.stat().st_size}
    return {'files': files, 'board_validated': False,
            'verification': read(work / 'verification.json'),
            'input_manifest_sha256': digest(attempt / 'input_manifest.json')}


def finish_failure(root, state, job, reason):
    attempt = job['attempts'][-1]
    attempt.update(status='failed', error=reason)
    job['error'] = reason
    job['phase'] = 'repair_pending' if job['repairs'] < MAX_REPAIRS else 'needs_attention'
    event(root, state, f'{job["id"]}:{attempt["number"]}:failed',
          f'Build {job["id"]} attempt {attempt["number"]} failed: {reason}. {attempt["path"]}')


def agent_prompt(root, state, job, purpose, candidate):
    return f'''You are the build-only campaign agent. Read {root / 'PLAN.md'}.
Task: {purpose}. Job: {job['id']}. State: {root / 'monitor_state.json'}.
Owned editable directory for this task: {candidate}.
Read attempt logs and events in {root}; other campaigns are read-only.
Never launch builds yourself, signal other processes, program boards, run
benchmarks, change machine settings or modify prior attempts. The controller
owns build dispatch and retries. Preserve model, clock, precision, correctness
tolerances and the plan's scientific intent. Invariants: {job['invariants']}.
For a repair, implement ONE plausible fix in the owned input directory. You do
not need certainty about the root cause. Explain the hypothesis and change;
try a different plausible correction informed by earlier outcomes. There are
THREE repair opportunities after the initial build, not two. Do not give up
just because a cause is uncertain; only report needs_attention early when no
in-scope correction is possible (e.g. external access or required intent change).
The controller runs the registered validation before any retry. Do not change
registered commands or acceptance gates to obtain a pass. Do not run synthesis.
For a transient failure, an unchanged retry is allowed only when its hypothesis
explains why another attempt is plausible. Record what changed in conditions.
For success review, inspect verification logs, artifact_manifest.json, timing
and correctness evidence; accept only when the registered gates are satisfied.
For startup/hourly checks, inspect progress and report continue or concerns.
Read observations.jsonl for the 30-second startup observations. Reviews are
coalesced while an agent is busy; do not sleep waiting for new observations.
Quiet logs alone are not failure. Return the requested JSON decision with
action, explanation and hypothesis. Never fabricate test results.
Current job details: {json.dumps(job, indent=2)}
'''


def start_agent(root, state, job, purpose, reuse=False):
    if purpose == 'repair' and not reuse:
        previous = Path(job['attempts'][-1]['path']) / 'input'
        attempt = new_attempt(root, job, previous, time.time())
        job['repairs'] += 1
        candidate = Path(attempt['path']) / 'input'
    elif purpose == 'repair':
        candidate = Path(job['attempts'][-1]['path']) / 'input'
    review = root / 'reviews' / f'{job["id"]}_{state["sequence"]:05d}'
    review.mkdir(parents=True)
    if purpose != 'repair':
        candidate = review
    save(review / 'schema.json', DECISION_SCHEMA)
    prompt = agent_prompt(root, state, job, purpose, candidate)
    prompt_path = review / 'prompt.txt'
    prompt_path.write_text(prompt)
    decision = review / 'decision.json'
    # Each task has a fresh bounded context assembled from durable campaign
    # evidence. It never resumes the human's or another fork's conversation.
    command = [state['codex'], 'exec', '--json', '--sandbox', 'workspace-write',
               '-c', 'approval_policy="never"', '--skip-git-repo-check',
               '--cd', str(candidate), '--output-schema', str(review / 'schema.json'),
               '--output-last-message', str(decision), prompt]
    state['agent'] = {'job': job['id'], 'purpose': purpose, 'decision': str(decision),
                      'candidate': str(candidate)}
    job['review_pending'] = False
    if purpose == 'repair':
        job['phase'] = 'repairing'
    launch(root, state, command, candidate, 3600 if purpose == 'repair' else 900,
           job['id'] + '_agent', state['agent'])


def complete_agent(root, state, result):
    task = state.pop('agent')
    job = state['jobs'][task['job']]
    try:
        decision = read(Path(task['decision']))
        if result['returncode'] or set(decision) != set(DECISION_SCHEMA['required']):
            raise ValueError('Agent failed or returned malformed decision')
        if not all(isinstance(value, str) for value in decision.values()):
            raise ValueError('Agent decision fields must be strings')
        if decision['action'] not in DECISION_SCHEMA['properties']['action']['enum']:
            raise ValueError('Unknown agent action')
        record = dict(task=task['purpose'], job=job['id'], at=time.time(), **decision)
        with (root / 'agent_decisions.jsonl').open('a') as output:
            output.write(json.dumps(record) + '\n')
        if task['purpose'] == 'repair':
            if decision['action'] == 'needs_attention' and decision['explanation'].strip():
                job.update(phase='needs_attention', error=decision['explanation'])
                event(root, state, f'{job["id"]}:cannot_repair',
                      f'{job["id"]}: no in-scope repair available: {decision["explanation"]}. {root}')
            else:
                if decision['action'] != 'retry' or not decision['hypothesis'].strip():
                    raise ValueError('A repair requires retry and a recorded hypothesis')
                job['attempts'][-1]['hypothesis'] = decision['hypothesis']
                job['phase'] = 'retry_ready'
                event(root, state, f'{job["id"]}:repair:{job["repairs"]}',
                      f'{job["id"]}: plausible repair {job["repairs"]}/3 ready: '
                      f'{decision["hypothesis"]}. {root}')
        elif task['purpose'] == 'terminal':
            if decision['action'] == 'accept':
                try:
                    artifacts = sealed_artifacts(job)
                    expected = read(Path(job['attempts'][-1]['path']) / 'artifact_manifest.json')
                except (OSError, ValueError) as error:
                    finish_failure(root, state, job, str(error))
                    return
                if artifacts != expected:
                    finish_failure(root, state, job, 'Artifacts changed during final review')
                    return
                job['phase'] = 'passed'
                job.pop('error', None)
                job['attempts'][-1]['status'] = 'passed'
                event(root, state, f'{job["id"]}:accepted',
                      f'Build accepted: {job["id"]}. {job["attempts"][-1]["path"]}')
            else:
                finish_failure(root, state, job, decision['explanation'])
        elif decision['action'] == 'needs_attention':
            # A progress review must not interrupt an active build.
            event(root, state, f'{job["id"]}:concern:{state["sequence"]}',
                  f'{job["id"]} progress concern: {decision["explanation"]}. {root}')
        job['agent_failures'] = 0
    except (OSError, ValueError, KeyError) as error:
        job['agent_failures'] = job.get('agent_failures', 0) + 1
        if task['purpose'] == 'repair':
            # Retry this agent task in the SAME candidate; no hardware attempt
            # has run yet. Do not consume another plausible-fix opportunity.
            job['phase'] = 'repair_agent_retry'
        else:
            job['review_pending'] = True
        if job['agent_failures'] > 2:
            if task['purpose'] in ('repair', 'terminal'):
                job['phase'] = 'needs_attention'
            job['review_pending'] = False
            event(root, state, f'{job["id"]}:agent_blocked', f'Agent needs attention: {job["id"]}: {error}. {root}')
        job['agent_error'] = str(error)


def render(root, state):
    lines = ['# Build summary', '', f'Host: {state["host"]}. Status: {state["status"]}.', '',
             '| Build | State | Repairs | Attempt / evidence |', '| --- | --- | ---: | --- |']
    manifest = {}
    errors = []
    evidence = []
    for job in state['jobs'].values():
        path = job['attempts'][-1]['path'] if job['attempts'] else str(root / 'templates' / job['id'])
        lines.append(f'| {job["id"]} | {job["phase"]} | {job["repairs"]}/3 | {path} |')
        if job.get('error'):
            errors.append(f'{job["id"]}: {job["error"]}')
        if job['phase'] == 'passed':
            manifest[job['id']] = read(Path(path) / 'artifact_manifest.json')
            verification = manifest[job['id']].get('verification')
            if verification:
                evidence.extend(['', f'## {job["id"]} verification', '',
                                 '```json', json.dumps(verification, indent=2), '```'])
    lines.extend(['', *errors, '', 'Board validation and benchmarking are manually invoked.', '',
                  f'Agent decisions: {root / "agent_decisions.jsonl"}',
                  f'Command logs and transcripts: {root / "commands"}'])
    lines.extend(evidence)
    (root / 'BUILD_SUMMARY.md').write_text('\n'.join(lines) + '\n')
    save(root / 'artifact_manifest.json', manifest)


def cancel_owned(root, state):
    """Signal only live supervisors whose PID, boot and start time still match."""
    records = [job['command'] for job in state['jobs'].values()
               if job['phase'] in ('validate', 'build', 'verify')]
    if state.get('agent'):
        records.append(state['agent']['command'])
    for record in records:
        process = record.get('identity') or read(Path(record['directory']) / 'identity.json')
        if process and alive(process):
            if not record.get('cancel_sent'):
                os.kill(process['pid'], signal.SIGTERM)
                record['cancel_sent'] = True
        elif process and group_alive(process['pid']):
            raise RuntimeError('Owned supervisor lost with descendants alive; inspect before cancelling')
    if any(outcome(record, time.time()) is None for record in records):
        return False
    state.pop('agent', None)
    for job in state['jobs'].values():
        if job['phase'] not in TERMINAL:
            job['phase'] = 'cancelled'
    event(root, state, 'campaign:cancelled', f'Cancelled owned campaign: {root}')
    return True


def safe_start_stage(root, state, job, phase):
    try:
        start_stage(root, state, job, phase)
    except (OSError, ValueError) as error:
        # Failed preparation/validation is evidence for the next plausible fix.
        # An ambiguous Popen launch is handled by launch_intent, never replayed.
        if state.get('launch_intent'):
            raise
        finish_failure(root, state, job, str(error))


def tick(root, state, now):
    if state.get('launch_intent'):
        directory = Path(state['launch_intent']['directory'])
        if (directory / 'identity.json').exists() or (directory / 'exit.json').exists():
            # Command ownership was journaled before spawning. Reattach to its
            # durable result/identity; never launch a second command here.
            state.pop('launch_intent')
        else:
            raise RuntimeError('Interrupted launch without identity: inspect command directory before resuming; no duplicate dispatched')
    if (root / 'CANCEL').exists():
        if not cancel_owned(root, state):
            render(root, state)
            save(root / 'monitor_state.json', state)
            return False
    if state.get('agent'):
        result = outcome(state['agent']['command'], now)
        if result is not None:
            complete_agent(root, state, result)
    for job in state['jobs'].values():
        if job['phase'] not in ('validate', 'build', 'verify'):
            continue
        if observe(root, job, now):
            job['review_pending'] = True
        result = outcome(job['command'], now)
        if result is None:
            continue
        if result['returncode']:
            finish_failure(root, state, job, result.get('error', f'{job["phase"]} exited {result["returncode"]}; {job["command"]["directory"]}'))
        elif job['phase'] == 'validate':
            safe_start_stage(root, state, job, 'build')
        elif job['phase'] == 'build':
            safe_start_stage(root, state, job, 'verify')
        else:
            try:
                artifacts = sealed_artifacts(job)
                save(Path(job['attempts'][-1]['path']) / 'artifact_manifest.json', artifacts)
                job['phase'] = 'terminal_review'
                event(root, state, f'{job["id"]}:{len(job["attempts"])}:review',
                      f'{job["id"]} build/verification completed; agent review pending. {root}')
            except (ValueError, OSError) as error:
                finish_failure(root, state, job, str(error))
    if not (root / 'PAUSED').exists():
        active = sum(job['phase'] in ('validate', 'build', 'verify') for job in state['jobs'].values())
        for job in state['jobs'].values():
            if job['phase'] not in ('queued', 'retry_ready'):
                continue
            dependencies = [state['jobs'][name]['phase'] for name in job['depends']]
            if any(value in TERMINAL - {'passed'} for value in dependencies):
                job.update(phase='blocked', error='Required dependency did not pass')
                event(root, state, f'{job["id"]}:blocked', f'{job["id"]}: blocked by failed dependency. {root}')
                continue
            if active >= state['max_jobs'] or any(value != 'passed' for value in dependencies):
                continue
            if job['phase'] == 'queued':
                if tree_hashes(root / 'templates' / job['id']) != job['template_hashes']:
                    job.update(phase='needs_attention', error='Registered template changed before dispatch')
                    continue
                new_attempt(root, job, root / 'templates' / job['id'], now)
            job['attempts'][-1].update(started_at=now, next_check=now)
            safe_start_stage(root, state, job, 'validate')
            job['review_pending'] = True
            active += 1
            event(root, state, f'{job["id"]}:{len(job["attempts"])}:started',
                  f'Build started: {job["id"]} attempt {len(job["attempts"])}. {root}')
    if not state.get('agent') and not (root / 'PAUSED').exists():
        # Terminal and repair work takes priority over routine progress checks.
        for phase, purpose in [('terminal_review', 'terminal'), ('repair_pending', 'repair'),
                               ('repair_agent_retry', 'repair_resume'), ('validate', 'progress'),
                               ('build', 'progress'), ('verify', 'progress')]:
            candidates = [job for job in state['jobs'].values() if job['phase'] == phase
                          and (purpose not in ('progress',) or job.get('review_pending'))]
            if candidates:
                job = candidates[0]
                if purpose == 'repair_resume':
                    start_agent(root, state, job, 'repair', reuse=True)
                else:
                    start_agent(root, state, job, purpose)
                break
    done = bool(state['jobs']) and all(job['phase'] in TERMINAL for job in state['jobs'].values()) and not state.get('agent')
    state['status'] = 'complete' if done else ('paused' if (root / 'PAUSED').exists() else 'running')
    if done:
        state.setdefault('finished_at', now)
        event(root, state, 'campaign:finished', f'Build campaign complete: '
              f'{sum(j["phase"] == "passed" for j in state["jobs"].values())}/{len(state["jobs"])} accepted. '
              f'Summary: {root / "BUILD_SUMMARY.md"}')
    render(root, state)
    save(root / 'monitor_state.json', state)
    return done


def run(root):
    with locked(root):
        state = read(root / 'monitor_state.json')
        if socket.gethostname() != state['host']:
            raise RuntimeError('Wrong host; build campaigns are host-bound')
        if digest(root / 'PLAN.md') != state['plan_sha256']:
            raise RuntimeError('Approved plan changed')
        if not state['jobs']:
            raise ValueError('No registered jobs')
        if not shutil.which(state['codex']):
            raise ValueError('Configured Codex executable is unavailable')
        event(root, state, 'campaign:started', f'Build orchestrator started; max {state["max_jobs"]} jobs. {root}')
        while True:
            now = time.time()
            try:
                done = tick(root, state, now)
            except Exception as error:
                state['status'] = 'monitor_error'
                event(root, state, f'monitor:error:{state["sequence"]}',
                      f'Build monitor needs attention: {error}. Running jobs remain owned. {root}')
                render(root, state)
                save(root / 'monitor_state.json', state)
                # Best effort without obscuring the original failure.
                notify_due(root, state, now)
                raise
            notify_due(root, state, now)
            save(root / 'monitor_state.json', state)
            reap_runners()
            if done and (all(row['delivered'] for row in state['notifications'].values())
                         or now - state['finished_at'] >= 900):
                return
            time.sleep(10)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    init = sub.add_parser('init')
    init.add_argument('root', type=Path)
    init.add_argument('--plan', type=Path, required=True)
    init.add_argument('--jobs', type=int, choices=range(1, 6), default=5)
    init.add_argument('--codex', default='codex')
    add = sub.add_parser('add')
    add.add_argument('root', type=Path)
    add.add_argument('--id', required=True)
    add.add_argument('--template', type=Path, required=True)
    for flag in ['validate', 'build', 'verify']:
        add.add_argument('--' + flag, required=True, help='Explicit argv string; {work} expands to the isolated working directory')
    add.add_argument('--artifact', action='append', required=True)
    add.add_argument('--invariant', action='append', default=[])
    add.add_argument('--depends', action='append', default=[])
    add.add_argument('--timeout', type=float, default=24 * 3600)
    for name in ['run', 'start', 'status', 'pause', 'resume', 'cancel']:
        command = sub.add_parser(name)
        command.add_argument('root', type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    if args.action == 'init':
        if not args.plan.is_file():
            raise ValueError('Plan does not exist')
        root.mkdir(parents=True, exist_ok=False)
        shutil.copyfile(args.plan, root / 'PLAN.md')
        save(root / 'monitor_state.json', {'host': socket.gethostname(), 'status': 'planned',
             'plan_sha256': digest(root / 'PLAN.md'), 'max_jobs': args.jobs,
             'codex': args.codex, 'jobs': {}, 'notifications': {}, 'sequence': 0})
        return
    if args.action == 'run':
        return run(root)
    if args.action == 'status':
        print((root / 'BUILD_SUMMARY.md').read_text() if (root / 'BUILD_SUMMARY.md').exists()
              else (root / 'monitor_state.json').read_text())
        return
    if args.action == 'pause':
        (root / 'PAUSED').touch()
        return
    if args.action == 'resume':
        (root / 'PAUSED').unlink(missing_ok=True)
        # Resume means unpause, not start a competing controller. Use start
        # after a controller exit; it reuses durable command identities.
        print('Unpaused. If the monitor has exited, use start to restart it.')
        return
    if args.action == 'cancel':
        (root / 'CANCEL').touch()
        print('Cancellation requested for this campaign only; monitor must be running.')
        return
    if args.action == 'start':
        # Check ownership, then release before the new tmux worker takes it.
        with locked(root):
            pass
        session = 'buildctl_' + hashlib.sha256(str(root).encode()).hexdigest()[:12]
        command = shlex.join([sys.executable, str(Path(__file__).resolve()), 'run', str(root)])
        subprocess.run(['tmux', 'new-session', '-d', '-s', session,
                        command + ' >> ' + shlex.quote(str(root / 'monitor.log')) + ' 2>&1'], check=True)
        print('Started tmux session', session)
        return
    with locked(root):
        state = read(root / 'monitor_state.json')
        if args.action == 'add':
            if state['status'] != 'planned' or not re.fullmatch(r'[A-Za-z0-9_-]+', args.id):
                raise ValueError('Register valid IDs before starting the campaign')
            if args.id in state['jobs'] or any(dep not in state['jobs'] for dep in args.depends):
                raise ValueError('Duplicate job or missing dependency; register dependencies first')
            source = args.template.resolve()
            if source == root or source.is_relative_to(root) or root.is_relative_to(source):
                raise ValueError('Template must be outside the new campaign')
            if read(source / 'status.json').get('status') in ('running', 'starting'):
                raise ValueError('Refusing an active build template; provide a prepared source-only copy')
            target = root / 'templates' / args.id
            commands = {name: shlex.split(getattr(args, name)) for name in ('validate', 'build', 'verify')}
            if any(not value for value in commands.values()) or args.timeout <= 0:
                raise ValueError('Commands and a positive timeout are required')
            invariants = {name: digest(contained(source, name)) for name in args.invariant}
            for phase in ('validate', 'verify'):
                # Freeze local acceptance scripts as well as user invariants.
                for argument in commands[phase]:
                    if argument.startswith('/') or '{work}' in argument:
                        continue
                    path = contained(source, argument)
                    if path.is_file():
                        invariants[argument] = digest(path)
            for name in args.artifact:
                contained(source, name)
            target.parent.mkdir(exist_ok=True)
            copy_inputs(source, target)
            state['jobs'][args.id] = dict(id=args.id, phase='queued', repairs=0, attempts=[],
                depends=args.depends, timeout=args.timeout, artifacts=args.artifact,
                invariants=invariants, template_hashes=tree_hashes(target), **commands)
            save(root / 'monitor_state.json', state)


if __name__ == '__main__':
    main()
