#!/usr/bin/env python3
"""Durable terminal-event/ntfy monitor; repair decisions belong to the agent."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import subprocess
import time

from worker import save


def observe(root, sent):
    events = []
    for path in sorted(root.glob('*/attempt_*/status.json')):
        state = json.loads(path.read_text())
        status = state.get('status')
        if status == 'running' and state.get('pid'):
            process = Path('/proc') / str(state['pid']) / 'cmdline'
            try:
                marker = state.get('process_marker', 'deployment_worker.py')
                alive = marker.encode() in process.read_bytes()
            except OSError:
                alive = False
            if not alive:
                status = 'unexpected_exit'
        if status not in ('passed', 'failed', 'unexpected_exit'):
            continue
        key = str(path.relative_to(root)) + ':' + status
        if key not in sent:
            events.append((key, state, status))
    return events


def run(root):
    with (root / 'monitor.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        record = root / 'monitor.json'
        previous = json.loads(record.read_text()) if record.exists() else {}
        sent = set(previous.get('sent', []))
        while True:
            for key, state, status in observe(root, sent):
                event = {
                    'key': key, 'status': status, 'state': state,
                    'observed_at': time.time(), 'requires_agent': status != 'passed',
                }
                with (root / 'events.jsonl').open('a') as output:
                    output.write(json.dumps(event) + '\n')
                message = (
                    f"HBM/network {state['id']}: {status}; "
                    f"stage={state.get('stage')}; {state.get('error', '')}; {root}"
                )
                response = subprocess.run([
                    'curl', '-fsS', '--max-time', '20', '-d', message,
                    'https://ntfy.sh/coyote-build-sdeheredia',
                ], capture_output=True, text=True)
                if response.returncode == 0:
                    sent.add(key)
                event['ntfy_exit'] = response.returncode
                save(root / 'last_event.json', event)
            save(record, {'pid': os.getpid(), 'heartbeat': time.time(),
                          'sent': sorted(sent), 'status': 'watching'})
            time.sleep(10)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('root', type=Path)
    run(parser.parse_args().root.resolve())
