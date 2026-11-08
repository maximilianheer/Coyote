#!/usr/bin/env python3
"""Wake the supervising tool call on terminal build state or worker death.

Run this in an awaited exec session while the assistant sleeps. ntfy delivery
is independently handled by deployment_monitor.py. A receipt is written only
when the supervising agent explicitly acknowledges the event after diagnosis.
"""
import argparse
import json
from pathlib import Path
import time

from deployment_monitor import observe


def wait(root):
    while True:
        receipt = root / 'agent_event_receipts.json'
        handled = set(json.loads(receipt.read_text())) if receipt.exists() else set()
        events = observe(root, handled)
        if events:
            print(json.dumps([{'key': key, 'state': state, 'status': status}
                              for key, state, status in events]), flush=True)
            return
        time.sleep(5)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('root', type=Path)
    wait(parser.parse_args().root.resolve())
