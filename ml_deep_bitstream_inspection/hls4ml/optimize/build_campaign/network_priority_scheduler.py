#!/usr/bin/env python3
"""Launch prepared networking jobs first; preserve running reader recoveries."""

import argparse
import fcntl
import json
import os
from pathlib import Path
import shlex
import subprocess
import time

from worker import save


def live(path):
    state = json.loads(path.read_text())
    if state.get('status') != 'running':
        return False
    try:
        command = Path(f'/proc/{state["pid"]}/cmdline').read_bytes()
        return str(path.parent.resolve()).encode() in command
    except (OSError, KeyError):
        return False


def event(root, kind, **fields):
    with (root / 'priority_events.jsonl').open('a') as output:
        output.write(json.dumps({'at': time.time(), 'kind': kind, **fields}) + '\n')


def tick(root, readers, state):
    now = time.time()
    active = [path for campaign in [root, readers]
              for path in campaign.glob('*/attempt_*/status.json') if live(path)]
    # Failed reader jobs are deliberately deferred. Diagnosis/repairs belong to
    # the supervising agent; a scheduler must not repeat failed hardware blindly.
    for path in readers.glob('*/attempt_*/status.json'):
        data = json.loads(path.read_text())
        key = str(path)
        if data.get('status') == 'failed' and key not in state['deferred_readers']:
            state['deferred_readers'].append(key)
            event(root, 'reader_repair_deferred', job=str(path.parent),
                  reason='All networking work has priority')
    queue_path = root / 'repair_queue.json'
    queue = json.loads(queue_path.read_text())
    waiting = sorted(
        [item for item in queue['pending']
         if item['status'] == 'prepared_waiting_for_capacity'],
        key=lambda item: item.get('priority', 4),
    )
    if len(active) < 6 and waiting:
        item = waiting[0]
        job = Path(item['job'])
        if not job.is_relative_to(root):
            raise RuntimeError('Queued job is outside the network campaign')
        # Count live workers before project generation too. Their implementation
        # permits are acquired later; counting permits alone could launch >6 jobs.
        session = 'netq_' + job.parent.name.lower() + '_' + job.name
        exists = subprocess.run(['tmux', 'has-session', '-t', session],
                                capture_output=True).returncode == 0
        if not exists:
            script = root / 'queue_launchers' / (session + '.sh')
            script.parent.mkdir(exist_ok=True)
            script.write_text(
                '#!/usr/bin/env bash\nset -eu\n'
                f'export HLS4ML_IMPLEMENTATION_PERMITS={shlex.quote(str(root / "permits"))}\n'
                'export HLS4ML_IMPLEMENTATION_LANE=primary\n'
                'exec ' + shlex.join(item['command']) + ' > '
                + shlex.quote(str(script.with_suffix('.log'))) + ' 2>&1\n'
            )
            subprocess.run(['tmux', 'new-session', '-d', '-s', session,
                            'bash ' + shlex.quote(str(script))], check=True)
        item.update(status='launched', launched_at=now, tmux=session)
        queue['updated_at'] = now
        save(queue_path, queue)
        state['watches'][str(job)] = {'started': now, 'last': 0, 'observations': []}
        message = f'Networking priority queue launched {job.parent.name}/{job.name}; five-minute startup watch attached.'
        state['notifications'].append({'message': message, 'delivered': False})
        event(root, 'launched', job=str(job), priority=item.get('priority', 4))
    for name, watch in state['watches'].items():
        if watch.get('complete') or now - watch['last'] < 30:
            continue
        path = Path(name) / 'status.json'
        if not path.exists():
            if now - watch['started'] > 30:
                watch.update(complete=True, outcome='worker_status_missing')
                event(root, 'startup_requires_agent', job=name)
            continue
        data = json.loads(path.read_text())
        # The prepared status file exists before the detached worker writes
        # its PID. Allow that handoff instead of ending the startup watch.
        if data.get('status') == 'prepared' and now - watch['started'] < 30:
            continue
        row = {'at': now, 'stage': data.get('stage'), 'alive': live(path)}
        watch['observations'].append(row)
        watch['last'] = now
        if not row['alive'] or now - watch['started'] >= 300:
            watch['complete'] = True
            watch['outcome'] = 'passed' if row['alive'] else 'requires_agent'
            save(Path(name) / 'restart_watch.json', watch)
            event(root, 'startup_watch_complete', job=name, outcome=watch['outcome'])
    for notification in state['notifications']:
        if notification['delivered'] or now < notification.get('retry_at', 0):
            continue
        result = subprocess.run(
            ['curl', '-fsS', '--max-time', '15', '-d', notification['message'],
             'https://ntfy.sh/coyote-build-sdeheredia'], capture_output=True, text=True)
        notification.update(delivered=result.returncode == 0, retry_at=now + 60)
    state.update(pid=os.getpid(), heartbeat=now,
                 active_workers=[str(path.parent) for path in active],
                 policy='network_first; running readers finish; reader repairs deferred')


def run(root, readers):
    with (root / 'priority_scheduler.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        path = root / 'priority_scheduler.json'
        state = json.loads(path.read_text()) if path.exists() else {
            'watches': {}, 'notifications': [], 'deferred_readers': []}
        while True:
            tick(root, readers, state)
            save(path, state)
            time.sleep(10)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('network', type=Path)
    parser.add_argument('readers', type=Path)
    arguments = parser.parse_args()
    run(arguments.network.resolve(), arguments.readers.resolve())
