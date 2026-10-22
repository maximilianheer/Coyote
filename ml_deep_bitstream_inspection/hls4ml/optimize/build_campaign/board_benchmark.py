#!/usr/bin/env python3
"""Prepare and analyze ABI-v3 board trials; never programs a board."""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import random
import statistics
from parity_gate import check_logit, load_tolerances

REPO = Path(__file__).resolve().parents[3]
BUILD = REPO/'hls4ml/optimize/runs/direct_stream_20261008_002352'
OLD = REPO/'hls4ml/optimize/runs/20261001_184524/jobs'
EXACT = [4*2**20, 16*2**20, 64*2**20, 128*2**20-64]
REAL = [(OLD/'HR/build/bitstreams/config_0/vfpga_c0_0.bin'),
        (OLD/'H4/build/bitstreams/config_0/vfpga_c0_0.bin'),
        (OLD/'H16/build/bitstreams/config_0/vfpga_c0_0.bin')]
for iteration, config in [('it1','027'),('it1','109'),('it2','105'),('it4_big_ro','050'),('it4_big_ro','075')]:
    REAL.append(REPO/f'upload_dataset/full_dataset_{iteration}/artifacts/bitstreams/config_{config}/vfpga_c{config}_0.bin')
GPU = [(65536,.19),(262144,.20),(1048576,.25),(4194304,.45),(16777216,1.24),(67108864,4.39),(134217728,8.59)]

def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()

def save(path,value):
    path=Path(path);tmp=path.with_suffix(path.suffix+'.tmp')
    tmp.write_text(json.dumps(value,indent=2)+'\n');tmp.replace(path)

def target(n):
    for (a,x),(b,y) in zip(GPU,GPU[1:]):
        if a<=n<=b:return .9*(x+(y-x)*(n-a)/(b-a))
    raise ValueError('size outside GPU reference range')

def prepare(root):
    cases=[];seed=REAL[0].read_bytes()
    def case(ident,sweep,path,source,recipe):
        cases.append(dict(id=ident,sweep=sweep,path=str(path.resolve()),bytes=path.stat().st_size,
            sha256=sha(path),source=str(source),recipe=recipe))
    for n in EXACT:
        p=root/'inputs'/f'synthetic_{n}.bin'
        with p.open('xb') as f:
            left=n
            while left: chunk=seed[:min(left,len(seed))];f.write(chunk);left-=len(chunk)
        case(f'synthetic_{n}','synthetic',p,REAL[0],'repeat/truncate benign HR; last point 128 MiB minus 64 bytes')
    for p in REAL:
        assert p.stat().st_size>1000000,'missing real bitstream'
        case(f'real_{p.stat().st_size}','real',p,p,'unchanged')
    random.Random(20261002).shuffle(cases)
    smoke=[]
    for n in [0,1,63,64,65,65535,65536,65537,4194240,4194241,4194242]:
        p=root/'inputs'/f'smoke_{n}.bin';p.write_bytes(seed[:n])
        smoke.append(dict(id=f'smoke_{n}',sweep='smoke',path=str(p.resolve()),bytes=n,sha256=sha(p)))
    for c in cases:
        if c['bytes'] in [min(EXACT),max(EXACT),REAL[0].stat().st_size,REAL[-1].stat().st_size]:
            smoke.append(dict(c,id='smoke_'+c['id'],sweep='smoke'))
    manifest=dict(order_seed=20261002,warmups=20,trials=200,cases=cases,smoke=smoke,
        hardware_build=str(BUILD),variants=[7,8],max_raw_bytes=134217664,
        host='hacc-u55c-03',cpu=2,numa_node=0,clock_mhz=250)
    save(root/'inputs.json',manifest)
    return manifest

def attach_reference(root):
    manifest=json.loads((root/'inputs.json').read_text())
    results={}
    for line in (root/'logs/reference.log').read_text().splitlines():
        if line.startswith('RESULT '):
            _,path,bits=line.split();results[path]=bits
    for name in ['cases','smoke']:
        with (root/(name+'.tsv')).open('w') as f:
            for c in manifest[name]:
                if sha(c['path'])!=c['sha256']:raise ValueError('input changed')
                c['expected_logit_hex']=results[c['path']]
                f.write('\t'.join(map(str,[c['id'],c['sweep'],c['path'],c['bytes'],c['sha256'],c['expected_logit_hex']]))+'\n')
    # Short pilot exercises minimum and maximum before admitting the full sweep.
    pilot=[c for c in manifest['cases'] if c['bytes'] in [min(EXACT),max(EXACT)]]
    with (root/'pilot.tsv').open('w') as f:
        for c in pilot:f.write('\t'.join(map(str,[c['id'],c['sweep'],c['path'],c['bytes'],c['sha256'],c['expected_logit_hex']]))+'\n')
    save(root/'inputs.json',manifest)

def clock_model(samples):
    """Feasible affine maps, clipped by every host/FPGA read bracket.

    x and y are relative milliseconds, nominal slope 1; avoids precision loss.
    A block is rejected if no single clock map satisfies all brackets.
    """
    if len(samples)<64 or {r['position'] for r in samples}!={'before','after'}:
        raise ValueError('need 32 before and 32 after calibration reads')
    if any(sum(r['position']==p for r in samples)!=32 for p in ['before','after']):
        raise ValueError('wrong calibration count')
    tick0=int(samples[0]['fpga_tick']);host0=int(samples[0]['host_before_ns'])
    poly=[(.9975,-1000), (1.0025,-1000),(1.0025,1000),(.9975,1000)]
    def clip(poly,a,b,c):
        out=[]
        for u,v in zip(poly,poly[1:]+poly[:1]):
            du=a*u[0]+b*u[1]-c;dv=a*v[0]+b*v[1]-c
            if du<=1e-12:out.append(u)
            if (du<0<dv) or (dv<0<du):
                k=du/(du-dv);out.append((u[0]+k*(v[0]-u[0]),u[1]+k*(v[1]-u[1])))
        return out
    for r in samples:
        x=(int(r['fpga_tick'])-tick0)*4/1e6
        lo=(int(r['host_before_ns'])-host0)/1e6;hi=(int(r['host_after_ns'])-host0)/1e6
        if lo>hi:raise ValueError('reversed clock bracket')
        poly=clip(poly,x,1,hi);poly=clip(poly,-x,-1,-lo)
        if not poly:raise ValueError('inconsistent clock calibration/drift')
    def mapped(tick):
        x=(int(tick)-tick0)*4/1e6
        ys=[a*x+b for a,b in poly]
        return host0+min(ys)*1e6,host0+max(ys)*1e6
    return mapped,dict(ns_per_tick_min=4*min(a for a,b in poly),ns_per_tick_max=4*max(a for a,b in poly),
        model='affine within size block; feasible interval from all MMIO brackets')

def components(row,case,mapped,tick_ns=4.0,tolerance=None,fifo_depth=32,pipeline_mode="streaming"):
    if (pipeline_mode,fifo_depth) not in (("streaming",32),("nonstreaming",65536)):
        raise ValueError("invalid pipeline interface")
    v=int(row['variant']);n=int(row['input_bytes']);r={i:int(row[f'csr_{i}']) for i in range(6,30)}
    if v not in (7,8) or n!=case['bytes'] or row['input_sha256']!=case['sha256']:
        raise ValueError('variant/input identity mismatch')
    if int(row['signature'])!=0x4342595400030000|v or int(row['status'])!=2:
        raise ValueError('wrong ABI or failed FPGA status')
    frame=64+((n+63)//64)*64
    if int(row['transport_bytes'])!=frame or r[20]!=frame//64:raise ValueError('input beat count')
    required=(0x1fc if v==7 else 0x180)|(3 if n else 0)
    if r[7]&required!=required:raise ValueError('missing FPGA events')
    if not r[6]<=r[15] or (n and not r[6]<=r[8]<=r[9]<=r[15]):raise ValueError('invalid raw/verdict ordering')
    # DMA acknowledges receipt upstream of Coyote's stream buffers. A slow
    # preprocessor may accept the final payload beat after that acknowledgment.
    if r[16]<r[6]:raise ValueError('invalid DMA acknowledgment')
    host=[int(row[k]) for k in ['host_start_ns','submit_start_ns','submit_return_ns','host_dma_done_ns','host_verdict_seen_ns']]
    if host!=sorted(host):raise ValueError('invalid host ordering')
    lo,hi=mapped(r[15]);uncertainty=(hi-lo)/1e6
    if hi<host[0] or lo>host[-1]:raise ValueError('verdict outside observed host interval')
    tick_ms=tick_ns/1e6
    d=dict(case_id=case['id'],sweep=case['sweep'],variant=v,input_bytes=n,trial=int(row['trial']),warmup=int(row['warmup']),
        total_lower_ms=(lo-host[0])/1e6,total_upper_ms=(hi-host[0])/1e6,total_ms=((lo+hi)/2-host[0])/1e6,
        clock_uncertainty_ms=uncertainty,host_observed_ms=(host[-1]-host[0])/1e6,
        submission_overhead_ms=(host[1]-host[0])/1e6,dma_call_ms=(host[2]-host[1])/1e6,
        host_dma_observed_ms=(host[3]-host[1])/1e6,arm_to_verdict_ms=(r[15]-r[6])*tick_ms,
        reception_ms=(r[9]-r[8])*tick_ms if n else 0,
        raw_first_ms=(r[8]-r[6])*tick_ms if n else 0,raw_last_ms=(r[9]-r[6])*tick_ms if n else 0,
        input_starve_cycles=r[22],input_backpressure_cycles=r[23],pixel_backpressure_cycles=r[24],cnn_starve_cycles=r[25],fifo_peak=r[29])
    if v==7:
        check_logit(r[26]&0xffffffff,(r[26]>>32)&1,case,tolerance)
        if r[27]!=65536 or r[28]!=65536 or r[29]>fifo_depth:raise ValueError('pixel/FIFO count')
        if not (r[6]<=r[10]<=r[11]<=r[14]<=r[15] and r[10]<=r[12]<=r[13]<=r[14] and r[11]<=r[13]):
            raise ValueError('invalid pipeline event ordering')
        if pipeline_mode=='nonstreaming' and (r[29]!=65536 or r[12]<=r[11] or (n and r[12]<=r[9])):
            raise ValueError('non-streaming full-frame ordering/occupancy')
        d.update(preprocess_ms=(r[11]-(r[8] if n else r[6]))*tick_ms,pixel_span_ms=(r[11]-r[10])*tick_ms,
            inference_ms=(r[14]-r[12])*tick_ms,inference_tail_ms=(r[15]-r[11])*tick_ms,
            overlap_ms=max(0,min(r[11],r[14])-max(r[10],r[12]))*tick_ms,
            pp_first_ms=(r[10]-r[6])*tick_ms,pp_last_ms=(r[11]-r[6])*tick_ms,
            cnn_first_ms=(r[12]-r[6])*tick_ms,logit_ms=(r[14]-r[6])*tick_ms,
            publication_ms=(r[15]-r[14])*tick_ms)
    return d

def percentile(xs,q):
    xs=sorted(xs);p=(len(xs)-1)*q;i=int(p);return xs[i]+(xs[min(i+1,len(xs)-1)]-xs[i])*(p-i)

def write_csv(path,rows):
    with Path(path).open('w') as f:
        fields=list(dict.fromkeys(k for row in rows for k in row));w=csv.DictWriter(f,fields);w.writeheader();w.writerows(rows)

def analyze(root,attempt,mode='full'):
    manifest=json.loads((root/'inputs.json').read_text())
    cases=manifest['smoke' if mode=='smoke' else 'cases']
    if mode=='pilot':cases=[c for c in cases if c['bytes'] in [min(EXACT),max(EXACT)]]
    trials,warmups=(200,20) if mode=='full' else ((10,2) if mode=='pilot' else (2,0))
    raw=list(csv.DictReader((attempt/f'{mode}.csv').open()))
    cal=list(csv.DictReader((attempt/f'{mode}.clock.csv').open()))
    tolerances=None
    if (root/'production_tolerances.json').exists():
        tolerances=load_tolerances(root/'production_tolerances.json')
    if {r['case_id'] for r in raw}!={c['id'] for c in cases}:raise ValueError('incomplete case grid')
    if len({r['variant'] for r in raw})!=1:raise ValueError('mixed variants')
    tags=[int(r['trial_tag']) for r in raw]
    if len(tags)!=len(set(tags)):raise ValueError('duplicate trial tag')
    derived=[];summary=[];clocks={}
    for c in cases:
        if sha(c['path'])!=c['sha256']:raise ValueError('input hash mismatch')
        rows=[r for r in raw if r['case_id']==c['id']]
        if len(rows)!=trials+warmups or sorted(int(r['trial']) for r in rows)!=list(range(trials+warmups)):
            raise ValueError('missing/duplicate trials')
        if any(int(r['warmup'])!=int(int(r['trial'])<warmups) for r in rows):raise ValueError('incorrect warm-up labels')
        mapped,details=clock_model([r for r in cal if r['case_id']==c['id']]);clocks[c['id']]=details
        tick_ns=(details['ns_per_tick_min']+details['ns_per_tick_max'])/2
        tolerance=tolerances[c['sha256']] if tolerances is not None and rows[0]['variant']=='7' else None
        ds=[components(r,c,mapped,tick_ns,tolerance) for r in rows];derived+=ds
        cap=target(c['bytes']) if c['bytes']>=65536 else None
        uncertainty=max(d['clock_uncertainty_ms'] for d in ds)
        if mode!='smoke' and uncertainty>cap*.01:raise ValueError('clock uncertainty exceeds 1% target')
        measured=[d for d in ds if not d['warmup']];xs=[d['total_ms'] for d in measured]
        item=dict(case_id=c['id'],sweep=c['sweep'],variant=ds[0]['variant'],input_bytes=c['bytes'],measured=len(measured),
            warmups=warmups,median_ms=statistics.median(xs),p95_ms=percentile(xs,.95),max_ms=max(xs),
            all_calls_median_ms=statistics.median(d['total_ms'] for d in ds),all_calls_p95_ms=percentile([d['total_ms'] for d in ds],.95),
            first_call_ms=ds[0]['total_ms'],clock_uncertainty_ms=uncertainty,target_ms=cap)
        if mode=='full':
            # 196th order statistic: >=95% one-sided coverage for population p95, n=200.
            item['p95_upper95_ms']=sorted(d['total_upper_ms'] for d in measured)[195]
            item['meets_pdf_target']=item['p95_upper95_ms']<=cap
        for key in measured[0]:
            if key.endswith('_ms') or key.endswith('_cycles') or key=='fifo_peak':
                item['median_'+key]=statistics.median(d[key] for d in measured)
        summary.append(item)
    write_csv(attempt/f'{mode}.derived.csv',derived);write_csv(attempt/f'{mode}.summary.csv',summary)
    result=dict(status='passed',mode=mode,trials=len(raw),cases=len(cases),clock_models=clocks,
        measurement='host before arm/submission to calibrated FPGA verdict; affine clock model within block',
        statistics='per-case, one-session; no independent cold-start or between-session claim',
        gpu_comparison='PDF reference only; 128 MiB point uses 64 fewer payload bytes',summary=summary)
    result['parity_policy']='production-matched per-input tolerance' if tolerances is not None else 'exact logits'
    if tolerances is not None:result['tolerances_sha256']=sha(root/'production_tolerances.json')
    metadata=attempt/f'{mode}.status.json'
    if mode=='full' and metadata.exists():
        collection=json.loads(metadata.read_text())
        if collection.get('status')!='passed' or collection.get('diagnostic'):
            raise ValueError('Only accepted benchmark collection can bind routed resources')
        from resource_attribution import installed_resources
        resources=installed_resources(root/'installed_image.json',collection['hardware_identity'])
        save(attempt/'full.resources.json',resources)
        result['routed_resources']='full.resources.json'
    save(attempt/f'{mode}.analysis.json',result)
    return result

def plots(root,attempts):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    summaries=[];derived=[]
    for p in attempts:
        summaries+=json.loads((p/'full.analysis.json').read_text())['summary']
        derived+=list(csv.DictReader((p/'full.derived.csv').open()))
    fig,axes=plt.subplots(1,2,figsize=(11,4))
    for ax,sweep in zip(axes,['synthetic','real']):
        for variant,name in [(7,'Checker'),(8,'Sink')]:
            rows=sorted((r for r in summaries if r['sweep']==sweep and r['variant']==variant),key=lambda r:r['input_bytes'])
            ax.plot([r['input_bytes']/2**20 for r in rows],[r['median_ms'] for r in rows],'-o',label=name+' median')
            ax.plot([r['input_bytes']/2**20 for r in rows],[r['p95_upper95_ms'] for r in rows],'--',label=name+' p95 upper bound')
        rows=sorted((r for r in summaries if r['sweep']==sweep and r['variant']==7),key=lambda r:r['input_bytes'])
        ax.plot([r['input_bytes']/2**20 for r in rows],[r['target_ms'] for r in rows],':',label='90% PDF GPU median')
        ax.set(title=sweep,xlabel='Raw input (MiB)',ylabel='Host start to FPGA verdict (ms)');ax.legend(fontsize=8)
    fig.tight_layout();fig.savefig(root/'latency_vs_size.png',dpi=160);plt.close(fig)
    ids=sorted({r['case_id'] for r in derived if r['variant']=='7'},key=lambda k:(next(r['sweep'] for r in derived if r['case_id']==k),int(next(r['input_bytes'] for r in derived if r['case_id']==k))))
    fig,ax=plt.subplots(figsize=(11,8))
    for i,ident in enumerate(ids):
        rows=sorted((r for r in derived if r['case_id']==ident and r['variant']=='7' and r['warmup']=='0'),key=lambda r:float(r['total_ms']))
        r=rows[len(rows)//2]
        for j,(a,b,color,label) in enumerate([('raw_first_ms','raw_last_ms','tab:blue','Reception'),('pp_first_ms','pp_last_ms','tab:orange','Pixel production'),('cnn_first_ms','logit_ms','tab:green','CNN including waits')]):
            ax.broken_barh([(float(r[a]),float(r[b])-float(r[a]))],(i*4+j,.8),facecolors=color,label=label if i==0 else None)
    ax.set(yticks=[i*4+1 for i in range(len(ids))],yticklabels=ids,xlabel='Milliseconds after FPGA arm');ax.legend();fig.tight_layout();fig.savefig(root/'overlap_timeline.png',dpi=160);plt.close(fig)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['prepare','reference','analyze','plots']);p.add_argument('root',type=Path);p.add_argument('--attempt',type=Path);p.add_argument('--mode',default='full',choices=['full','pilot','smoke']);p.add_argument('--attempts',type=Path,nargs='*')
    a=p.parse_args()
    if a.action=='prepare':prepare(a.root.resolve())
    elif a.action=='reference':attach_reference(a.root.resolve())
    elif a.action=='analyze':print(json.dumps(analyze(a.root.resolve(),a.attempt.resolve(),a.mode),indent=2))
    else:plots(a.root.resolve(),a.attempts)
