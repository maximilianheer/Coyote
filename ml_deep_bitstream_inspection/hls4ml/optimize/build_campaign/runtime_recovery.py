#!/usr/bin/env python3
"""Run fresh-context D_I parity gates on an already installed image; no programming."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
from board_benchmark import REPO,save
from validate_runtime import validate

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);p.add_argument('--attempt',required=True);a=p.parse_args()
    root=a.root.resolve();here=Path(__file__).resolve().parent
    python=REPO/'ml_baseline/.venv_hls4ml/bin/python'
    outputs=[]
    for name,cases,trials in [('sequential','runtime_cases.tsv',10),('alternating_a','alternating_1.tsv',1),('alternating_b','alternating_2.tsv',1)]:
        out=root/'diagnostics'/f'runtime_{a.attempt}_{name}'
        command=[str(python),str(here/'run_diagnostic.py'),str(out),'--',
            'numactl','--physcpubind=2','--membind=0',str(python),str(here/'runtime_benchmark.py'),
            str(root/'diagnostics'/cases),str(out/'observations.csv'),str(out/'clock.csv'),'7',str(trials),'0',
            '--library',str(root/'software/runtime_build/libCoyoteInferenceCampaign.so'),
            '--tolerances',str(root/'production_tolerances.json'),'--diagnostic',
            '--image-manifest',str(root/'installed_image.json')]
        subprocess.run(command,check=False)
        state=json.loads((out/'task_status.json').read_text())
        if state.get('returncode') not in (0,2):raise RuntimeError(f'{name}: runtime failure; inspect {out}')
        outputs.append(out/'observations.csv')
    result=validate(root,outputs[0],outputs[1:])
    print('RUNTIME_GATE',result['status'],len(result['failures']),'failures',flush=True)
    raise SystemExit(result['status']!='passed')
