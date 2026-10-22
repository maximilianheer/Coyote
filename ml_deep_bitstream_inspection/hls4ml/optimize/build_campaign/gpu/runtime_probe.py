#!/usr/bin/env python3
"""Isolated FP32 runtime experiments; never used as the preprocessing-v2 report source."""
import argparse,hashlib,json,os,sys,time,traceback
from pathlib import Path
import numpy as np
import tensorflow as tf
import gpu_transport
from fp32_model import build_model,inference_function,preprocess

def save(p,x):
    tmp=p.with_suffix('.tmp');tmp.write_text(json.dumps(x,indent=2)+'\n');tmp.replace(p)
def quantiles(xs):return dict(median_ms=float(np.median(xs)),p95_ms=float(np.percentile(xs,95)))
def main(a):
    out=a.out;out.mkdir(parents=True,exist_ok=False)
    sys.path.insert(0,str(a.root/'tooling'));from host_environment import snapshot
    save(out/'environment_before.json',snapshot())
    state=dict(status='running',revision=a.mode,report_eligible=False,pid=os.getpid(),affinity=sorted(os.sched_getaffinity(0)),tensorflow=tf.__version__,started_at=time.time(),inter_threads=a.threads,intra_threads=a.threads)
    save(out/'status.json',state)
    try:
        for d in tf.config.list_physical_devices('GPU'):tf.config.experimental.set_memory_growth(d,True)
        tf.config.threading.set_intra_op_parallelism_threads(a.threads);tf.config.threading.set_inter_op_parallelism_threads(a.threads)
        tf.config.experimental.enable_tensor_float_32_execution(False)
        model=build_model('/GPU:0');infer=inference_function(model,'/GPU:0');cpu=inference_function(build_model('/CPU:0'),'/CPU:0')
        inputs=[]
        for line in (a.root/'cases.tsv').read_text().splitlines():
            ident,kind,path,n,digest,_=line.split('\t')
            if ident.startswith('smoke'):continue
            if a.quick and ident not in ['synthetic_4194304','synthetic_134217664']:continue
            inputs.append((ident,np.fromfile(path,dtype=np.uint8)))
        if not a.quick:
            for n in [65536,262144,1048576]:inputs.append((f'reference_size_{n}',np.arange(n,dtype=np.uint8)))
        rows=[];profiler_windows=[]
        @tf.function(jit_compile=False)
        def combined(raw):return model(preprocess(raw),training=False)
        for ident,raw in inputs:
            n=len(raw);sample=raw[np.arange(65536,dtype=np.int64)*(n-1)//65535] if n>65536 else np.pad(raw,(0,65536-n))
            expected=((255-sample).astype(np.float32)/255).reshape(1,256,256,1)
            ref=cpu(tf.convert_to_tensor(expected)).numpy()
            tensor=tf.experimental.dlpack.from_dlpack(gpu_transport.diagnostic_input(raw))
            if a.mode=='xla_combined':
                @tf.function(input_signature=[tf.TensorSpec([n],tf.uint8)],jit_compile=True)
                def xla(raw):
                    data=tf.cast(raw,tf.float32)
                    selected=tf.gather(data,tf.range(65536,dtype=tf.int64)*(n-1)//65535) if n>65536 else tf.pad(data,[[0,65536-n]])
                    pixels=tf.reshape((255.-selected)/255.,[1,256,256,1])
                    return model(pixels,training=False)
                fn=xla
            elif a.mode=='combined_graph':fn=combined
            else:
                def fn(raw):return infer(preprocess(raw))
            start=time.perf_counter()
            with tf.device('/GPU:0'):score=fn(tensor)
            actual=score.numpy();first=time.perf_counter()-start
            np.testing.assert_allclose(actual,ref,rtol=1e-4,atol=1e-4);assert np.array_equal(actual>=0,ref>=0)
            vals=[]
            for k in range(20+a.trials):
                start=time.perf_counter_ns()
                with tf.device('/GPU:0'):score=fn(tensor)
                actual=score.numpy()
                if k>=20:vals.append((time.perf_counter_ns()-start)/1e6)
            np.testing.assert_allclose(actual,ref,rtol=1e-4,atol=1e-4)
            row=dict(case_id=ident,input_bytes=n,input_sha256=hashlib.sha256(raw).hexdigest(),scope='GPU input ready to synchronized FP32 scalar; no FPGA transfer/publication',first_call_seconds=first,max_abs_error=float(abs(actual-ref).max()),samples_ms=vals,**quantiles(vals))
            rows.append(row);save(out/'partial.json',rows)
            print('PASS',a.mode,ident,row['median_ms'],flush=True)
            # Separate diagnostic: one trace window includes all preprocessing + inference,
            # and only one final scalar synchronization. Never time with the profiler enabled.
            if ident in ['synthetic_4194304','synthetic_134217664']:
                trace=out/'profiles'/ident;tf.profiler.experimental.start(str(trace))
                for k in range(20):
                    with tf.profiler.experimental.Trace('combined_compute',step_num=k,_r=1):
                        with tf.device('/GPU:0'):score=fn(tensor)
                        score.numpy()
                tf.profiler.experimental.stop()
        from tensorflow.core.profiler.protobuf import xplane_pb2
        profile_rows=[]
        for pb in (out/'profiles').rglob('*.xplane.pb'):
            space=xplane_pb2.XSpace();space.ParseFromString(pb.read_bytes());markers=[];kernels=[];copies=[]
            for plane in space.planes:
                for line in plane.lines:
                    for e in line.events:
                        name=plane.event_metadata[e.metadata_id].name;start=line.timestamp_ns+e.offset_ps/1000;end=start+e.duration_ps/1000
                        stats={plane.stat_metadata[v.metadata_id].name:(plane.stat_metadata[v.ref_value].name if v.WhichOneof('value')=='ref_value' else getattr(v,v.WhichOneof('value'))) for v in e.stats}
                        if plane.name=='/host:CPU' and name=='combined_compute':markers.append((start,end))
                        if 'GPU' in plane.name and 'kernel_details' in stats:kernels.append(dict(name=name[:250],start=start,end=end,tf_op=stats.get('tf_op','')))
                        if 'GPU' in plane.name and name.startswith('Copy'):copies.append(dict(name=name,start=start,end=end,**stats))
            case_id=pb.relative_to(out/'profiles').parts[0]
            samples=[]
            for start,end in markers:
                ks=[x for x in kernels if x['start']>=start and x['end']<=end];assert ks
                samples.append(dict(kernel_sum_ms=sum(x['end']-x['start'] for x in ks)/1e6,device_span_ms=(max(x['end'] for x in ks)-min(x['start'] for x in ks))/1e6,host_diagnostic_ms=(end-start)/1e6,kernels=len(ks)))
            profile_rows.append(dict(case_id=case_id,samples=samples,copies=copies,kernel_names=sorted({x['name'] for x in kernels})))
        save(out/'profiles.json',profile_rows)
        state.update(status='passed',finished_at=time.time(),rows=len(rows));save(out/'result.json',dict(**state,measurements=rows,reference=dict(preprocess_inference_ms=.165,exact_sample_runtime_scope_match=False),weights_unchanged=True,batch_size=1,precision='FP32'))
        save(out/'status.json',state)
        save(out/'environment_after.json',snapshot())
    except BaseException as e:
        state.update(status='failed',error=str(e),finished_at=time.time());save(out/'status.json',state);traceback.print_exc();raise
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);p.add_argument('out',type=Path);p.add_argument('--mode',choices=['v2_baseline','gpu_local','cpu_pool','threads2','combined_graph','xla_combined'],default='v2_baseline');p.add_argument('--threads',type=int,default=1);p.add_argument('--trials',type=int,default=1000);p.add_argument('--quick',action='store_true');main(p.parse_args())
