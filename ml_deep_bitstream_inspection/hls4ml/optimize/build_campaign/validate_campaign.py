#!/usr/bin/env python3
"""Validate prepared diagnostic attempts while hardware dispatch is paused."""
import argparse
from pathlib import Path
import subprocess
import sys
import time
from monitor import notify
from prepare import VARIANTS
from worker import save

HERE=Path(__file__).resolve().parent

def main(root):
    if not (root/'dispatch_paused').exists():
        raise RuntimeError('Pause dispatch before campaign-wide validation')
    result=dict(started_at=time.time(),status='running',jobs={})
    path=root/'refactor_validation.json'
    save(path,result)
    for ident in VARIANTS:
        jobdir=root/'jobs'/ident
        print(f'Validating {ident}',flush=True)
        with (jobdir/'preflight.log').open('w') as log:
            rc=subprocess.run([sys.executable,'-u',str(HERE/'worker.py'),str(jobdir),
                               '--validate-only'],stdout=log,stderr=subprocess.STDOUT).returncode
        result['jobs'][ident]='passed' if rc==0 else 'failed'
        save(path,result)
        if rc:
            result.update(status='failed',finished_at=time.time());save(path,result)
            notify(root,f'Refactor validation failed for {ident}. Dispatch remains paused. See {jobdir}/preflight.log')
            return 1
    result.update(status='passed',finished_at=time.time());save(path,result)
    notify(root,'Refactor validation passed for I/U/N/P/C: preprocessing boundaries, CNN/checksum parity, host compilation and control RTL/ABI simulation. Fresh builds are ready for queue resumption; synthesis equivalence is not established.')
    return 0

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('root',type=Path)
    sys.exit(main(parser.parse_args().root.resolve()))
