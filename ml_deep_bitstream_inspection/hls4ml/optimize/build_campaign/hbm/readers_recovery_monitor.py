#!/usr/bin/env python3
"""Durable recovery observations and ntfy outbox, without relaunching work."""

import argparse
import fcntl
import json
import os
from pathlib import Path
import subprocess
import time

from readers_recovery_worker import save


def run(root):
    record_path = root / 'monitor.json'
    previous = json.loads(record_path.read_text()) if record_path.exists() else {}
    notifications = previous.get('notifications', {})
    reviews = previous.get('reviews', {})
    while True:
        now = time.time()
        for path in sorted(root.glob('*/attempt_*/status.json')):
            state = json.loads(path.read_text())
            status = state['status']
            if status == 'prepared':
                continue
            if status == 'running':
                try:
                    command = Path(f"/proc/{state['pid']}/cmdline").read_bytes()
                    alive = b'readers_recovery_worker.py' in command and str(path.parent).encode() in command
                except OSError:
                    alive = False
                if not alive:
                    status = 'unexpected_exit'
            identity = str(path.parent.relative_to(root))
            event = status
            if status == 'running':
                event = 'implementation_started' if state.get('implementation_started_at') else 'validation_started'
            if event in ('validation_started', 'implementation_started', 'passed', 'failed', 'unexpected_exit'):
                key = identity + ':' + event
                if key not in notifications:
                    notifications[key] = {
                        'message': f"HBM reader recovery {identity}: {event}; stage={state['stage']}; "
                                   f"{state.get('error', '')}; {root}",
                        'delivered': False, 'tries': 0, 'next_try': now,
                    }
                    with (root / 'events.jsonl').open('a') as handle:
                        handle.write(json.dumps({'key': key, 'state': state, 'at': now}) + '\n')
            start = state.get('implementation_started_at', state.get('started_at', now))
            elapsed = now - start
            interval = 30 if elapsed <= 300 else 3600
            review_key = identity + (':implementation' if state.get('implementation_started_at') else ':validation')
            if status == 'running' and now - reviews.get(review_key, 0) >= interval:
                with (root / 'observations.jsonl').open('a') as handle:
                    handle.write(json.dumps({'at': now, 'identity': identity, 'state': state,
                                             'elapsed_seconds': elapsed, 'process_alive': True}) + '\n')
                reviews[review_key] = now
        for event in notifications.values():
            if event['delivered'] or now < event['next_try']:
                continue
            response = subprocess.run([
                'curl', '-fsS', '--connect-timeout', '5', '--max-time', '10',
                '-d', event['message'], 'https://ntfy.sh/coyote-build-sdeheredia',
            ], capture_output=True, text=True)
            event.update(delivered=response.returncode == 0, tries=event['tries'] + 1,
                         next_try=time.time() + 30, response=response.stdout, error=response.stderr)
        save(record_path, {'pid': os.getpid(), 'heartbeat': time.time(),
                           'notifications': notifications, 'reviews': reviews, 'status': 'watching'})
        time.sleep(10)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('root', type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    with (root / 'monitor.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        run(root)
