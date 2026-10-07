#!/usr/bin/env python3
"""Persistent ntfy reporter. Only sends to the user-authorized build topic."""
import argparse
import json
import subprocess
import time
from pathlib import Path

URL = 'https://ntfy.sh/coyote-build-sdeheredia'

def notify(root, message):
    result = subprocess.run(['curl', '--fail', '--silent', '--show-error',
        '--connect-timeout', '10', '--max-time', '30', '-H',
        'Title: Coyote optimization builds', '--data-binary', message, URL],
        capture_output=True, text=True)
    with (root / 'notifications.jsonl').open('a') as f:
        f.write(json.dumps({'time': time.time(), 'message': message,
                           'sent': result.returncode == 0,
                           'response': result.stdout if result.returncode == 0 else result.stderr}) + '\n')
    return result.returncode == 0

def summary(root, state):
    jobs = state.get('jobs', [])
    counts = {s: sum(j['status'] == s for j in jobs) for s in
              ['running', 'passed', 'failed', 'pending', 'blocked']}
    lines = [f"Campaign {root.name}: " + ', '.join(f'{s}={n}' for s, n in counts.items())]
    for job in jobs:
        if job['status'] in ('running', 'failed', 'blocked'):
            age = (time.time() - job.get('started_at', time.time())) / 3600
            lines.append(f"{job['id']}: {job['status']} {job.get('stage', '')} ({age:.1f}h) {job.get('error', '')}")
    lines.append(f"tmux: {state.get('tmux_session', 'preparing')}; results: {root}")
    return '\n'.join(lines)

def run(root, interval=3600, once=False):
    sent = set()
    next_hour = 0
    stopped_alert = False
    recovery_sent = 0
    while True:
        try:
            state = json.loads((root / 'status.json').read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            state = {'jobs': [], 'phase': 'preparing'}
        events=root/'recovery_events.jsonl'
        if events.exists():
            lines=events.read_text().splitlines()
            for line in lines[recovery_sent:]:
                try: entry=json.loads(line)
                except json.JSONDecodeError:break
                if not notify(root,f"{root.name}: {entry['job']} {entry['action']}: {entry['detail']}"):break
                recovery_sent+=1
        for job in state.get('jobs', []):
            if job['status'] in ('failed', 'passed', 'blocked'):
                key = (job['id'], job['status'], job.get('attempt', 1))
                if key not in sent:
                    if notify(root, f"{root.name}: {job['id']} {job['status']}; stage={job.get('stage')}; "
                        f"{job.get('error', '')}\nLog: {root / 'jobs' / job['id'] / 'worker.log'}"):
                        sent.add(key)
        heartbeat = state.get('heartbeat', time.time())
        if state.get('phase') == 'running' and time.time() - heartbeat > 180:
            if not stopped_alert:
                stopped_alert = notify(root, f'{root.name}: ISSUE: scheduler heartbeat is stale. Inspect tmux and scheduler.log.')
        else:
            stopped_alert = False
        if time.time() >= next_hour or once:
            if notify(root, summary(root, state)):
                next_hour = time.time() + interval
            else:
                next_hour = time.time() + 60
        if state.get('phase') == 'finished':
            if notify(root, 'Campaign finished.\n' + summary(root, state)):
                return
        if once:
            return
        time.sleep(30)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('root', type=Path)
    parser.add_argument('--interval', type=int, default=3600)
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    run(args.root.resolve(), args.interval, args.once)
