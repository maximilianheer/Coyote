#!/usr/bin/env python3
"""Publish the correctness gate only after sequential and recreated/alternating trials."""
import argparse
from collections import Counter
import csv
import json
from pathlib import Path
from board_benchmark import components,clock_model,save,sha
from parity_gate import load_tolerances
from runtime_benchmark import read_cases
from benchmark_identity import installed_identity


def validate(root,sequential,alternating):
    cases={c['sha256']:c for c in read_cases(root/'diagnostics/runtime_cases.tsv')}
    tolerances=load_tolerances(root/'production_tolerances.json')
    library=root/'software/runtime_build/libCoyoteInferenceCampaign.so'
    identity=installed_identity(root/'installed_image.json',7)
    failures=[];records=[]
    if len(alternating)<2:raise ValueError('two recreated sessions required for alternating validation')
    for label,files in [('sequential',[sequential]),('alternating',alternating)]:
        counts=Counter()
        for file in files:
            state=json.loads(file.with_suffix('.status.json').read_text())
            if state.get('hardware_identity')!=identity:
                raise ValueError('Parity evidence belongs to a different bitstream/driver/source')
            if state['library_sha256']!=sha(library) or state['allocation']!='HPF':
                raise ValueError('runtime binary/allocation differs from benchmark configuration')
            with file.open() as source:rows=list(csv.DictReader(source))
            with (file.parent/'clock.csv').open() as source:calibration=list(csv.DictReader(source))
            tags=[int(r['trial_tag']) for r in rows]
            if len(set(tags))!=len(tags):raise ValueError('repeated trial tag within session')
            for ident in dict.fromkeys(r['case_id'] for r in rows):
                block=[r for r in rows if r['case_id']==ident]
                mapped,detail=clock_model([r for r in calibration if r['case_id']==ident])
                tick=(detail['ns_per_tick_min']+detail['ns_per_tick_max'])/2
                for row in block:
                    c=cases[row['input_sha256']];counts[c['sha256']]+=1
                    try:components(row,c,mapped,tick,tolerances[c['sha256']])
                    except ValueError as e:failures.append(dict(workload=label,case_id=ident,error=str(e)))
            records.append(dict(csv=str(file),sha256=sha(file)))
        if counts!=Counter({key:10 for key in cases}):raise ValueError(f'{label}: incomplete 10-repeat input coverage')
    result=dict(status='failed' if failures else 'passed',library_sha256=sha(library),
        coyote_library_sha256=sha(library.parent/'coyote/libcoyote.so'),
        tolerances_sha256=sha(root/'production_tolerances.json'),
        cases_sha256=sha(root/'diagnostics/runtime_cases.tsv'),
        diagnostic_inputs=len(cases),records=records,failures=failures,hardware_identity=identity)
    current=root/'runtime_validation.json'
    if current.exists():
        history=root/'runtime_validation_history';history.mkdir(exist_ok=True)
        preserved=history/(sha(current)+'.json')
        if not preserved.exists():preserved.write_bytes(current.read_bytes())
    save(current,result)
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);p.add_argument('--sequential',type=Path,required=True)
    p.add_argument('--alternating',type=Path,nargs='+',required=True);a=p.parse_args()
    r=validate(a.root,a.sequential,a.alternating);print(r['status'],len(r['failures']),'failures')
    raise SystemExit(r['status']!='passed')
