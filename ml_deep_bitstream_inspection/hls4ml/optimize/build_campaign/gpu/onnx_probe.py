#!/usr/bin/env python3
"""Isolated standard ONNX/MIGraphX experiment; no report inputs are modified."""
import argparse,ctypes,hashlib,json,os,time,traceback
from pathlib import Path
import numpy as np
import tensorflow as tf
import tf2onnx
import onnxruntime as ort
import gpu_transport
from fp32_model import build_model,inference_function

class Device(ctypes.Structure):_fields_=[('type',ctypes.c_int),('id',ctypes.c_int)]
class DType(ctypes.Structure):_fields_=[('code',ctypes.c_uint8),('bits',ctypes.c_uint8),('lanes',ctypes.c_uint16)]
class Tensor(ctypes.Structure):_fields_=[('data',ctypes.c_void_p),('device',Device),('ndim',ctypes.c_int),('dtype',DType),('shape',ctypes.POINTER(ctypes.c_int64)),('strides',ctypes.POINTER(ctypes.c_int64)),('offset',ctypes.c_uint64)]
def save(p,x):p.write_text(json.dumps(x,indent=2)+'\n')
def main(a):
    a.out.mkdir(exist_ok=False,parents=True);state=dict(status='running',report_eligible=False,started_at=time.time(),onnxruntime=ort.__version__,tf2onnx=tf2onnx.__version__,affinity=sorted(os.sched_getaffinity(0)))
    save(a.out/'status.json',state)
    try:
        tf.config.set_visible_devices([],'GPU');tf.config.threading.set_inter_op_parallelism_threads(1);tf.config.threading.set_intra_op_parallelism_threads(1)
        model=build_model('/CPU:0');cpu=inference_function(model,'/CPU:0');rows=[]
        for line in (a.root/'cases.tsv').read_text().splitlines():
            ident,kind,path,n,digest,_=line.split('\t');n=int(n)
            if ident.startswith('smoke') or a.quick and ident not in ['synthetic_4194304','synthetic_134217664']:continue
            assert 0<=n<2**31, 'Exact int32 indices require this range'
            raw=np.fromfile(path,dtype=np.uint8);assert hashlib.sha256(raw).hexdigest()==digest
            sample=raw[np.arange(65536,dtype=np.int64)*(n-1)//65535] if n>65536 else np.pad(raw,(0,65536-n));pixels=((255-sample).astype(np.float32)/255).reshape(1,256,256,1)
            ref=cpu(tf.convert_to_tensor(pixels)).numpy()
            @tf.function(input_signature=[tf.TensorSpec([n],tf.uint8,name='raw')])
            def combined(raw):
                data=raw
                selected=tf.gather(data,tf.constant((np.arange(65536,dtype=np.int64)*(n-1)//65535).astype(np.int32))) if n>65536 else tf.pad(data,[[0,65536-n]])
                return model(tf.reshape((255.-tf.cast(selected,tf.float32))/255.,[1,256,256,1]),training=False)
            target=a.out/(ident+'.onnx');start=time.perf_counter();tf2onnx.convert.from_function(combined,input_signature=combined.input_signature,opset=17,output_path=str(target))
            options=ort.SessionOptions();options.log_severity_level=0;options.intra_op_num_threads=1;options.inter_op_num_threads=1;options.add_session_config_entry('session.disable_cpu_ep_fallback','1')
            providers=[('MIGraphXExecutionProvider',dict(device_id='0',migraphx_fp16_enable='0',migraphx_bf16_enable='0',migraphx_int8_enable='0',migraphx_fp8_enable='0'))]
            session=ort.InferenceSession(str(target),sess_options=options,providers=providers);session.disable_fallback();compile_seconds=time.perf_counter()-start
            assert session.get_providers()[0]=='MIGraphXExecutionProvider'
            assert session.get_session_options().get_session_config_entry('session.disable_cpu_ep_fallback')=='1'
            capsule=gpu_transport.diagnostic_input(raw)
            get=ctypes.pythonapi.PyCapsule_GetPointer;get.restype=ctypes.c_void_p;get.argtypes=[ctypes.py_object,ctypes.c_char_p]
            t=Tensor.from_address(get(capsule,b'dltensor'));assert t.device.type==10 and t.dtype.bits==8 and t.shape[0]==n
            binding=session.io_binding();binding.bind_input(session.get_inputs()[0].name,'cuda',0,np.uint8,[n],t.data+t.offset);binding.bind_output(session.get_outputs()[0].name,'cuda',0)
            def run():
                session.run_with_iobinding(binding)
                return binding.copy_outputs_to_cpu()[0]
            start=time.perf_counter();actual=run();first=time.perf_counter()-start;np.testing.assert_allclose(actual,ref,rtol=1e-4,atol=1e-4);assert np.array_equal(actual>=0,ref>=0)
            samples=[]
            for k in range(1020):
                start=time.perf_counter_ns();actual=run();elapsed=(time.perf_counter_ns()-start)/1e6
                if k>=20:samples.append(elapsed)
            np.testing.assert_allclose(actual,ref,rtol=1e-4,atol=1e-4)
            rows.append(dict(case_id=ident,input_bytes=n,input_sha256=digest,scope='GPU input ready to synchronized FP32 scalar; GPU I/O binding; no FPGA transfer/publication',median_ms=float(np.median(samples)),p95_ms=float(np.percentile(samples,95)),samples_ms=samples,max_abs_error=float(abs(actual-ref).max()),first_call_seconds=first,export_compile_seconds=compile_seconds,providers=session.get_providers(),provider_options=session.get_provider_options(),onnx_sha256=hashlib.sha256(target.read_bytes()).hexdigest()))
            save(a.out/'partial.json',rows);print('PASS',ident,rows[-1]['median_ms'],flush=True)
            del binding,session,capsule
        state.update(status='passed',finished_at=time.time());save(a.out/'status.json',state);save(a.out/'result.json',dict(**state,measurements=rows,precision='FP32',batch_size=1))
    except BaseException as e:
        state.update(status='failed',error=str(e),finished_at=time.time());save(a.out/'status.json',state);traceback.print_exc();raise
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);p.add_argument('out',type=Path);p.add_argument('--quick',action='store_true');main(p.parse_args())
