"""Process-owned implementation permits, with configurable shared capacity.

The legacy default is three primary plus one non-streaming slot. Shared
campaigns can explicitly select up to six slots. Legacy workers keep their
original shared lock and temporarily reserve primary-0. Preparation,
synthesis of HLS kernels and RTL validation do not take permits.
"""
import contextlib, fcntl, json, os, time
from pathlib import Path


def alive(pid, marker):
    try:
        cmd=Path(f'/proc/{int(pid)}/cmdline').read_bytes().replace(b'\0',b' ').decode()
        return marker in cmd
    except (OSError, ValueError, TypeError):return False


def available_slots(root, lane):
    config = root / 'capacity.json'
    if config.exists():
        capacity = json.loads(config.read_text())
        if capacity.get('policy') != 'shared':
            raise ValueError('Unknown implementation capacity policy')
        count = capacity.get('slots')
        if type(count) is not int or not 1 <= count <= 6:
            raise ValueError('Shared implementation capacity must be 1..6')
        return list(range(count))
    if lane not in ('primary','nonstreaming'):raise ValueError('Unknown implementation lane')
    slots=[0,1,2] if lane=='primary' else [3]
    legacy=root/'legacy.json'
    if lane=='primary' and legacy.exists():
        if any(alive(row['pid'],row['job']) for row in json.loads(legacy.read_text())):slots.remove(0)
    return slots


@contextlib.contextmanager
def permit(progress=lambda **kw:None):
    directory=os.environ.get('HLS4ML_IMPLEMENTATION_PERMITS')
    if not directory:
        path=Path(os.environ['HLS4ML_IMPLEMENTATION_LOCK']);path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('a') as handle:
            progress(stage='waiting_implementation_lock')
            fcntl.flock(handle,fcntl.LOCK_EX)
            yield
        return
    root=Path(directory);root.mkdir(parents=True,exist_ok=True)
    lane=os.environ.get('HLS4ML_IMPLEMENTATION_LANE','primary')
    progress(stage='waiting_implementation_permit',implementation_lane=lane)
    handle=None
    while handle is None:
        for slot in available_slots(root,lane):
            candidate=(root/f'slot_{slot}.lock').open('a+')
            try:fcntl.flock(candidate,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:candidate.close();continue
            handle=candidate;break
        if handle is None:time.sleep(2)
    try:
        handle.seek(0);handle.truncate();handle.write(json.dumps({'pid':os.getpid(),'lane':lane,'at':time.time()}));handle.flush()
        progress(implementation_slot=slot)
        yield
    finally:
        fcntl.flock(handle,fcntl.LOCK_UN);handle.close()
