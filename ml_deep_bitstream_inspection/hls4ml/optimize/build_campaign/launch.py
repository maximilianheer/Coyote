#!/usr/bin/env python3
"""Create a new isolated campaign and persistent scheduler/notification windows."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shlex
import subprocess
import sys
import time
from campaign import ORDER

HERE = Path(__file__).resolve().parent

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=HERE.parent/'runs'/datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S'))
    parser.add_argument('--streaming-only', action='store_true', help='Isolated S_I job; leave existing campaigns untouched')
    args = parser.parse_args()
    root = args.root.resolve()
    root.mkdir(parents=True, exist_ok=False)
    (root/'jobs').mkdir()
    session = 'coyote_opt_'+root.name
    state = dict(phase='preparing', heartbeat=time.time(), tmux_session=session,
                 max_jobs=5, jobs=[dict(id=j, status='pending', stage='preparation', attempt=1) for j in (['S_I'] if args.streaming_only else ORDER)])
    (root/'status.json').write_text(json.dumps(state, indent=2))
    def command(script, *argv):
        return shlex.join([sys.executable, '-u', str(HERE/script), *map(str,argv)])
    monitor = command('monitor.py', root)+' >> '+shlex.quote(str(root/'monitor.log'))+' 2>&1'
    scheduler = command('campaign.py', 'run', root, '--jobs', '5')+' >> '+shlex.quote(str(root/'scheduler.log'))+' 2>&1'
    subprocess.run(['tmux','-L','coyote-opt','new-session','-d','-s',session,'-n','monitor',monitor],check=True)
    subprocess.run(['tmux','-L','coyote-opt','new-window','-d','-t',session,'-n','scheduler',scheduler],check=True)
    if args.streaming_only:
        outcome=command('record_outcome.py',root,'--watch')+' >> '+shlex.quote(str(root/'outcome.log'))+' 2>&1'
        subprocess.run(['tmux','-L','coyote-opt','new-window','-d','-t',session,'-n','outcome',outcome],check=True)
    print(f'Run: {root}\nAttach: tmux -L coyote-opt attach -t {session}')

if __name__ == '__main__':
    main()
