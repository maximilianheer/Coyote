#!/usr/bin/env python3
"""Track a bounded diagnostic in tmux; diagnostic jobs do not send ntfy alerts."""
import argparse
import os
from pathlib import Path
import signal
import subprocess
import time
from board_benchmark import save

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('directory',type=Path);p.add_argument('--timeout',type=int,default=600)
    p.add_argument('command',nargs=argparse.REMAINDER);a=p.parse_args()
    command=a.command[1:] if a.command and a.command[0]=='--' else a.command
    a.directory.mkdir(parents=True,exist_ok=False)
    state=dict(status='running',pid=os.getpid(),command=command,started_at=time.time())
    with (a.directory/'task.log').open('w') as log:
        # Own process group for tree cleanup, retaining tmux's controlling TTY for sudo.
        child=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT,preexec_fn=os.setpgrp)
        state['child_pid']=child.pid
        try:
            while child.poll() is None:
                state['heartbeat']=time.time();save(a.directory/'task_status.json',state)
                if time.time()-state['started_at']>a.timeout: raise TimeoutError('diagnostic timeout')
                time.sleep(1)
            state.update(status='finished' if child.returncode==0 else 'failed',returncode=child.returncode)
        except BaseException as e:
            os.killpg(child.pid,signal.SIGTERM)
            try:child.wait(timeout=5)
            except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL);child.wait()
            state.update(status='failed',error=str(e),returncode=child.returncode)
    state['finished_at']=time.time();save(a.directory/'task_status.json',state)
    raise SystemExit(0 if state['status']=='finished' else 1)
