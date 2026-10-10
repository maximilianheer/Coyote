"""Require an explicit host identity when replaying a board run elsewhere."""
import json
from pathlib import Path
import socket


def verify_host(root):
    path = Path(root) / 'board_target.json'
    target = json.loads(path.read_text()) if path.exists() else {
        'hostname': 'hacc-u55c-03.inf.ethz.ch'}
    actual = socket.gethostname()
    if actual != target['hostname']:
        raise RuntimeError(f"Wrong board host: {actual}; expected {target['hostname']}")
    return target
