"""Experimental combined FP32 graph; deliberately not the report-pinned runtime."""
import tensorflow as tf

class CombinedInference:
    def __init__(self,model):
        self.model=model
        self.functions={}

    def __call__(self,raw):
        n=int(raw.shape[0])
        if n not in self.functions:
            @tf.function(input_signature=[tf.TensorSpec([n],tf.uint8)],jit_compile=True)
            def combined(data):
                data=tf.cast(data,tf.float32)
                selected=tf.gather(data,tf.range(65536,dtype=tf.int64)*(n-1)//65535) if n>65536 else tf.pad(data,[[0,65536-n]])
                pixels=tf.reshape((255.-selected)/255.,[1,256,256,1])
                return self.model(pixels,training=False)
            self.functions[n]=combined.get_concrete_function()
        return self.functions[n](raw)
