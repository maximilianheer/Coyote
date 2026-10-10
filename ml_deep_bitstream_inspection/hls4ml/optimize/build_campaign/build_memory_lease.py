#!/usr/bin/env python3
"""Temporarily release unused hugepages for this build campaign, then restore them."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import subprocess
import time
from worker import save

def memory():
    return {k:int(v.split()[0]) for k,v in
            (line.split(':',1) for line in Path('/proc/meminfo').read_text().splitlines())}

def set_pages(count, log):
    # This exact sysfs target is explicitly permitted by the host sudo policy.
    # Generic sysctl writes require authentication on this machine.
    return subprocess.run(['sudo','-n','/usr/bin/tee',
        '/sys/kernel/mm/hugepages/hugepages-2048kB/nr_hugepages'],
        input=str(count)+'\n',text=True,stdout=log,stderr=subprocess.STDOUT)

def run(root):
    path=root/'memory_lease.json'
    with (root/'memory_lease.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if path.exists():raise RuntimeError('Preserve existing lease; do not replace its restoration target')
        mem=memory();original=mem['HugePages_Total'];target=2048
        if original!=8192 or mem['Hugepagesize']!=2048 or mem['HugePages_Free']!=original or mem['HugePages_Rsvd']:
            raise RuntimeError('Expected 16 GiB entirely unused 2-MiB hugepages; no change made')
        state=dict(status='prepared',pid=os.getpid(),started_at=time.time(),original_pages=original,
                   temporary_pages=target,page_size_kib=2048,meminfo_before=mem,
                   backend='sudo-permitted 2-MiB sysfs hugepage count')
        save(path,state)
        with (root/'memory_lease.log').open('a') as log:
            changed=set_pages(target,log)
        now=memory()
        if changed.returncode or now['HugePages_Total']!=target:
            state.update(status='apply_failed',meminfo_after=now);save(path,state)
            if now['HugePages_Total']==original:return 1
            # A partial kernel adjustment still requires restoration below.
        else:
            state.update(status='leased',meminfo_after=now);save(path,state)
        while True:
            queue=json.loads((root/'status.json').read_text())
            mem=memory();state.update(heartbeat=time.time(),available_kib=mem['MemAvailable'])
            if queue.get('phase')=='finished' or state['status']=='apply_failed':
                needed=max(0,original-mem['HugePages_Total'])*2048+8*1024**2
                if mem['MemAvailable']>=needed:
                    with (root/'memory_lease.log').open('a') as log:
                        set_pages(original,log)
                    mem=memory()
                    if mem['HugePages_Total']==original:
                        state.update(status='restored',restored_at=time.time(),meminfo_restored=mem)
                        save(path,state);return 0
                    state.update(status='restoring',last_restore_attempt=time.time())
            save(path,state);time.sleep(30)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path)
    raise SystemExit(run(p.parse_args().root.resolve()))
