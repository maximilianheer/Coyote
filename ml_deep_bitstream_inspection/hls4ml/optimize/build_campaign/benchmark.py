#!/usr/bin/env python3
"""Prepare the fixed input grid and analyze later board CSVs; never programs hardware."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import random
import shlex
import shutil
import statistics

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
SIZES = [30323588, 33945471, 37567355, 41189238, 44811122, 48433005, 52054889, 55676772]
ENDPOINTS = [REPO/'upload_dataset/full_dataset_it1/artifacts/bitstreams/config_027/vfpga_c027_0.bin',
             REPO/'upload_dataset/full_dataset_it4_big_ro/artifacts/bitstreams/config_075/vfpga_c075_0.bin']

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def prepare(root, executable):
    root.mkdir(parents=True, exist_ok=False)
    seed = ENDPOINTS[0].read_bytes()
    assert len(seed)==SIZES[0] and ENDPOINTS[1].stat().st_size==SIZES[-1]
    cases=[]
    for i,n in enumerate(SIZES):
        p=root/f'input_{n}.bin'
        if i in (0,7): shutil.copy2(ENDPOINTS[i==7],p)
        else: p.write_bytes((seed*((n+len(seed)-1)//len(seed)))[:n])
        cases.append(dict(bytes=n,path=str(p.resolve()),sha256=sha(p),
            kind='real endpoint' if i in (0,7) else 'synthetic timing input',
            source=str(ENDPOINTS[i==7] if i in (0,7) else ENDPOINTS[0]),
            recipe='unchanged' if i in (0,7) else 'repeat benign minimum endpoint then truncate'))
    order=list(range(8));random.Random(20261002).shuffle(order)
    manifest=dict(batch_size=1,warmups=20,trials=200,total_calls=1760,order_seed=20261002,
        order=order,cases=cases,hardware_status='deferred',
        endpoint_sha256=[sha(p) for p in ENDPOINTS])
    (root/'inputs.json').write_text(json.dumps(manifest,indent=2)+'\n')
    # Explicit invocation is required later. There is no program/load command.
    lines=['#!/usr/bin/env bash','set -euo pipefail',
           '# Run only after explicitly authorized board programming and clock verification.']
    for i in order:
        case=cases[i]
        lines.append(shlex.join([str(executable),case['path'],str((root/f"trials_{case['bytes']}.csv").resolve()),'200','20']))
    (root/'run_later.sh').write_text('\n'.join(lines)+'\n')
    return manifest

def percentile(values, q):
    xs=sorted(values);position=(len(xs)-1)*q;i=int(position)
    return xs[i]+(xs[min(i+1,len(xs)-1)]-xs[i])*(position-i)

def components(row):
    r={k:int(v) for k,v in row.items() if v!=''}
    d=dict(total=r['decision_cycles'],starvation=r['input_starve_cycles'],backpressure=r['input_backpressure_cycles'])
    if r.get('abi_version')==2:
        flags=r['event_flags']
        if flags&0x6f != 0x6f or r['produced_tokens']!=65536: raise ValueError('incomplete stage/ack events or token count')
        ps,pe,cs,logit=[r[k] for k in ('pp_start_cycles','pp_end_cycles','cnn_task_start_cycles','logit_cycles')]
        if not(ps<=pe<=r['decision_cycles'] and cs<=logit<=r['decision_cycles']): raise ValueError('invalid stage timestamps')
        d.update(preprocess=pe-ps,inference=logit-cs,publication=r['decision_cycles']-logit,
            overlap=max(0,min(pe,logit)-max(ps,cs)),tokens=r['produced_tokens'])
        if flags&128:
            d.update(reception=r['payload_last_cycles']-r['payload_first_cycles'],
                     last_byte_to_decision=r['decision_cycles']-r['payload_last_cycles'])
    else:
        d.update(preprocess=r['preprocess_cycles'],inference=r['inference_cycles'],publication=r['publish_cycles'])
    return d

def summarize(root, csv_paths, clock_mhz, reference_paths=(), manifest_path=None, reference_provenance=None):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    if clock_mhz<=0: raise ValueError('implemented clock must be positive')
    manifest=json.loads(manifest_path.read_text()) if manifest_path else None
    if manifest:
        for case in manifest['cases']:
            if sha(Path(case['path']))!=case['sha256']: raise ValueError('input hash mismatch')
    provenance=json.loads(reference_provenance.read_text()) if reference_provenance else {}
    if reference_paths and (not manifest or not provenance):
        raise ValueError('reference comparison requires input manifest and reference provenance')
    rows=[]
    for path in [*csv_paths,*reference_paths]:
        with path.open() as f: rows.extend(csv.DictReader(f))
    groups={}
    for row in rows:
        key=(int(row['variant']),int(row['input_bytes']))
        groups.setdefault(key,[]).append(row)
    if reference_paths:
        wanted={str(c['bytes']):c['sha256'] for c in manifest['cases']}
        for variant in {v for v,n in groups if v!=6}:
            if variant not in (1,3): raise ValueError('only sequential I and transport N references are in scope')
            entry=provenance.get(str(variant),{})
            if entry.get('input_sha256')!=wanted or entry.get('clock_mhz')!=clock_mhz:
                raise ValueError(f'reference {variant} input hashes/clock do not match')
            if not isinstance(entry.get('same_ila'),bool): raise ValueError('reference ILA provenance missing')
            if {n for v,n in groups if v==variant}!=set(SIZES): raise ValueError('reference grid incomplete')
    root.mkdir(parents=True,exist_ok=False)
    with (root/'per_trial.csv').open('w') as f:
        fields=list(dict.fromkeys(k for r in rows for k in r))
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
    summary=[]; medians={}
    for (variant,n),trials in sorted(groups.items()):
        if n not in SIZES: raise ValueError('unexpected input size')
        measured=[r for r in trials if int(r['warmup'])==0]
        if len(trials)!=220 or len(measured)!=200 or len({int(r['trial']) for r in trials})!=220:
            raise ValueError(f'need exactly 20 warmups + 200 unique measured trials for {variant},{n}')
        ds=[components(r) for r in measured]
        item=dict(variant=variant,input_bytes=n,median_total_ms=statistics.median(d['total'] for d in ds)/clock_mhz/1000,
            p95_total_ms=percentile([d['total'] for d in ds],.95)/clock_mhz/1000,
            max_total_ms=max(d['total'] for d in ds)/clock_mhz/1000)
        for name in ds[0]: item['median_'+name+'_cycles']=statistics.median(d[name] for d in ds)
        summary.append(item);medians[variant,n]=measured
    if {n for v,n in groups if v==6}!=set(SIZES): raise ValueError('S_I requires all eight sizes')
    with (root/'per_size.csv').open('w') as f:
        fields=list(dict.fromkeys(k for r in summary for k in r));w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(summary)
    fig,ax=plt.subplots()
    for v in sorted({v for v,n in groups}):
        rs=[r for r in summary if r['variant']==v]
        ax.plot([r['input_bytes']/1e6 for r in rs],[r['median_total_ms'] for r in rs],'-o',label=f'ID {v} median')
        ax.plot([r['input_bytes']/1e6 for r in rs],[r['p95_total_ms'] for r in rs],'--',label=f'ID {v} p95')
    ax.set(xlabel='Raw input (MB)',ylabel='Request to decision (ms)');ax.legend();fig.tight_layout();fig.savefig(root/'latency_vs_size.png');plt.close(fig)
    fig,ax=plt.subplots(figsize=(10,7))
    colors=['tab:blue','tab:orange','tab:green','tab:red']
    for idx,n in enumerate(SIZES):
        rs=medians[6,n];r=sorted(rs,key=lambda r:int(r['decision_cycles']))[len(rs)//2]
        spans=[('payload_first_cycles','payload_last_cycles'),('pp_start_cycles','pp_end_cycles'),
               ('cnn_task_start_cycles','logit_cycles'),('logit_cycles','decision_cycles')]
        for j,(a,b) in enumerate(spans):
            start=int(r[a])/clock_mhz/1000;width=(int(r[b])-int(r[a]))/clock_mhz/1000
            ax.broken_barh([(start,width)],(idx*5+j,.8),facecolors=colors[j])
    from matplotlib.patches import Patch
    ax.legend(handles=[Patch(color=c,label=l) for c,l in zip(colors,['Reception','Preprocessing','CNN task (includes waits)','Publication'])])
    ax.set(yticks=[i*5+1.5 for i in range(8)],yticklabels=[f'{n:,}' for n in SIZES],xlabel='Milliseconds after accepted request',ylabel='Raw bytes; one median-ranked trial per size')
    fig.tight_layout();fig.savefig(root/'overlap_timeline.png');plt.close(fig)
    largest=next(r for r in summary if r['variant']==6 and r['input_bytes']==SIZES[-1])
    pressure=largest['median_backpressure_cycles'];starve=largest['median_starvation_cycles']
    recommendation=('Investigate the input reader/memory service first.' if starve>pressure else
                    'Inspect CNN input service rate and buffering before reducing FIFO depths.')
    analysis=dict(clock_mhz=clock_mhz,measurement_scope='board: accepted request to captured decision',
        references_present=sorted({v for v,n in groups if v!=6}),
        reference_matching='Input hashes and implemented clock matched' if reference_paths else 'No matching board references supplied',
        reference_provenance=provenance,
        bottleneck=f'Largest input median starvation={starve} cycles, backpressure={pressure} cycles. {recommendation}',
        interpretation='Overlapping durations are not additive. Final-byte-to-decision is incremental deployment delay only if checking does not extend reception versus matching transport-only measurements.')
    (root/'analysis.json').write_text(json.dumps(analysis,indent=2)+'\n')

if __name__=='__main__':
    p=argparse.ArgumentParser();sub=p.add_subparsers(dest='action',required=True)
    a=sub.add_parser('prepare');a.add_argument('root',type=Path);a.add_argument('--executable',type=Path,required=True)
    a=sub.add_parser('summarize');a.add_argument('root',type=Path);a.add_argument('csv',type=Path,nargs='+');a.add_argument('--clock-mhz',type=float,required=True);a.add_argument('--reference',type=Path,nargs='*',default=[]);a.add_argument('--manifest',type=Path);a.add_argument('--reference-provenance',type=Path)
    args=p.parse_args()
    if args.action=='prepare': prepare(args.root.resolve(),args.executable.resolve())
    else: summarize(args.root,args.csv,args.clock_mhz,args.reference,args.manifest,args.reference_provenance)
