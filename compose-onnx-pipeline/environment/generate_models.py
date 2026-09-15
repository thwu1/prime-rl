#!/usr/bin/env python3
"""Generate three ONNX sub-models with intentional cross-model incompatibilities.

Models form a preprocess -> encoder -> classifier pipeline, but are exported
with different opset versions, tensor types, and overlapping internal names.
"""
import os
import numpy as np
import onnx
from onnx import helper, TensorProto, numpy_helper


def make_preprocess():
    """Preprocessing model: opset 11, float32.

    Key incompatibility: Squeeze uses 'axes' as an ATTRIBUTE.
    In opset 13+, 'axes' must be a separate input tensor.
    Also uses internal names 'tmp' and 'scale' that collide with encoder.
    """
    scale = numpy_helper.from_array(
        np.array([0.5, 0.5, 0.5, 0.5], dtype=np.float32), name="scale"
    )
    offset = numpy_helper.from_array(
        np.array([1.0, 1.0, 1.0, 1.0], dtype=np.float32), name="offset"
    )
    nodes = [
        helper.make_node('Squeeze', ['raw_input'], ['squeezed'], axes=[1]),
        helper.make_node('Mul', ['squeezed', 'scale'], ['tmp']),
        helper.make_node('Add', ['tmp', 'offset'], ['preprocess_output']),
    ]
    graph = helper.make_graph(
        nodes, 'preprocess',
        [helper.make_tensor_value_info('raw_input', TensorProto.FLOAT, [1, 1, 4])],
        [helper.make_tensor_value_info('preprocess_output', TensorProto.FLOAT, [1, 4])],
        initializer=[scale, offset],
    )
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid('', 11)])
    model.ir_version = 6
    onnx.checker.check_model(model)
    return model


def make_encoder():
    """Encoder model: opset 17, float16.

    Key incompatibilities:
    - Uses FLOAT16 tensors (preprocess outputs FLOAT32)
    - Internal name 'tmp' collides with preprocess
    - Initializer name 'scale' collides with preprocess
    """
    W1 = numpy_helper.from_array(
        np.eye(4, 8, dtype=np.float16), name="weights"
    )
    b1 = numpy_helper.from_array(
        np.zeros(8, dtype=np.float16), name="bias"
    )
    sc = numpy_helper.from_array(
        np.full(8, 0.5, dtype=np.float16), name="scale"
    )
    W2 = numpy_helper.from_array(
        np.eye(8, 4, dtype=np.float16), name="weights2"
    )
    nodes = [
        helper.make_node('MatMul', ['encoder_input', 'weights'], ['hidden']),
        helper.make_node('Add', ['hidden', 'bias'], ['biased']),
        helper.make_node('Relu', ['biased'], ['activated']),
        helper.make_node('Mul', ['activated', 'scale'], ['tmp']),
        helper.make_node('MatMul', ['tmp', 'weights2'], ['encoder_output']),
    ]
    graph = helper.make_graph(
        nodes, 'encoder',
        [helper.make_tensor_value_info('encoder_input', TensorProto.FLOAT16, [1, 4])],
        [helper.make_tensor_value_info('encoder_output', TensorProto.FLOAT16, [1, 4])],
        initializer=[W1, b1, sc, W2],
    )
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid('', 17)])
    model.ir_version = 8
    onnx.checker.check_model(model)
    return model


def make_classifier():
    """Classifier model: opset 13, float32.

    Key incompatibility: different opset version from encoder (13 vs 17).
    """
    cls_W = numpy_helper.from_array(
        np.array([[1, 0], [0, 1], [1, 0], [0, 1]], dtype=np.float32),
        name="cls_W",
    )
    cls_b = numpy_helper.from_array(
        np.array([0.0, 0.0], dtype=np.float32), name="cls_b"
    )
    nodes = [
        helper.make_node('Gemm', ['cls_input', 'cls_W', 'cls_b'], ['logits']),
        helper.make_node('Sigmoid', ['logits'], ['cls_output']),
    ]
    graph = helper.make_graph(
        nodes, 'classifier',
        [helper.make_tensor_value_info('cls_input', TensorProto.FLOAT, [1, 4])],
        [helper.make_tensor_value_info('cls_output', TensorProto.FLOAT, [1, 2])],
        initializer=[cls_W, cls_b],
    )
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid('', 13)])
    model.ir_version = 8
    onnx.checker.check_model(model)
    return model


if __name__ == '__main__':
    os.makedirs('/app/models', exist_ok=True)
    onnx.save(make_preprocess(), '/app/models/preprocess.onnx')
    onnx.save(make_encoder(), '/app/models/encoder.onnx')
    onnx.save(make_classifier(), '/app/models/classifier.onnx')
    print("Generated 3 sub-models in /app/models/")
