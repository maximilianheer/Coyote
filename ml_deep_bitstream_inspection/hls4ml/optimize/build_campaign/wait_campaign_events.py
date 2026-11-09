#!/usr/bin/env python3
"""Wait for terminal events across campaigns or a recovery synthesis launch."""

import argparse
import json
from pathlib import Path
import time

from deployment_monitor import observe


def wait(roots):
    while True:
        events = []
        for root in roots:
            receipt = root / 'agent_event_receipts.json'
            handled = set(json.loads(receipt.read_text())) if receipt.exists() else set()
            for key, state, status in observe(root, handled):
                events.append({'root': str(root), 'key': key, 'state': state, 'status': status})
            for path in root.glob('*/attempt_*/status.json'):
                state = json.loads(path.read_text())
                if state.get('process_marker') != 'readers_recovery_worker.py':
                    continue
                key = str(path.relative_to(root)) + ':implementation_started'
                if state.get('implementation_started_at') and key not in handled:
                    events.append({'root': str(root), 'key': key, 'state': state,
                                   'status': 'implementation_started'})
        if events:
            print(json.dumps(events), flush=True)
            return
        time.sleep(10)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('roots', type=Path, nargs='+')
    args = parser.parse_args()
    wait([root.resolve() for root in args.roots])
