
"""Tests for ONNX pipeline composition task.

Verifies that /app/pipeline.onnx is a correctly composed model from
three sub-models with all incompatibilities resolved.
"""
import os

import numpy as np
import onnx
import onnxruntime as ort
import pytest
from onnx import TensorProto

PIPELINE_PATH = "/app/pipeline.onnx"


def test_pipeline_exists():
    """Pipeline model file must exist at the specified path."""
    assert os.path.exists(PIPELINE_PATH), f"Pipeline model not found at {PIPELINE_PATH}"


def test_pipeline_validates():
    """Pipeline must pass full ONNX model validation including shape inference."""
    model = onnx.load(PIPELINE_PATH)
    # full_check=True also runs shape inference
    onnx.checker.check_model(model, full_check=True)


def test_single_opset_17_or_higher():
    """Pipeline must use exactly one opset import for default domain, version >= 17."""
    model = onnx.load(PIPELINE_PATH)
    default_opsets = [
        op for op in model.opset_import if op.domain == "" or op.domain == "ai.onnx"
    ]
    assert (
        len(default_opsets) == 1
    ), f"Expected exactly 1 default opset import, got {len(default_opsets)}"
    assert (
        default_opsets[0].version >= 17
    ), f"Opset version must be >= 17, got {default_opsets[0].version}"


def test_correct_io_names():
    """Pipeline must have correct input and output names."""
    model = onnx.load(PIPELINE_PATH)
    assert (
        len(model.graph.input) == 1
    ), f"Expected 1 graph input, got {len(model.graph.input)}"
    assert (
        model.graph.input[0].name == "raw_input"
    ), f"Input name must be 'raw_input', got '{model.graph.input[0].name}'"
    assert (
        len(model.graph.output) == 1
    ), f"Expected 1 graph output, got {len(model.graph.output)}"
    assert (
        model.graph.output[0].name == "prediction"
    ), f"Output name must be 'prediction', got '{model.graph.output[0].name}'"


def test_correct_io_types():
    """Pipeline input and output must both be float32."""
    model = onnx.load(PIPELINE_PATH)
    input_type = model.graph.input[0].type.tensor_type.elem_type
    output_type = model.graph.output[0].type.tensor_type.elem_type
    assert (
        input_type == TensorProto.FLOAT
    ), f"Input type must be FLOAT (1), got {input_type}"
    assert (
        output_type == TensorProto.FLOAT
    ), f"Output type must be FLOAT (1), got {output_type}"


def test_squeeze_no_axes_attribute():
    """Any Squeeze node must use axes as input, not as attribute (required for opset >= 13)."""
    model = onnx.load(PIPELINE_PATH)
    for node in model.graph.node:
        if node.op_type == "Squeeze":
            attr_names = [a.name for a in node.attribute]
            assert "axes" not in attr_names, (
                "Squeeze node still uses 'axes' as attribute — "
                "this is invalid for opset >= 13 and must be converted to an input"
            )


def test_cast_nodes_present():
    """Pipeline must include Cast nodes for float32/float16 type conversion."""
    model = onnx.load(PIPELINE_PATH)
    cast_nodes = [n for n in model.graph.node if n.op_type == "Cast"]
    assert (
        len(cast_nodes) >= 2
    ), f"Expected >= 2 Cast nodes for type conversion, found {len(cast_nodes)}"
    cast_to_types = set()
    for cn in cast_nodes:
        for attr in cn.attribute:
            if attr.name == "to":
                cast_to_types.add(attr.i)
    assert TensorProto.FLOAT16 in cast_to_types, "Missing Cast to FLOAT16"
    assert TensorProto.FLOAT in cast_to_types, "Missing Cast to FLOAT (FLOAT32)"


def test_ssa_unique_outputs():
    """No two nodes may produce the same output name (SSA property)."""
    model = onnx.load(PIPELINE_PATH)
    all_outputs = []
    for node in model.graph.node:
        for o in node.output:
            if o:
                all_outputs.append(o)
    dupes = {n for n in all_outputs if all_outputs.count(n) > 1}
    assert not dupes, f"SSA violation — duplicate node output names: {dupes}"


def test_unique_initializer_names():
    """All initializer names must be unique (no name collisions from sub-models)."""
    model = onnx.load(PIPELINE_PATH)
    names = [i.name for i in model.graph.initializer]
    dupes = {n for n in names if names.count(n) > 1}
    assert not dupes, f"Duplicate initializer names (name collision): {dupes}"


def test_inference_correctness():
    """Pipeline must produce numerically correct output via onnxruntime."""
    session = ort.InferenceSession(PIPELINE_PATH)
    input_data = np.array([[[2.0, 4.0, 6.0, 8.0]]], dtype=np.float32)
    result = session.run(None, {"raw_input": input_data})
    output = result[0]

    # Expected computation trace:
    # Preprocess: squeeze([[[2,4,6,8]]]) -> [[2,4,6,8]]
    #             * 0.5 -> [[1,2,3,4]]
    #             + 1.0 -> [[2,3,4,5]]
    # Cast float32 -> float16
    # Encoder:    matmul(eye4x8) -> [[2,3,4,5,0,0,0,0]]
    #             + 0 -> same, relu -> same
    #             * 0.5 -> [[1,1.5,2,2.5,0,0,0,0]]
    #             matmul(eye8x4) -> [[1,1.5,2,2.5]]
    # Cast float16 -> float32
    # Classifier: gemm([[1,0],[0,1],[1,0],[0,1]]) -> [[3.0, 4.0]]
    #             sigmoid -> [[sigmoid(3), sigmoid(4)]]
    expected = np.array(
        [[1.0 / (1 + np.exp(-3.0)), 1.0 / (1 + np.exp(-4.0))]], dtype=np.float32
    )
    np.testing.assert_allclose(output, expected, rtol=1e-3, atol=1e-3)
