#!/usr/bin/env python3
"""Queue isolated acceptance continuation only after routed timing passes."""

import argparse
import json
from pathlib import Path
import shutil
import time

from prepare import HERE, sha
from worker import final_timing_reports, save


def prepare(original, output):
    config = json.loads((original / 'config.json').read_text())
    final_timing_reports(original / 'build', config['id'])
    for name, digest in json.loads((original / 'source_hashes.json').read_text()).items():
        if sha(original / name) != digest:
            raise RuntimeError('Source changed: ' + name)
    output.mkdir(parents=True, exist_ok=False)
    for name in ['hw', 'coyote']:
        shutil.copytree(original / name, output / name)
    shutil.copy2(original / 'source_hashes.json', output / 'source_hashes.json')
    for name in ['validation.json', 'repair_preflight.json',
                 'generated_control_clock_verification.json',
                 'generated_hbm_clock_verification.json']:
        if (original / name).exists():
            shutil.copy2(original / name, output / name)
    config.update(recovery_of=str(original), continuation='Acceptance and bitgen only')
    save(output / 'config.json', config)
    (output / 'tooling').mkdir()
    for name in ['deployment_finish.py', 'implementation_permits.py', 'prepare.py',
                 'worker.py', 'hbm_clock.py', 'network_timing.py']:
        shutil.copy2(HERE / name, output / 'tooling' / name)
    save(output / 'tool_identity.json', {
        path.name: sha(path) for path in (output / 'tooling').glob('*.py')})
    save(output / 'status.json', {'id': config['id'], 'status': 'prepared',
                                  'stage': 'waiting_for_build_capacity'})
    root = original.parent.parent
    path = root / 'repair_queue.json'
    queue = json.loads(path.read_text())
    queue['updated_at'] = time.time()
    queue['pending'].append({
        'job': str(output), 'id': config['id'], 'status': 'prepared_waiting_for_capacity',
        'priority': 0, 'kind': 'acceptance_continuation',
        'reason': 'Routed timing passes; verify merged user clock and finish bitgen',
        'command': ['python3', str(output / 'tooling/deployment_finish.py'),
                    str(original), str(output)],
    })
    save(path, queue)
    with (root / 'repair_journal.jsonl').open('a') as log:
        log.write(json.dumps({'at': time.time(), 'ancestor': str(original),
                              'output': str(output), 'action': 'queue_acceptance_continuation',
                              'routed_timing': 'passed'}) + '\n')
    print(output, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('original', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    prepare(args.original.resolve(), args.output.resolve())
