#!/usr/bin/env python3
"""520 software admission calls using exact prior workload bytes; no FPGA timings."""
import argparse,hashlib,json,struct
from pathlib import Path
import numpy as np
import tensorflow as tf
import gpu_transport
from fp32_model import build_model,inference_function,preprocess

def main(manifest,output):
    for d in tf.config.list_physical_devices('GPU'):tf.config.experimental.set_memory_growth(d,True)
    tf.config.experimental.enable_tensor_float_32_execution(False)
    gpu=inference_function(build_model('/GPU:0'),'/GPU:0');cpu=inference_function(build_model('/CPU:0'),'/CPU:0')
    count=0;largest=0.0;rows=[]
    for line in manifest.read_text().splitlines():
        name,kind,path,size,digest,old_logit=line.split('\t');raw=np.fromfile(path,dtype=np.uint8)
        assert raw.size==int(size) and hashlib.sha256(raw).hexdigest()==digest
        n=raw.size
        pixels=raw[np.arange(65536,dtype=np.int64)*(n-1)//65535] if n>65536 else np.pad(raw,(0,65536-n))
        expected=((255-pixels).astype(np.float32)/255).reshape(1,256,256,1)
        ref=float(cpu(tf.convert_to_tensor(expected)).numpy()[0,0])
        # Exported fine-grained input -> TensorFlow preprocessing, without host tensor staging.
        tensor=tf.experimental.dlpack.from_dlpack(gpu_transport.diagnostic_input(raw))
        with tf.device('/GPU:0'):prepared=preprocess(tensor)
        np.testing.assert_allclose(prepared.numpy(),expected,rtol=0,atol=1e-7)
        for rep in range(20):
            result=gpu(prepared)
            ready,payload,trial=gpu_transport.diagnostic_publish(tf.experimental.dlpack.to_dlpack(result),count+1)
            assert trial==count+1 and ready==((~trial&0xffffffff)<<32)|(trial&0xffffffff)
            assert payload>>32==0x43565234
            value=struct.unpack('<f',struct.pack('<I',payload&0xffffffff))[0]
            np.testing.assert_allclose(value,ref,atol=1e-4,rtol=1e-4);assert (value>=0)==(ref>=0)
            largest=max(largest,abs(value-ref));count+=1
        rows.append({'name':name,'sha256':digest,'float_logit_cpu':ref,'float_logit_gpu':value,'old_quantized_logit_bits':old_logit})
        print('PASS',name,'calls',count,flush=True)
    assert count==520
    output.write_text(json.dumps({'status':'passed','calls':count,'max_abs_error':largest,'scope':'GPU software/DLPack/publication admission; new-image board admission still pending','cases':rows},indent=2))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('manifest',type=Path);p.add_argument('output',type=Path);a=p.parse_args();main(a.manifest,a.output)
