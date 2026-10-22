#!/usr/bin/env python3
"""Independent ntfy watchdog for an existing iteration campaign; never changes builds."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import subprocess
import time

TOPIC = 'https://ntfy.sh/coyote-build-sdeheredia'
TERMINAL = {'passed', 'failed', 'blocked'}


def read(path, default=None):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {} if default is None else default


def alive(pid, marker):
    try:
        path = Path('/proc') / str(int(pid))
        command=(path/'cmdline').read_bytes()
        if marker.encode() in command:return True
        if marker.startswith('/'):
            cwd=(path/'cwd').resolve()
            for argument in command.decode(errors='replace').split('\0'):
                if argument and not argument.startswith('-'):
                    if str((cwd/argument).resolve())==marker:return True
        return False
    except (OSError, ValueError, TypeError):
        return False


def legacy_delivered(root, ident, since=0):
    try:
        lines = (root/'notifications.jsonl').read_text().splitlines()
    except OSError:
        return False
    for line in lines:
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if record.get('id') == ident and record.get('notification_returncode') == 0 and record.get('at',0) >= since:
            return True
    return False


def observe(root, is_alive=alive, campaign_file='campaign.json'):
    campaign = read(root/campaign_file)
    supervisor_alive = is_alive(campaign.get('pid'), campaign.get('process_marker','iterations.py'))
    jobs = dict(campaign.get('candidates', {}))
    if campaign.get('baseline'):
        jobs['OPT_1_STREAMING'] = campaign['baseline']
    events = {}
    workers_alive = False
    for ident, directory in jobs.items():
        job = Path(directory)
        state = read(job/'status.json')
        running = is_alive(state.get('pid'), str(job))
        workers_alive |= running
        status = state.get('status')
        if status in TERMINAL or (state and not running):
            outcome = status if status in TERMINAL else 'unexpected worker exit'
            key = f'{ident}:{job.name}:{outcome}'
            events[key] = {'id': ident, 'job': str(job), 'outcome': outcome, 'started_at':state.get('started_at',0),
                           'message': f'hls4ml {ident} {job.name}: {outcome}. '
                                      f'Last stage: {state.get("stage", "unknown")}. Results: {job}'}
    if campaign and not supervisor_alive and campaign.get('status') not in TERMINAL:
        events['campaign:unexpected_exit'] = {
            'id': 'campaign', 'outcome': 'unexpected supervisor exit',
            'message': f'hls4ml campaign supervisor exited unexpectedly. '
                       f'Worker processes still active: {workers_alive}. Results: {root}'}
    done = bool(campaign) and not supervisor_alive and not workers_alive
    return events, done


def send(root, event):
    try:
        result = subprocess.run(
            ['curl', '--fail', '--show-error', '--silent', '--max-time', '20',
             '-d', event['message'], TOPIC], capture_output=True, text=True)
        record = dict(event, at=time.time(), returncode=result.returncode,
                      response=result.stdout.strip(), error=result.stderr.strip())
    except OSError as error:
        record = dict(event, at=time.time(), returncode=-1, error=str(error))
    with (root/'monitor_notifications.jsonl').open('a') as output:
        output.write(json.dumps(record)+'\n')
    return record['returncode'] == 0


def save(path, data):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, indent=2)+'\n')
    temporary.replace(path)


def monitor(root, campaign_file='campaign.json', prefix='notification_monitor'):
    with (root/(prefix+'.lock')).open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        path = root/(prefix+'.json')
        state = read(path)
        state.update(pid=os.getpid(), status='running', topic=TOPIC)
        state.setdefault('events', {})
        state.pop('done_first_seen',None)
        while True:
            events, done = observe(root, campaign_file=campaign_file)
            events['monitor:attached'] = {
                'id': 'monitor', 'outcome': 'attached',
                'message': f'hls4ml termination watchdog attached: baseline + A/B2. '
                           f'Completion, failure and unexpected exits monitored. Results: {root}'}
            now = time.time()
            pending = False
            for key, event in events.items():
                record = state['events'].setdefault(key, {'first_seen': now, 'delivered': False})
                if record['delivered']:
                    continue
                # Give the campaign's normal sender time to finish; avoid duplicate notifications.
                if event['id'] not in {'monitor', 'campaign'} and legacy_delivered(root, event['id'], event.get('started_at',0)):
                    record.update(delivered=True, via='campaign')
                    continue
                pending = True
                grace = 0 if event['id'] == 'monitor' else 45
                if now-record['first_seen'] < grace or now-record.get('last_attempt', 0) < 60:
                    continue
                record['last_attempt'] = now
                record['delivered'] = send(root, event)
                record['via'] = 'watchdog'
            state.update(heartbeat_at=time.time(), campaign_finished=done)
            if done:
                state.setdefault('done_first_seen',time.time())
            else:
                state.pop('done_first_seen',None)
            # Retry supervisors atomically replace the previous campaign record.
            # Observe a stable terminal state before exiting to avoid a startup race.
            if done and not pending and time.time()-state['done_first_seen'] >= 60:
                state['status'] = 'complete'
            save(path, state)
            if state['status'] == 'complete':
                return
            time.sleep(20)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('--campaign-file',default='campaign.json')
    parser.add_argument('--prefix',default='notification_monitor')
    args=parser.parse_args()
    monitor(args.root.resolve(),args.campaign_file,args.prefix)
