"""Frozen FP32 and QKeras CPU models and a gather-first CPU preprocessing graph."""

import importlib.util
import json
import os
from pathlib import Path

os.environ.setdefault("TF_USE_LEGACY_KERAS", "1")
os.environ["CUDA_VISIBLE_DEVICES"] = "-1"
os.environ["HIP_VISIBLE_DEVICES"] = "-1"
os.environ["ROCR_VISIBLE_DEVICES"] = "-1"

import numpy as np
import tensorflow as tf

from common import GPU_REFERENCE, REPO, sha

tf.config.set_visible_devices([], "GPU")
tf.config.threading.set_intra_op_parallelism_threads(1)
tf.config.threading.set_inter_op_parallelism_threads(1)


def build(kind):
    if kind == "FP32":
        source = GPU_REFERENCE / "software/gpu_runtime/fp32_model.py"
        spec = importlib.util.spec_from_file_location("accepted_fp32_model", source)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.build_model("/CPU:0")
    from qkeras.utils import _add_supported_quantized_objects

    objects = {}
    _add_supported_quantized_objects(objects)
    config = (
        REPO
        / "hls4ml/optimize/iterations/OPT_6_BRAM_FIFO1024_DSP_B2_RF72_RF288/model_config.json"
    )
    weights = REPO / "models/res256/pruned_qat/final_weights.weights.h5"
    assert (
        sha(config)
        == "daf37e59295492b5ac14bb9e186f528ced1fcb763186366128932d937f1d5e23"
    )
    assert (
        sha(weights)
        == "8693fe8efed10f2996c0bc5fe32e68b466fbce097ef75c0f60941f399899ca53"
    )
    with tf.device("/CPU:0"):
        model = tf.keras.models.model_from_json(
            config.read_text(), custom_objects=objects
        )
        model.load_weights(str(weights))
    return model


def preprocess(data):
    # CPU supports gathering bytes directly. Select the 65,536 relevant bytes
    # before conversion, avoiding a full-size float temporary for large inputs.
    size = int(data.shape[0])
    if size > 65536:
        indices = tf.range(65536, dtype=tf.int64) * (size - 1) // 65535
        selected = tf.gather(data, indices)
    else:
        selected = tf.pad(data, [[0, 65536 - size]])
    # Preserve every reference float32 pixel bit. Reassociating division into
    # reciprocal multiplication can cross a later QKeras rounding threshold.
    table = (255 - np.arange(256, dtype=np.uint8)).astype(np.float32) / np.float32(255)
    normalized = tf.gather(tf.constant(table), tf.cast(selected, tf.int32))
    return tf.reshape(normalized, [1, 256, 256, 1])


class Runtime:
    def __init__(self, kind, xla=True):
        self.kind = kind
        self.model = build(kind)
        self.functions = {}
        self.xla = xla

    def combined(self, size):
        key = ("combined", size)
        if key not in self.functions:

            @tf.function(
                input_signature=[tf.TensorSpec([size], tf.uint8)], jit_compile=self.xla
            )
            def function(raw):
                return self.model(preprocess(raw), training=False)

            self.functions[key] = function.get_concrete_function()
        return self.functions[key]

    def prepared(self):
        key = ("inference", 65536)
        if key not in self.functions:

            @tf.function(
                input_signature=[tf.TensorSpec([1, 256, 256, 1], tf.float32)],
                jit_compile=self.xla,
            )
            def function(value):
                return self.model(value, training=False)

            self.functions[key] = function.get_concrete_function()
        return self.functions[key]

    def preprocessing(self, size):
        @tf.function(
            input_signature=[tf.TensorSpec([size], tf.uint8)], jit_compile=self.xla
        )
        def function(raw):
            return preprocess(raw)

        return function.get_concrete_function()


def alias(raw):
    tensor = tf.experimental.dlpack.from_dlpack(raw.__dlpack__())
    assert tensor.device.endswith("CPU:0")
    if len(raw):
        flat = raw.reshape(-1)
        original = flat[0].copy()
        changed = (
            int(original) ^ 255 if raw.dtype == np.uint8 else float(original) + 0.125
        )
        flat[0] = changed
        assert tensor.numpy().ravel()[0] == flat[0], "Tensor input was copied"
        flat[0] = original
    return tensor
