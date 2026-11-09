#!/usr/bin/env python3
"""Exclusive board lease and durable, logged benchmark command supervision."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import subprocess
import time


def save(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.replace(path)


def notify(message):
    subprocess.run(['curl', '-fsS', '--max-time', '20', '-d', message,
                    'https://ntfy.sh/coyote-build-sdeheredia'], capture_output=True)


def run(root, board_lock):
    state = {'pid': os.getpid(), 'status': 'running', 'stage': 'waiting_board_lease'}
    commands = root / 'commands'
    commands.mkdir(exist_ok=True)

    def update(**values):
        state.update(values, heartbeat=time.time())
        save(root / 'status.json', state)

    with (root / 'controller.lock').open('a') as owner, board_lock.open('a') as lease:
        fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        while True:
            try:
                fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                update()
                time.sleep(5)
        notify('HBM benchmark campaign acquired the device2 board lease; preparing OPT_10/11 admission.')
        update(stage='ready')
        while True:
            pending = [path for path in sorted(commands.glob('*.json'))
                       if not (root / 'logs' / (path.stem + '.result.json')).exists()]
            if not pending:
                update()
                time.sleep(2)
                continue
            request = pending[0]
            command = json.loads(request.read_text())
            if command.get('finish'):
                update(status='passed', stage='board_work_complete')
                return
            stage = command['stage']
            state.pop('error', None)
            update(status='running', stage=stage, command=request.name, started_at=time.time())
            environment = dict(os.environ)
            environment.update(command.get('env', {}))
            with (root / 'logs' / (request.stem + '.log')).open('w') as log:
                process = subprocess.Popen(command['argv'], cwd=command.get('cwd'), env=environment,
                                           stdout=log, stderr=subprocess.STDOUT)
                update(child_pid=process.pid)
                while process.poll() is None:
                    update()
                    if time.time() - state['started_at'] > command.get('timeout', 7200):
                        process.terminate()
                        process.wait(timeout=30)
                        break
                    time.sleep(2)
            result = {'stage': stage, 'exit_code': process.returncode, 'finished_at': time.time()}
            save(root / 'logs' / (request.stem + '.result.json'), result)
            if process.returncode:
                update(status='failed', error=f'{stage} exited {process.returncode}')
                notify(f'HBM benchmark {stage} FAILED; supervisor inspecting {root}/logs/{request.stem}.log')
            else:
                update(stage='ready')
                notify('HBM benchmark gate completed: ' + stage)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('root', type=Path)
    parser.add_argument('board_lock', type=Path)
    arguments = parser.parse_args()
    run(arguments.root.resolve(), arguments.board_lock.resolve())
