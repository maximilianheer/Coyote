"""Detached command runner with durable identity and completion records."""

import argparse
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import time


def save(path, value):
    temporary = path.with_suffix('.tmp')
    with temporary.open('w') as output:
        json.dump(value, output, indent=2)
        output.write('\n')
        output.flush()
        os.fsync(output.fileno())
    temporary.replace(path)


def identity(pid):
    try:
        fields = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
        return {
            'pid': pid,
            'start_ticks': fields[19],
            'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
            'process_state': fields[0],
        }
    except (OSError, IndexError):
        return None


def alive(record):
    current = identity(record.get('pid'))
    return bool(current and current['process_state'] != 'Z' and all(
        current[key] == record.get(key) for key in ('pid', 'start_ticks', 'boot_id')
    ))


def group_alive(group, exclude=None):
    """Include descendants after a wrapper exits; zombies consume no build slot."""
    for path in Path('/proc').glob('[0-9]*/stat'):
        try:
            if int(path.parent.name) == exclude:
                continue
            fields = path.read_text().rsplit(')', 1)[1].split()
            if fields[0] != 'Z' and int(fields[2]) == group:
                return True
        except (OSError, ValueError, IndexError):
            continue
    return False


def run(directory, cwd, command, timeout):
    if os.getpgrp() != os.getpid():
        raise RuntimeError('Runner must be launched in its own session')
    with (directory / 'runner.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if (directory / 'exit.json').exists():
            raise RuntimeError('This command already completed')
        save(directory / 'identity.json', identity(os.getpid()))
        started = time.time()
        result = {'started_at': started, 'command': command, 'cwd': str(cwd)}
        child = None

        def interrupted(signum, frame):
            raise InterruptedError(f'Received signal {signum}')

        signal.signal(signal.SIGTERM, interrupted)
        signal.signal(signal.SIGINT, interrupted)
        try:
            with (directory / 'command.log').open('ab') as log:
                child = subprocess.Popen(command, cwd=cwd, stdout=log,
                                         stderr=subprocess.STDOUT)
                result['returncode'] = child.wait(timeout=timeout)
                if group_alive(os.getpgrp(), exclude=os.getpid()):
                    raise RuntimeError('Command left background children; build commands must stay foreground')
        except BaseException as error:
            result.update(returncode=-1, error=str(error))
            # Descendants share this runner's process group. Ignore TERM here
            # while draining owned processes; never signal unrelated build PIDs.
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            os.killpg(os.getpgrp(), signal.SIGTERM)
            # A parent shell may exit while its tools are still alive. Give the
            # entire owned group a grace period, then kill it including this
            # supervisor. The controller waits for group drain before retrying.
            if child is not None:
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass
            time.sleep(1)
            result.update(finished_at=time.time(), error=str(error) + '; stopped owned group')
            save(directory / 'exit.json', result)
            os.killpg(os.getpgrp(), signal.SIGKILL)
        result['finished_at'] = time.time()
        save(directory / 'exit.json', result)
        return result['returncode']


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('cwd', type=Path)
    parser.add_argument('timeout', type=float)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    raise SystemExit(run(args.directory, args.cwd, args.command, args.timeout))
