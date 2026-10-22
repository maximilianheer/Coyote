#!/usr/bin/env python3
"""OPT ABI-v3 collector: exact parity, calibrated FPGA ticks, explicit e2e scopes."""
import argparse, csv, ctypes as ct, json, random, statistics, time, sys
from pathlib import Path
import numpy as np
sys.path.append(str(Path(__file__).resolve().parents[2]/'pipeline/coyote_accelerator'))
from direct_session import DirectCoyoteSession
from board_benchmark import sha, save, components, clock_model, percentile
from parity_gate import check_logit
from host_environment import record


def read_cases(path):
    cases=[]
    for line in path.read_text().splitlines():
        if not line or line.startswith('#'):continue
        ident,sweep,file,n,digest,expected=line.split('\t');p=Path(file)
        if p.stat().st_size!=int(n) or sha(p)!=digest:raise ValueError('Input changed: '+file)
        cases.append(dict(id=ident,sweep=sweep,path=file,bytes=int(n),sha256=digest,expected_logit_hex=expected))
    if not cases or len({c['id'] for c in cases})!=len(cases):raise ValueError('Empty/duplicate case IDs')
    return cases


def image_identity(root,ident):
    config=json.loads((root/'campaign.json').read_text());selected=config['images'][ident]
    image=json.loads((root/'installed_image.json').read_text())
    if image.get('status')!='ready' or image.get('id')!=ident or image.get('reset_diagnostic') is not False:
        raise ValueError('Wrong installed image/reset policy')
    for key in ('bitstream_sha256','source_manifest_sha256','artifact_manifest_sha256','fifo_depth','pipeline_mode'):
        if image[key]!=selected[key]:raise ValueError('Installed OPT identity mismatch: '+key)
    if sha(Path(selected['bitstream']))!=selected['bitstream_sha256']:raise ValueError('Changed bitstream')
    if sha(Path(config['driver']))!=config['driver_sha256']:raise ValueError('Changed driver')
    for file,digest in config['software_files'].items():
        if sha(root/file)!=digest:raise ValueError('Changed benchmark software: '+file)
    return dict(id=ident,**{k:selected[k] for k in ('bitstream_sha256','source_manifest_sha256','artifact_manifest_sha256','fifo_depth','pipeline_mode')},driver_sha256=config['driver_sha256'])


def open_session(root,capacity,depth):
    s=DirectCoyoteSession(root/'software/runtime_build/libCoyoteInferenceCampaign.so','direct_checker',capacity,'HPF')
    s.lib.campaign_configure_fifo.argtypes=[ct.c_void_p,ct.c_uint];s.lib.campaign_configure_fifo.restype=ct.c_int
    s._call('campaign_configure_fifo',depth)
    s.lib.campaign_now_ns.argtypes=[];s.lib.campaign_now_ns.restype=ct.c_uint64
    return s


def file_trial(session,path):
    # All host timestamps use the runtime's same steady_clock. CSR readback happens
    # after host_verdict_seen_ns and is excluded from the application endpoint.
    start=int(session.lib.campaign_now_ns());raw=np.fromfile(path,dtype=np.uint8)
    read_end=int(session.lib.campaign_now_ns());session.prepare(raw)
    prepare_end=int(session.lib.campaign_now_ns());result=session.run()
    result.update(file_start_ns=start,file_read_end_ns=read_end,prepare_end_ns=prepare_end)
    return result


def derived(row,case,mapped,tick,identity):
    d=components(row,case,mapped,tick,None,identity['fifo_depth'],identity['pipeline_mode'])
    if row['scope']=='file':
        t=[int(row[k]) for k in ('file_start_ns','file_read_end_ns','prepare_end_ns','host_start_ns','host_verdict_seen_ns')]
        if t!=sorted(t):raise ValueError('file/read/prepare/verdict timestamp ordering')
        d.update(file_e2e_ms=(t[-1]-t[0])/1e6,file_read_ms=(t[1]-t[0])/1e6,prepare_ms=(t[2]-t[1])/1e6)
    return dict(d,scope=row['scope'],iteration=identity['id'])


def collect(root,ident,out,mode):
    out.mkdir(parents=True,exist_ok=False);identity=image_identity(root,ident)
    cases=read_cases(root/('admission.tsv' if mode=='admission' else 'pilot.tsv' if mode=='pilot' else 'cases.tsv'))
    capacity=max(c['bytes'] for c in cases)
    frame_capacity=json.loads((root/'campaign.json').read_text()).get('host_buffer_capacity_bytes')
    if frame_capacity is not None:
        if frame_capacity % 64 or frame_capacity < 64+((capacity+63)//64)*64:
            raise ValueError('Pinned frame allocation is unaligned or smaller than the selected workload')
        capacity=frame_capacity-64
    depth=identity['fifo_depth'];measurements=[];summaries=[];seen_tags=set()
    fields=['case_id','sweep','input_sha256','iteration','variant','input_bytes','scope','trial','warmup','signature','status','transport_bytes','trial_tag',
            'host_start_ns','submit_start_ns','submit_return_ns','host_dma_done_ns','host_verdict_seen_ns',
            'file_start_ns','file_read_end_ns','prepare_end_ns']+[f'csr_{i}' for i in range(6,30)]+['session','block']
    with (out/'observations.csv').open('x') as f,(out/'clock.csv').open('x') as cf,(out/'environment.jsonl').open('x') as ef:
        writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader();clocks=csv.writer(cf);clocks.writerow(['session','block','case_id','scope','position','host_before_ns','fpga_tick','host_after_ns'])
        passes=[('sequential',10),('alternating_a',5),('alternating_b',5)] if mode=='admission' else [('timed',1)]
        for session_name,repetitions in passes:
            with open_session(root,capacity,depth) as session:
                work=list(cases)
                if session_name.startswith('alternating'):
                    random.Random(20261013+(session_name=='alternating_b')).shuffle(work)
                    work=work*repetitions
                for index,c in enumerate(work):
                    scopes=['resident'] if mode=='admission' else ['resident','file']
                    for scope in scopes:
                        raw=np.fromfile(c['path'],dtype=np.uint8);session.prepare(raw)
                        record(ef,c['id'],session_name+'_'+scope+'_before')
                        calibration=[]
                        for position in ['before']:
                            for _ in range(32):
                                b,t,a=session.clock_sample();calibration.append(dict(position=position,host_before_ns=b,fpga_tick=t,host_after_ns=a));clocks.writerow([session_name,index,c['id'],scope,position,b,t,a])
                        count,warm=(repetitions,0) if session_name=='sequential' else (1,0) if mode=='admission' else (10,2) if mode=='pilot' else (200,20)
                        rows=[]
                        for i in range(count+warm):
                            result=file_trial(session,c['path']) if scope=='file' else session.run()
                            row={k:v for k,v in result.items() if k in fields};row.update(case_id=c['id'],sweep=c['sweep'],input_sha256=c['sha256'],iteration=ident,variant=7,input_bytes=c['bytes'],scope=scope,trial=i,warmup=int(i<warm),session=session_name,block=index)
                            writer.writerow(row);f.flush()
                            if (session_name,row['trial_tag']) in seen_tags:raise ValueError('Duplicate hardware trial tag')
                            seen_tags.add((session_name,row['trial_tag']))
                            check_logit(result['csr_26']&0xffffffff,result['verdict'],c,None)
                            rows.append(row)
                        for _ in range(32):
                            b,t,a=session.clock_sample();calibration.append(dict(position='after',host_before_ns=b,fpga_tick=t,host_after_ns=a));clocks.writerow([session_name,index,c['id'],scope,'after',b,t,a])
                        cf.flush();mapped,model=clock_model(calibration);tick=(model['ns_per_tick_min']+model['ns_per_tick_max'])/2
                        ds=[derived(row,c,mapped,tick,identity) for row in rows];measurements+=ds
                        accepted=[d for d in ds if not d['warmup']]
                        metrics=['host_observed_ms','arm_to_verdict_ms','preprocess_ms','inference_ms','inference_tail_ms','overlap_ms','publication_ms','fifo_peak','pixel_backpressure_cycles','cnn_starve_cycles']
                        if scope=='file':metrics+=['file_e2e_ms','file_read_ms','prepare_ms']
                        summary=dict(case_id=c['id'],input_bytes=c['bytes'],scope=scope,session=session_name,trials=count,warmups=warm,
                            metrics={k:dict(median=statistics.median(d[k] for d in accepted),p95=percentile([d[k] for d in accepted],.95)) for k in metrics})
                        summaries.append(summary);record(ef,c['id'],session_name+'_'+scope+'_after');ef.flush()
                        print('PASS',ident,mode,session_name,c['id'],scope,count,flush=True)
    if image_identity(root,ident)!=identity:raise ValueError('Hardware/software identity changed')
    # Recheck files after timed reads without including hashing in the measurement.
    read_cases(root/('admission.tsv' if mode=='admission' else 'pilot.tsv' if mode=='pilot' else 'cases.tsv'))
    expected=len(cases)*(20 if mode=='admission' else 24 if mode=='pilot' else 440)
    if len(measurements)!=expected:raise ValueError('Incomplete measurement grid')
    with (out/'derived.csv').open('x') as f:
        keys=list(dict.fromkeys(k for d in measurements for k in d));w=csv.DictWriter(f,fieldnames=keys);w.writeheader();w.writerows(measurements)
    result=dict(status='passed',mode=mode,identity=identity,rows=len(measurements),summaries=summaries,
        exact_logits=True,clock_calibration='32 bracketed samples before/after every case block',
        file_scope='warm filesystem cache; open/read + input preparation/copy + transfer + FPGA preprocessing/inference + host-observed verdict; diagnostic readback excluded',
        resident_scope='prepared input, host invocation to host-observed verdict; excludes file read/copy and session allocation',
        inference_scope='first CNN input accepted to score; includes streaming stalls',
        files={p.name:sha(p) for p in out.iterdir() if p.is_file()})
    save(out/'result.json',result)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);p.add_argument('ident');p.add_argument('output',type=Path);p.add_argument('mode',choices=['admission','pilot','full']);a=p.parse_args()
    try:collect(a.root.resolve(),a.ident,a.output.resolve(),a.mode)
    except Exception as e:
        if a.output.exists():save(a.output/'failure.json',dict(status='failed',error=str(e)))
        raise
