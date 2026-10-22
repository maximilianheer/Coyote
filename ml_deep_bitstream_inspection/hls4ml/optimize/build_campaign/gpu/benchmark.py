#!/usr/bin/env python3
"""Explicit board-admission/benchmark runner for GPU ABI v4; never programs devices."""
import argparse,contextlib,fcntl,hashlib,json,os,time
from pathlib import Path
os.environ.setdefault('HIP_VISIBLE_DEVICES','0')
os.environ.setdefault('TF_FORCE_GPU_ALLOW_GROWTH','true')
import numpy as np
import tensorflow as tf
import gpu_transport
from fp32_model import build_model,inference_function,preprocess

def run(args):
    args.output.mkdir(parents=True,exist_ok=False)
    lock=args.board_lock.open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    for device in tf.config.list_physical_devices('GPU'):tf.config.experimental.set_memory_growth(device,True)
    tf.config.experimental.enable_tensor_float_32_execution(False)
    model=build_model('/GPU:0');infer=inference_function(model,'/GPU:0')
    for _ in range(20):infer(tf.zeros([1,256,256,1],tf.float32)).numpy()
    # Require explicit image-bound admission for measured runs.
    if not args.admission:
        if not args.admission_result:raise RuntimeError('Measured run requires --admission-result from the currently programmed image')
        gate=json.loads(args.admission_result.read_text())
        if gate.get('status')!='passed' or not gate.get('admission') or gate.get('calls')!=520 or gate.get('variant')!=args.variant or gate.get('bitstream_sha256')!=args.bitstream_sha256:raise RuntimeError('Admission image identity mismatch')
    adapter=gpu_transport.Transport()
    calibration={'before':list(adapter.calibrate())}
    cases=[]
    for line in args.cases.read_text().splitlines():
        name,kind,path,size,digest,quantized=line.split('\t')
        raw=np.fromfile(path,dtype=np.uint8)
        if len(raw)!=int(size) or hashlib.sha256(raw).hexdigest()!=digest:raise RuntimeError('Workload identity mismatch: '+name)
        cases.append((name,Path(path),raw,digest))
    cpu=inference_function(build_model('/CPU:0'),'/CPU:0') if args.admission else None
    if args.admission and len(cases)!=26:raise RuntimeError('Admission requires the sealed 26-case manifest (520 calls)')
    if args.profile:tf.profiler.experimental.start(str(args.output/'tf_profile'))
    def trace(label,trial):return tf.profiler.experimental.Trace(label,step_num=trial,_r=1) if args.profile else contextlib.nullcontext()
    trial=0;errors=[]
    with (args.output/'trials.jsonl').open('w') as output:
        for name,path,resident,digest in cases:
            with tf.device('/CPU:0'):
                reference=float(cpu(preprocess(tf.convert_to_tensor(resident))).numpy()[0,0]) if cpu else None
            rounds=20 if args.admission else (args.warmups+args.trials)
            for i in range(rounds):
                trial+=1;file_start=time.monotonic_ns()
                raw=np.fromfile(path,dtype=np.uint8) if args.scope=='file' else resident
                file_end=time.monotonic_ns()
                adapter.load(raw);pack_end=time.monotonic_ns()
                adapter.start(trial);adapter.wait_input()
                raw_tensor=tf.experimental.dlpack.from_dlpack(adapter.input_capsule())
                with trace('gpu_preprocessing',trial),tf.device('/GPU:0'):pixels=preprocess(raw_tensor)
                with trace('gpu_inference',trial):score=infer(pixels)
                relay_start=time.monotonic_ns()
                if args.variant=='host':adapter.publish_host(float(score.numpy()[0,0]))
                else:adapter.publish_gpu(tf.experimental.dlpack.to_dlpack(score))
                relay_end=time.monotonic_ns()
                row=dict(adapter.finish());row.update(case=name,scope=args.scope,warmup=False if args.admission else i<args.warmups,
                    file_start_ns=file_start,file_end_ns=file_end,pack_end_ns=pack_end,relay_start_ns=relay_start,relay_end_ns=relay_end,
                    bitstream_sha256=args.bitstream_sha256,input_sha256=digest,profiled=args.profile)
                expected_variant=10 if args.variant=='host' else 11
                if row['variant']!=expected_variant:raise RuntimeError('CLI variant disagrees with hardware')
                row['e2e_ns']=row['verdict_seen_ns']-(file_start if args.scope=='file' else row['host_start_ns'])
                if args.admission:
                    bits=int(row['csr_26'])&0xffffffff
                    value=np.array([bits],np.uint32).view(np.float32)[0]
                    np.testing.assert_allclose(value,reference,rtol=1e-4,atol=1e-4)
                    if bool(int(row['csr_26'])>>32)!=(reference>=0):raise RuntimeError('Hardware verdict mismatch')
                output.write(json.dumps(row)+'\n');output.flush()
            print('PASS',name,'trials',trial,flush=True)
    if args.profile:tf.profiler.experimental.stop()
    calibration['after']=list(adapter.calibrate())
    (args.output/'clock.json').write_text(json.dumps(calibration,indent=2))
    (args.output/'result.json').write_text(json.dumps({'status':'passed','calls':trial,'bitstream_sha256':args.bitstream_sha256,'variant':args.variant,'admission':args.admission,'profiled':args.profile,'scope':args.scope},indent=2))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--cases',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--board-lock',type=Path,required=True);p.add_argument('--variant',choices=['host','p2p'],required=True)
    p.add_argument('--bitstream-sha256',required=True);p.add_argument('--scope',choices=['resident','file'],default='resident')
    p.add_argument('--warmups',type=int,default=20);p.add_argument('--trials',type=int,default=200)
    p.add_argument('--admission',action='store_true');p.add_argument('--admission-result',type=Path);p.add_argument('--profile',action='store_true')
    args=p.parse_args()
    if len(args.bitstream_sha256)!=64 or any(x not in '0123456789abcdef' for x in args.bitstream_sha256):p.error('invalid bitstream hash')
    if args.profile:args.warmups=0;args.trials=20
    run(args)
