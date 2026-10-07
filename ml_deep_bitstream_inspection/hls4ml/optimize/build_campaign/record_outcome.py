#!/usr/bin/env python3
"""Persist a terminal S_I build outcome and notify the authorized ntfy topic."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import time
import xml.etree.ElementTree as ET
from monitor import notify
from worker import save

HERE=Path(__file__).resolve().parent
MARKER='<!-- S_I_BUILD_OUTCOME -->'

def record(root):
    state=json.loads((root/'status.json').read_text())
    job=next(j for j in state['jobs'] if j['id']=='S_I')
    if job['status'] not in ('passed','failed','blocked'): return False
    directory=root/'jobs/S_I'; build=directory/'build'
    report=dict(recorded_at=time.time(),run=str(root),job=job,board_programmed=False,
        board_benchmarked=False,shared_debug_overhead='ILA v6.2; one 1-bit probe, depth 1024, accepted card-input beat; included in design totals',
        hls_estimates=[],routed_reports=[],evidence={})
    for p in build.rglob('model_wrapper_csynth.xml'):
        if '/syn/report/' not in str(p): continue
        tree=ET.parse(p)
        report['hls_estimates'].append(dict(path=str(p),
            resources={e.tag:e.text for e in tree.findall('./AreaEstimates/Resources/*')},
            timing={e.tag:e.text for e in tree.findall('./PerformanceEstimates/SummaryOfTimingAnalysis/*')}))
    for p in (build/'reports').rglob('*.rpt'):
        if 'util' in p.name or 'timing' in p.name:
            report['routed_reports'].append(dict(path=str(p),sha256=hashlib.sha256(p.read_bytes()).hexdigest()))
    for name in ['source_manifest.json','validation.json','csim.log','rtl_simulate.log',
                 'streaming_control_simulate.log','streaming_rtl_simulate.log','bitgen.log']:
        p=directory/name
        if p.exists(): report['evidence'][name]=dict(path=str(p),sha256=hashlib.sha256(p.read_bytes()).hexdigest())
    save(root/'build_outcome.json',report)
    plan=HERE.parent/'OPTIMIZATION_PLAN.md'
    text=plan.read_text().split(MARKER)[0].rstrip()
    suffix=f'''\n\n{MARKER}
## Recorded build outcome

Run `{root.name}`: **{job['status']}**, stage `{job.get('stage','unknown')}`.
{job.get('error','')}

Evidence, HLS estimates, routed report locations, and source/log hashes:
[`build_outcome.json`](runs/{root.name}/build_outcome.json).
This is a build outcome; board programming and benchmarking remain deferred.
'''
    plan.write_text(text+suffix)
    message=(f"S_I ID 6 build outcome: {job['status']} at {job.get('stage')}. "
             f"{job.get('error','')}\nEvidence/resources: {root/'build_outcome.json'}\n"
             f"Logs/artifacts: {directory}\nNo board programming or benchmarking performed.")
    while not notify(root,message): time.sleep(30)
    return True

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('root',type=Path);parser.add_argument('--watch',action='store_true');a=parser.parse_args()
    while not record(a.root.resolve()):
        if not a.watch: raise SystemExit('Build is not terminal yet')
        time.sleep(30)
