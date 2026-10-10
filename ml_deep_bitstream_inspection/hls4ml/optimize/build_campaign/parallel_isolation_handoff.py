#!/usr/bin/env python3
"""Adopt an idle R_S worker at its validated synthesis boundary, without rebuilding IP."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import time
from prepare import verify_sources, sha
from worker import save

HERE=Path(__file__).resolve().parent

def children(pid):
    return [int(p) for p in Path(f'/proc/{pid}/task/{pid}/children').read_text().split()]

def handoff(root):
    jobdir=root/'jobs/R_S'; path=root/'parallel_handoff.json'
    state=dict(status='waiting', pid=os.getpid(), started_at=time.time())
    save(path,state)
    with (root/'parallel_handoff.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        while True:
            progress=json.loads((jobdir/'progress.json').read_text())
            state.update(heartbeat=time.time(), observed_stage=progress.get('stage'));save(path,state)
            if progress.get('parallel_synthesis'):
                state.update(status='already_applied');save(path,state);return
            if progress['status']!='running':
                state.update(status='not_needed', reason='Worker finished before a safe handoff');save(path,state);return
            if progress['stage']=='waiting_memory_synth' and not children(progress['pid']):break
            # Never interrupt a running tool, even if it has crossed this boundary.
            if progress['stage'] in ('synth','link','shell','bitgen','complete'):
                state.update(status='not_applied', reason='Worker already crossed safe boundary');save(path,state);return
            time.sleep(2)
        worker_pid=progress['pid']
        queue=json.loads((root/'status.json').read_text());scheduler_pid=queue['scheduler_pid']
        for pid, script, argument in [(worker_pid,'worker.py',jobdir), (scheduler_pid,'campaign.py',root)]:
            cmdline=Path(f'/proc/{pid}/cmdline').read_bytes().replace(b'\0',b' ').decode()
            if script not in cmdline or str(argument) not in cmdline:
                raise RuntimeError('PID identity changed; refusing handoff')
        os.kill(scheduler_pid,signal.SIGSTOP)
        worker_stopped=False; replacement=False
        try:
            os.kill(worker_pid,signal.SIGSTOP);worker_stopped=True
            snapshot=json.loads((jobdir/'progress.json').read_text())
            if snapshot['stage']!='waiting_memory_synth' or children(worker_pid):
                raise RuntimeError('Worker crossed boundary; keep original worker running')
            digest=verify_sources(jobdir)
            validation=json.loads((jobdir/'validation.json').read_text())
            if validation['status']!='passed' or validation['source_manifest_sha256']!=digest:
                raise RuntimeError('Validation identity mismatch')
            if 'PASS production wrapper frames=8' not in (jobdir/'wrapper_rtl.log').read_text():
                raise RuntimeError('Wrapper RTL gate incomplete')
            archive=jobdir/'scheduling_handoff';archive.mkdir(exist_ok=False)
            save(archive/'previous_progress.json',snapshot)
            save(archive/'previous_queue.json',queue)
            # Only scheduling in the generated, not-yet-executed Tcl changes.
            anchor='launch_runs -jobs 1 -verbose synth_1'
            scripts={name:(jobdir/'build'/name).read_text() for name in ['synth_shell.tcl','synth_user.tcl']}
            if any(text.count(anchor)!=1 for text in scripts.values()):
                raise RuntimeError('Unexpected synthesis launcher')
            hashes={}
            for name,before in scripts.items():
                script=jobdir/'build'/name
                saved=archive/(script.stem+'.before.tcl');saved.write_text(before)
                script.write_text(before.replace(anchor,'set_param general.maxThreads 1\nlaunch_runs -jobs 2 -verbose synth_1'))
                hashes[name]=dict(before_sha256=sha(saved),after_sha256=sha(script))
            save(archive/'configuration.json',dict(source_manifest_sha256=digest,
                scheduling_only=True, synthesis_jobs=2, synthesis_tool_threads=1, implementation_tool_threads=4,
                parallel_stage_min_available_gib=24, serialized_place_route=True,
                stage_peak_reservations_gib={'synth':12,'link':12,'bitgen':12},
                other_build_peak_reservations_gib={'synth':24,'implementation':20}, memory_margin_gib=8,
                generated_scripts=hashes))
            # The idle Python controller has no subprocesses. All HLS/IP/RTL work
            # remains intact; no hardware build is terminated or restarted here.
            os.kill(worker_pid,signal.SIGTERM);os.kill(worker_pid,signal.SIGCONT);worker_stopped=False
            for _ in range(100):
                if not Path(f'/proc/{worker_pid}').exists():break
                time.sleep(.1)
            else:raise RuntimeError('Old idle worker did not exit')
            command=shlex.join(['env','ISOLATION_RESUME_STAGE=synth',sys.executable,'-u',str(HERE/'worker.py'),str(jobdir)])
            command+=' >> '+shlex.quote(str(jobdir/'worker_parallel.log'))+' 2>&1'
            subprocess.run(['tmux','-L','coyote-opt','new-window','-d','-t',queue['tmux_session'],
                            '-n','R_S_parallel',command],check=True)
            for _ in range(100):
                fresh=json.loads((jobdir/'progress.json').read_text())
                if fresh['pid']!=worker_pid:break
                time.sleep(.1)
            else:raise RuntimeError('Replacement worker did not publish PID')
            replacement=True
            state.update(status='applied', old_pid=worker_pid, new_pid=fresh['pid'],
                         applied_at=time.time(), configuration=str(archive/'configuration.json'))
            save(path,state)
        except Exception as error:
            state.update(status='failed', error=str(error), replacement_started=replacement);save(path,state)
            raise
        finally:
            if worker_stopped:os.kill(worker_pid,signal.SIGCONT)
            os.kill(scheduler_pid,signal.SIGCONT)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('root',type=Path)
    handoff(parser.parse_args().root.resolve())
