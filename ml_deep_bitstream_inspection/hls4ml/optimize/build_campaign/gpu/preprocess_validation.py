#!/usr/bin/env python3
"""Validate preprocessing-v2 using the real DMA-BUF/DLPack adapter, without FPGA programming."""
import argparse, hashlib, importlib.util, json, time
from pathlib import Path
import numpy as np
import tensorflow as tf
import gpu_transport
from fp32_model import preprocess

def save(p,x): p.write_text(json.dumps(x,indent=2)+'\n')
def main(root):
    out=root/'diagnostics/preprocessing_validation';out.mkdir(exist_ok=False)
    for d in tf.config.list_physical_devices('GPU'):tf.config.experimental.set_memory_growth(d,True)
    tf.config.threading.set_intra_op_parallelism_threads(1);tf.config.threading.set_inter_op_parallelism_threads(1)
    tf.config.set_soft_device_placement(False)
    cases=[]
    for line in (root/'cases.tsv').read_text().splitlines():
        ident,kind,path,n,h,_=line.split('\t');cases.append((ident,np.fromfile(path,dtype=np.uint8)))
    for n in [0,1,63,64,65,65535,65536,65537]:cases.append((f'boundary_{n}',np.arange(n,dtype=np.uint8)))
    rows=[]
    for ident,raw in cases:
        n=len(raw);sample=raw[np.arange(65536,dtype=np.int64)*(n-1)//65535] if n>65536 else np.pad(raw,(0,65536-n))
        expected=((255-sample).astype(np.float32)/255).reshape(1,256,256,1)
        tensor=tf.experimental.dlpack.from_dlpack(gpu_transport.diagnostic_input(raw))
        with tf.device('/GPU:0'):result=preprocess(tensor)
        got=result.numpy();np.testing.assert_allclose(got,expected,atol=1e-7,rtol=0)
        np.testing.assert_array_equal(np.rint(255-got.reshape(-1)*255).astype(np.uint8),sample)
        rows.append(dict(case_id=ident,bytes=n,max_abs_error=float(np.max(abs(got-expected))),device=result.device))
    print('PASS strict placement and pixels:',len(rows),'cases',flush=True)
    tf.profiler.experimental.start(str(out/'trace'))
    for ident,raw in cases:
        tensor=tf.experimental.dlpack.from_dlpack(gpu_transport.diagnostic_input(raw))
        with tf.profiler.experimental.Trace('placement_'+ident,_r=1):
            with tf.device('/GPU:0'):result=preprocess(tensor)
            result.numpy()
    tf.profiler.experimental.stop()
    from tensorflow.core.profiler.protobuf import xplane_pb2
    copies=[];gathers=[]
    for p in (out/'trace').rglob('*.xplane.pb'):
        s=xplane_pb2.XSpace();s.ParseFromString(p.read_bytes())
        for plane in s.planes:
            if 'GPU' not in plane.name:continue
            for line in plane.lines:
                for e in line.events:
                    stats={plane.stat_metadata[v.metadata_id].name:(plane.stat_metadata[v.ref_value].name if v.WhichOneof('value')=='ref_value' else getattr(v,v.WhichOneof('value'))) for v in e.stats}
                    name=plane.event_metadata[e.metadata_id].name
                    if name.startswith('Copy'):copies.append(dict(name=name,duration_us=e.duration_ps/1e6,**stats))
                    if 'kernel_details' in stats and 'Gather' in stats.get('tf_op',''):gathers.append(dict(name=name,**stats))
    assert gathers,'No GPU GatherV2 kernel observed'
    bad=[c for c in copies if c['name']=='CopyDeviceToHost' and ('Gather' in c.get('to','') or (c.get('edge_name') not in ['', 'copy',None] and 'GPU:0;' in c.get('key','') and 'device:CPU:0;' in c.get('key','')))]
    assert not bad,('Unexpected graph GPU-to-CPU copies',bad)
    save(out/'placement.json',dict(status='passed',gpu_gather_kernels=len(gathers),copies=copies,gathers=gathers,scope='Includes diagnostic result.numpy output copies; no input/index CPU fallback'))
    tf.config.set_soft_device_placement(True)
    old=root.parent/'final_benchmarks_gpu_u55c_20261019/software/gpu_runtime/fp32_model.py'
    spec=importlib.util.spec_from_file_location('previous_fp32_model',old);mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    timings=[]
    for ident,raw in cases:
        if not ident.startswith('synthetic'):continue
        tensor=tf.experimental.dlpack.from_dlpack(gpu_transport.diagnostic_input(raw))
        for revision,fn in [('previous',mod.preprocess),('gpu_preprocess_v2',preprocess)]:
            vals=[]
            for k in range(220):
                start=time.perf_counter_ns()
                with tf.device('/GPU:0'):result=fn(tensor)
                result.numpy()
                if k>=20:vals.append((time.perf_counter_ns()-start)/1e6)
            timings.append(dict(case_id=ident,revision=revision,scope='unprofiled preprocessing with synchronized image output',samples_ms=vals,median_ms=float(np.median(vals)),p95_ms=float(np.percentile(vals,95))))
            print(ident,revision,timings[-1]['median_ms'],flush=True)
    save(out/'result.json',dict(status='passed',cases=rows,comparisons=timings,tensorflow=tf.__version__,scope='Pixel/device-placement validation; board/model admission remains separate'))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);main(p.parse_args().root.resolve())
