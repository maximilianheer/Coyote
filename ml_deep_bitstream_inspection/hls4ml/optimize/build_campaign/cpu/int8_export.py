"""Explicitly separate native INT8 deployment conversion from faithful QKeras."""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from common import REPO, cases, pixels, save
from models import build, tf


def run(root):
    destination = root / "int8_conversion"
    destination.mkdir(exist_ok=True)
    model = build("QKERAS_W8A8")
    inputs = tf.keras.Input(shape=(256, 256, 1), dtype=tf.float32)
    value = inputs
    layers = []
    for layer in model.layers[1:]:
        name = layer.__class__.__name__
        config = layer.get_config()
        if name in ["QConv2D", "QDense"]:
            ordinary = dict(config)
            for key in list(ordinary):
                if "quantizer" in key or key in ["kernel_range", "bias_range"]:
                    ordinary.pop(key)
            ordinary["kernel_constraint"] = None
            ordinary["bias_constraint"] = None
            # Initializers are irrelevant because the frozen, quantized weights
            # are assigned immediately after layer construction.
            ordinary["kernel_initializer"] = "zeros"
            ordinary["bias_initializer"] = "zeros"
            cls = tf.keras.layers.Conv2D if name == "QConv2D" else tf.keras.layers.Dense
            converted = cls.from_config(ordinary)
            value = converted(value)
            weights = [layer.kernel_quantizer_internal(layer.kernel).numpy()]
            if layer.use_bias:
                weights.append(layer.bias_quantizer_internal(layer.bias).numpy())
            converted.set_weights(weights)
            layers.append(converted)
        elif name == "QActivation":
            quantizer = layer.quantizer
            maximum = float(2**quantizer.integer * (1 - 2**-quantizer.bits))
            # Explicit fake-quant ranges let the standard converter recognize
            # 8-bit activation grids. Tie rounding and integer pool arithmetic
            # may differ from QKeras; this artifact is separately validated.
            value = tf.quantization.fake_quant_with_min_max_args(
                value, min=0.0, max=maximum, num_bits=8
            )
        else:
            value = getattr(tf.keras.layers, name).from_config(config)(value)
    converted = tf.keras.Model(inputs, value)
    benchmark_pixels = {
        hashlib.sha256(
            pixels(np.fromfile(case["path"], dtype=np.uint8)).tobytes()
        ).hexdigest()
        for case in cases(admission=True)
    }
    calibration_path = REPO / "models/res256/reproducibility/prepared_inputs/x_norm.npy"
    calibration = np.load(calibration_path, mmap_mode="r")
    selected = []
    for index, sample in enumerate(calibration):
        digest = hashlib.sha256(sample.astype(np.float32).tobytes()).hexdigest()
        if digest not in benchmark_pixels:
            selected.append(index)
        if len(selected) == 128:
            break
    assert len(selected) >= 100

    def representative():
        for index in selected:
            yield [np.asarray(calibration[index : index + 1], dtype=np.float32)]

    converter = tf.lite.TFLiteConverter.from_keras_model(converted)
    converter.optimizations = [tf.lite.Optimize.DEFAULT]
    converter.representative_dataset = representative
    converter.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
    converter.inference_input_type = tf.int8
    converter.inference_output_type = tf.int8
    binary = converter.convert()
    path = destination / "qat_deployment_int8.tflite"
    path.write_bytes(binary)
    interpreter = tf.lite.Interpreter(model_path=str(path), num_threads=1)
    interpreter.allocate_tensors()
    details = interpreter.get_tensor_details()
    tensor_lookup = {item["index"]: item for item in details}
    operations = interpreter._get_ops_details()
    for op in operations:
        if op["op_name"] in ["CONV_2D", "FULLY_CONNECTED"]:
            assert all(
                tensor_lookup[int(i)]["dtype"] in [np.int8, np.int32]
                for i in op["inputs"]
                if i >= 0
            )
    inp = interpreter.get_input_details()[0]
    out = interpreter.get_output_details()[0]
    validation = []
    for case in cases(admission=True):
        value = pixels(np.fromfile(case["path"], dtype=np.uint8))
        expected = float(model(value, training=False).numpy().ravel()[0])
        scale, zero = inp["quantization"]
        quantized = np.clip(np.rint(value / scale + zero), -128, 127).astype(np.int8)
        interpreter.set_tensor(inp["index"], quantized)
        interpreter.invoke()
        scale, zero = out["quantization"]
        score = float(
            (interpreter.get_tensor(out["index"]).astype(np.float32) - zero).ravel()[0]
            * scale
        )
        validation.append(
            dict(
                case_id=case["id"],
                qkeras_score=expected,
                int8_score=score,
                verdict_match=(expected >= 0) == (score >= 0),
                absolute_difference=abs(score - expected),
            )
        )
    result = dict(
        status=(
            "passed"
            if all(row["verdict_match"] for row in validation)
            else "diagnostic_only"
        ),
        identity="Native INT8 deployment conversion of frozen QKeras checkpoint; not bit-exact QKeras/hls4ml",
        sha256=hashlib.sha256(binary).hexdigest(),
        bytes=len(binary),
        calibration_source=str(calibration_path),
        calibration_indices=selected,
        benchmark_tensor_overlap_excluded=True,
        tensorflow=tf.__version__,
        input_quantization=inp["quantization"],
        output_quantization=out["quantization"],
        operations=[op["op_name"] for op in operations],
        validation=validation,
    )
    save(destination / "result.json", result)
    print(json.dumps(result, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    run(parser.parse_args().root.resolve())
