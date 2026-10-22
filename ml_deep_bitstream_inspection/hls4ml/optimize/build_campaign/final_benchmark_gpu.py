#!/usr/bin/env python3
"""GPU ABI-v4 collector. The parent controller owns the exclusive board lease."""
import argparse, contextlib, gc, json, random, statistics, time
from pathlib import Path
import numpy as np
import tensorflow as tf
import gpu_transport
from fp32_model import build_model, inference_function, preprocess
from board_benchmark import sha, save, clock_model, percentile
from opt_benchmark_collect import read_cases
from host_environment import record

def identity(root,ident):
    c=json.loads((root/'campaign.json').read_text());i=c['images'][ident]
    installed=json.loads((root/'installed_image.json').read_text())
    assert installed['status']=='ready' and installed['id']==ident and installed['reset_diagnostic'] is False
    for key in ['bitstream_sha256','source_manifest_sha256','artifact_manifest_sha256']:assert installed[key]==i[key]
    assert sha(i['bitstream'])==i['bitstream_sha256']
    for p,h in c['software_files'].items():assert sha(root/p)==h,p
    return i

def calibration(adapter,position):
    return [dict(position=position,host_before_ns=int(a),fpga_tick=int(t),host_after_ns=int(b)) for a,t,b in adapter.calibrate()]

def validate(row,case,reference,variant):
    r=lambda i:int(row['csr_'+str(i)])
    assert row['variant']==variant and r(4)==0x4342595400040000|variant
    assert r(0)==2 and r(2)==row['trial'] and r(1)==case['bytes']
    beats=1+(case['bytes']+63)//64
    assert r(20)==beats and row['transport_bytes']==beats*64
    assert r(7)&0xc0==0xc0 and r(6)<=r(14)<=r(15)
    if case['bytes']:assert r(7)&3==3 and r(6)<=r(8)<=r(9)<=r(15)
    value=float(np.array([r(26)&0xffffffff],np.uint32).view(np.float32)[0])
    assert np.isfinite(value)
    np.testing.assert_allclose(value,reference,rtol=1e-4,atol=1e-4)
    assert bool(r(26)>>32)==(reference>=0)
    times=[row[k] for k in ['file_start_ns','file_end_ns','pack_end_ns','host_start_ns','submit_ns','submitted_ns','input_ready_ns','relay_start_ns','relay_end_ns','verdict_seen_ns']]
    assert times==sorted(times),'Invalid host ordering'
    if variant==11:
        assert r(21)==beats and r(37)==0 and r(45)==0 and r(42)>=2 and r(43)==64*r(42)
        assert r(6)<=r(18)<=r(19)<=r(38)<=r(40)<=r(41)<=r(14)<=r(15)
        if row['delayed_publication']:assert r(42)>2 and r(39)>r(38),'Autonomous repeated polling not observed'

def derived(row,mapped,tick):
    r=lambda i:int(row['csr_'+str(i)]);ms=tick/1e6
    lo,hi=mapped(r(15))
    assert lo<=row['verdict_seen_ns'] and hi>=row['host_start_ns'],'FPGA verdict outside host interval'
    d=dict(case_id=row['case_id'],scope=row['scope'],input_bytes=row['input_bytes'],trial=row['trial'],warmup=row['warmup'],
        host_observed_ms=(row['verdict_seen_ns']-row['host_start_ns'])/1e6,
        file_e2e_ms=(row['verdict_seen_ns']-row['file_start_ns'])/1e6,
        file_read_ms=(row['file_end_ns']-row['file_start_ns'])/1e6,prepare_ms=(row['pack_end_ns']-row['file_end_ns'])/1e6,
        arm_to_verdict_ms=(r(15)-r(6))*ms,reception_ms=(r(9)-r(8))*ms if row['input_bytes'] else 0,
        input_ready_observed_ms=(row['input_ready_ns']-row['submit_ns'])/1e6,
        relay_host_ms=(row['relay_end_ns']-row['relay_start_ns'])/1e6,
        host_completion_wait_ms=(row['verdict_seen_ns']-row['relay_end_ns'])/1e6,
        result_to_verdict_ms=(r(15)-r(14))*ms,clock_uncertainty_ms=(hi-lo)/1e6)
    if row['variant']==11:
        d.update(forwarding_ms=(r(19)-r(18))*ms,poll_window_ms=(r(41)-r(38))*ms,ready_to_payload_ms=(r(41)-r(40))*ms,
            poll_requests=r(42),poll_bytes=r(43),poll_queue_stall_cycles=r(44),gpu_publication_ms=row['gpu_publication_ms'])
    else:d['host_to_gpu_ms']=row['host_to_gpu_ms']
    return d

def extract_profile(out,windows):
    from tensorflow.core.profiler.protobuf import xplane_pb2
    events=[];planes=[];markers={};copies=[]
    for p in (out/'tf_profile').rglob('*.xplane.pb'):
        space=xplane_pb2.XSpace();space.ParseFromString(p.read_bytes())
        for plane in space.planes:
            planes.append(plane.name)
            if plane.name=='/host:CPU':
                for line in plane.lines:
                    for event in line.events:
                        name=plane.event_metadata[event.metadata_id].name
                        if name not in ('gpu_preprocessing','gpu_inference'):continue
                        step=next(int(getattr(s,s.WhichOneof('value'))) for s in event.stats if plane.stat_metadata[s.metadata_id].name=='step_num')
                        key=(step,name)
                        if key in markers:raise RuntimeError('Duplicate profile phase marker')
                        markers[key]=(line.timestamp_ns+event.offset_ps/1000,line.timestamp_ns+(event.offset_ps+event.duration_ps)/1000)
            if 'GPU' not in plane.name.upper():continue
            for line in plane.lines:
                for event in line.events:
                    name=plane.event_metadata[event.metadata_id].name
                    stats=[plane.stat_metadata[s.metadata_id].name for s in event.stats]
                    if name.startswith('Copy'):
                        decoded={plane.stat_metadata[s.metadata_id].name:(plane.stat_metadata[s.ref_value].name if s.WhichOneof('value')=='ref_value' else getattr(s,s.WhichOneof('value'))) for s in event.stats}
                        copies.append(dict(name=name,start_ns=line.timestamp_ns+event.offset_ps/1000,end_ns=line.timestamp_ns+(event.offset_ps+event.duration_ps)/1000,**decoded))
                    if not any('kernel' in s.lower() for s in stats):continue
                    events.append(dict(name=name,start_ns=line.timestamp_ns+event.offset_ps/1000,end_ns=line.timestamp_ns+(event.offset_ps+event.duration_ps)/1000))
    rows=[]
    for w in windows:
        # XPlane normalizes host/device events to a common trace origin. Match
        # Trace(step_num) markers in that domain, never wall time against offsets.
        start,end=markers[(w['trial'],w['phase'])]
        selected=[e for e in events if e['start_ns']>=start and e['end_ns']<=end]
        if not selected:raise RuntimeError('No attributed GPU kernel events for '+str(w)+'; inspect profiler traces / use rocprofv3')
        rows.append(dict(**w,trace_start_ns=start,trace_end_ns=end,host_synchronized_phase_ms=(end-start)/1e6,
            device_span_ms=(max(e['end_ns'] for e in selected)-min(e['start_ns'] for e in selected))/1e6,
            kernel_sum_ms=sum(e['end_ns']-e['start_ns'] for e in selected)/1e6,kernels=len(selected)))
    bad=[c for c in copies if c['name']=='CopyDeviceToHost' and 'Gather' in c.get('to','')]
    assert not bad, 'Preprocessing fallback: GPU input/index transfer to CPU Gather'
    save(out/'device_profile.json',dict(status='passed',planes=planes,rows=rows,copies=copies,
        no_cpu_gather_fallback=True,scope='Synchronized diagnostic phases; kernel sums exclude copies; spans can contain copies/gaps; not the unprofiled e2e distribution'))

def collect(root,ident,out,mode):
    out.mkdir(parents=True,exist_ok=False);i=identity(root,ident);variant=10 if i['transport']=='host' else 11
    for d in tf.config.list_physical_devices('GPU'):tf.config.experimental.set_memory_growth(d,True)
    tf.config.experimental.enable_tensor_float_32_execution(False)
    tf.config.threading.set_intra_op_parallelism_threads(1);tf.config.threading.set_inter_op_parallelism_threads(1)
    infer=inference_function(build_model('/GPU:0'),'/GPU:0');cpu=inference_function(build_model('/CPU:0'),'/CPU:0')
    for _ in range(20):infer(tf.zeros([1,256,256,1],tf.float32)).numpy()
    cases=read_cases(root/('admission.tsv' if mode=='admission' else 'pilot.tsv' if mode=='pilot' else 'cases.tsv'))
    assert len(cases)==(26 if mode=='admission' else len(cases))
    references={}
    for c in cases:
        with tf.device('/CPU:0'):references[c['id']]=float(cpu(preprocess(tf.convert_to_tensor(np.fromfile(c['path'],dtype=np.uint8)))).numpy()[0,0])
    if mode!='admission':
        gate=json.loads((out.parent/'admission/result.json').read_text())
        assert gate['status']=='passed' and gate['rows']==520 and gate['identity']==i
    profiled=mode=='profile';windows=[];allrows=[];summaries=[];trial=0
    passes=[('sequential',10),('alternating_a',5),('alternating_b',5)] if mode=='admission' else [('timed',1)]
    if profiled:tf.profiler.experimental.start(str(out/'tf_profile'))
    with (out/'observations.jsonl').open('w') as rawfile,(out/'calibration.jsonl').open('w') as clocks,(out/'environment.jsonl').open('w') as environment:
        for session,repetitions in passes:
            adapter=gpu_transport.Transport()
            work=list(cases)
            if session.startswith('alternating'):
                random.Random(20261013+(session=='alternating_b')).shuffle(work);work=work*repetitions
            for c in work:
                resident=np.fromfile(c['path'],dtype=np.uint8)
                for scope in (['resident'] if mode in ['admission','profile'] else ['resident','file']):
                    record(environment,c['id'],session+'_'+scope+'_before');cal=calibration(adapter,'before');rows=[];segment=[];ds=[]
                    count,warm=(repetitions,0) if session=='sequential' else (1,0) if mode=='admission' else (10,2) if mode=='pilot' else (20,0) if profiled else (200,20)
                    for index in range(count+warm):
                        trial+=1;start=time.monotonic_ns();raw=np.fromfile(c['path'],dtype=np.uint8) if scope=='file' else resident
                        read_end=time.monotonic_ns();adapter.load(raw);pack_end=time.monotonic_ns();adapter.start(trial);adapter.wait_input()
                        raw_tensor=tf.experimental.dlpack.from_dlpack(adapter.input_capsule())
                        def phase(name,fn):
                            if not profiled:return fn()
                            a=time.time_ns()
                            with tf.profiler.experimental.Trace(name,step_num=trial,_r=1):
                                result=fn();result.numpy()
                            windows.append(dict(case_id=c['id'],trial=trial,phase=name,start_wall_ns=a,end_wall_ns=time.time_ns()))
                            return result
                        with tf.device('/GPU:0'):pixels=phase('gpu_preprocessing',lambda:preprocess(raw_tensor))
                        score=phase('gpu_inference',lambda:infer(pixels))
                        delayed=mode=='admission' and variant==11 and session=='sequential' and index==0
                        if delayed:time.sleep(.005)
                        relay_start=time.monotonic_ns()
                        if variant==10:adapter.publish_host(float(score.numpy()[0,0]))
                        else:adapter.publish_gpu(tf.experimental.dlpack.to_dlpack(score))
                        relay_end=time.monotonic_ns();row=dict(adapter.finish())
                        row.update(case_id=c['id'],input_sha256=c['sha256'],scope=scope,session=session,warmup=index<warm,
                            file_start_ns=start,file_end_ns=read_end,pack_end_ns=pack_end,relay_start_ns=relay_start,relay_end_ns=relay_end,
                            delayed_publication=delayed,profiled=profiled,bitstream_sha256=i['bitstream_sha256'])
                        rawfile.write(json.dumps(row)+'\n');rawfile.flush();validate(row,c,references[c['id']],variant);rows.append(row);segment.append(row)
                        if len(segment)==20 or index+1==count+warm:
                            cal+=calibration(adapter,'after');mapped,model=clock_model(cal);tick=(model['ns_per_tick_min']+model['ns_per_tick_max'])/2
                            clocks.write(json.dumps(dict(case_id=c['id'],scope=scope,session=session,first_trial=segment[0]['trial'],last_trial=segment[-1]['trial'],samples=cal,model=model))+'\n');clocks.flush()
                            ds.extend(derived(r,mapped,tick) for r in segment);segment=[]
                            if index+1<count+warm:cal=calibration(adapter,'before')
                    allrows+=ds;accepted=[r for r in ds if not r['warmup']]
                    metrics=[k for k in ds[0] if k not in ['case_id','scope','input_bytes','trial','warmup']]
                    summaries.append(dict(case_id=c['id'],scope=scope,input_bytes=c['bytes'],session=session,trials=count,warmups=warm,
                        metrics={k:dict(median=statistics.median(r[k] for r in accepted),p95=percentile([r[k] for r in accepted],.95)) for k in metrics}))
                    record(environment,c['id'],session+'_'+scope+'_after');environment.flush();print('PASS',ident,mode,session,c['id'],scope,count,flush=True)
            del raw_tensor,pixels,score,adapter;gc.collect()
    if profiled:
        tf.profiler.experimental.stop();save(out/'profile_windows.json',windows);extract_profile(out,windows)
    assert identity(root,ident)==i
    read_cases(root/('admission.tsv' if mode=='admission' else 'pilot.tsv' if mode=='pilot' else 'cases.tsv'))
    expected=len(cases)*(20 if mode in ['admission','profile'] else 24 if mode=='pilot' else 440)
    assert len(allrows)==expected
    save(out/'derived.json',allrows)
    save(out/'result.json',dict(status='passed',mode=mode,identity=i,rows=len(allrows),summaries=summaries,precision='float32',host_allocation='HPF',clock_block_trials=20,
        files={p.name:sha(p) for p in out.iterdir() if p.is_file()}))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);p.add_argument('ident');p.add_argument('output',type=Path);p.add_argument('mode',choices=['admission','pilot','full','profile']);a=p.parse_args()
    try:collect(a.root.resolve(),a.ident,a.output.resolve(),a.mode)
    except Exception as e:
        if a.output.exists():save(a.output/'failure.json',dict(status='failed',error=str(e)))
        raise
