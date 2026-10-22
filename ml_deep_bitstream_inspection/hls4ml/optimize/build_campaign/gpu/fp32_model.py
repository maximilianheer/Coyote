"""Original FP32 Keras checkpoint; only standard TensorFlow preprocessing/ops."""
import json,hashlib
from pathlib import Path
import numpy as np
import tensorflow as tf
REPO=next(p for p in Path(__file__).resolve().parents if (p/'ML_Based_Deep_Bitstream_Inspection_for_Serverless_FPGAs_Report.pdf').is_file())
MODEL=REPO/'hls4ml/artifacts_layer7_ext/cnn_small_hls_opt_img256/notebook_float/res256_layers7_WfloatAfloat_P0_RFbase_929720764c5b/fold_0'

def build_model(device='/GPU:0'):
    local=Path(__file__).with_name('model_config.json')
    config_path=local if local.exists() else MODEL/'model_config.json'
    weights=MODEL/'final_weights.weights.h5'
    reference=Path(__file__).with_name('model_reference.json')
    if reference.exists():
        pinned=json.loads(reference.read_text())
        weights=REPO/pinned['weights']
        for path,digest in [(weights,pinned['weights_sha256']),(config_path,pinned['model_config_sha256'])]:
            if hashlib.sha256(path.read_bytes()).hexdigest()!=digest:raise RuntimeError('Pinned model changed: '+str(path))
    config=json.loads(config_path.read_text())['config']
    with tf.device(device):
        x=inputs=tf.keras.Input(shape=(256,256,1),dtype=tf.float32,name='bitstream_input')
        for spec in config['layers'][1:]:
            cls=getattr(tf.keras.layers,spec['class_name'])
            x=cls.from_config(spec['config'])(x)
        model=tf.keras.Model(inputs,x,name=config['name'])
        model.load_weights(str(weights))
    return model

@tf.function(input_signature=[tf.TensorSpec([None],tf.uint8)],jit_compile=False)
def preprocess(raw):
    n=tf.size(raw,out_type=tf.int64)
    # ROCm TensorFlow places uint8 GatherV2 on CPU, copying the entire input
    # back to the host. Float32 gathering is GPU-supported; byte values are
    # exactly representable. Keep padding before inversion for parity.
    data=tf.cast(raw,tf.float32)
    selected=tf.cond(n>65536,
        lambda:tf.gather(data,tf.range(65536,dtype=tf.int64)*(n-1)//65535),
        lambda:tf.pad(data,tf.reshape(tf.stack([tf.constant(0,tf.int64),65536-n]),[1,2])))
    return tf.reshape((255.0-selected)/255.0,[1,256,256,1])

def inference_function(model,device):
    @tf.function(input_signature=[tf.TensorSpec([1,256,256,1],tf.float32)],jit_compile=False)
    def infer(x):
        with tf.device(device):return model(x,training=False)
    return infer

def validate(output):
    devices=tf.config.list_physical_devices('GPU')
    if not devices or not tf.sysconfig.get_build_info()['is_rocm_build']:raise RuntimeError('ROCm GPU unavailable')
    for d in devices:tf.config.experimental.set_memory_growth(d,True)
    tf.config.experimental.enable_tensor_float_32_execution(False)
    gpu=inference_function(build_model('/GPU:0'),'/GPU:0')
    cpu=inference_function(build_model('/CPU:0'),'/CPU:0')
    rng=np.random.default_rng(20261018);largest=0.0;checks=0
    for n in [0,1,65,65535,65536,65537,1048576,134217664]:
        raw=rng.integers(0,256,n,dtype=np.uint8)
        sample=raw[np.arange(65536,dtype=np.int64)*(n-1)//65535] if n>65536 else np.pad(raw,(0,65536-n))
        expected=((255-sample).astype(np.float32)/255).reshape(1,256,256,1)
        with tf.device('/GPU:0'):prepared=preprocess(tf.convert_to_tensor(raw))
        np.testing.assert_allclose(prepared.numpy(),expected,atol=1e-7,rtol=0)
        a=gpu(prepared).numpy();b=cpu(tf.convert_to_tensor(expected)).numpy()
        np.testing.assert_allclose(a,b,atol=1e-4,rtol=1e-4)
        assert np.array_equal(a>=0,b>=0)
        largest=max(largest,float(np.max(np.abs(a-b))));checks+=1
    Path(output).write_text(json.dumps({'status':'passed','cases':checks,'max_abs_logit_error':largest,'tensorflow':tf.__version__,'device':gpu(prepared).device,'scope':'synthetic boundary/preprocessing and FP32 CPU/GPU parity; 520-call workload admission remains required'},indent=2))
    print('PASS FP32 model and preprocessing',checks,'cases, max error',largest,flush=True)
if __name__=='__main__':
    import sys
    validate(sys.argv[1])
