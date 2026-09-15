
import pytest
import numpy as np
import onnx
from onnx import checker, shape_inference, TensorProto
import onnxruntime as ort

PIPELINE_PATH = "/app/pipeline.onnx"
TEST_INPUT_PATH = "/app/test_data/input.npy"
EXPECTED_OUTPUT_PATH = "/app/test_data/expected_output.npy"


def test_pipeline_validates():
    """Pipeline must pass onnx.checker.check_model with full_check=True."""
    model = onnx.load(PIPELINE_PATH)
    checker.check_model(model, full_check=True)


def test_pipeline_has_silu_function():
    """Pipeline must contain a model-local SiLU function using Sigmoid + Mul."""
    model = onnx.load(PIPELINE_PATH)
    silu_funcs = [f for f in model.functions if "SiLU" in f.name]
    assert len(silu_funcs) >= 1, (
        f"No function with 'SiLU' in name found. "
        f"Functions present: {[f.name for f in model.functions]}"
    )
    silu = silu_funcs[0]
    assert len(silu.input) == 1, f"SiLU function should have 1 input, has {len(silu.input)}"
    assert len(silu.output) == 1, f"SiLU function should have 1 output, has {len(silu.output)}"
    op_types = {n.op_type for n in silu.node}
    assert "Sigmoid" in op_types, f"SiLU function must use Sigmoid op. Ops found: {op_types}"
    assert "Mul" in op_types, f"SiLU function must use Mul op. Ops found: {op_types}"


def test_pipeline_io_spec():
    """Pipeline must have single float32 input [N, 4] and single float32 output [N, 3]."""
    model = onnx.load(PIPELINE_PATH)
    graph = model.graph

    assert len(graph.input) == 1, f"Expected 1 input, got {len(graph.input)}"
    assert len(graph.output) == 1, f"Expected 1 output, got {len(graph.output)}"

    inp = graph.input[0]
    out = graph.output[0]

    # Input type and shape
    assert inp.type.tensor_type.elem_type == TensorProto.FLOAT, (
        f"Input should be FLOAT, got {inp.type.tensor_type.elem_type}"
    )
    inp_dims = inp.type.tensor_type.shape.dim
    assert len(inp_dims) == 2, f"Input should be 2D, got {len(inp_dims)}D"
    assert inp_dims[1].dim_value == 4, f"Input dim[1] should be 4, got {inp_dims[1].dim_value}"

    # Output type and shape
    assert out.type.tensor_type.elem_type == TensorProto.FLOAT, (
        f"Output should be FLOAT, got {out.type.tensor_type.elem_type}"
    )
    out_dims = out.type.tensor_type.shape.dim
    assert len(out_dims) == 2, f"Output should be 2D, got {len(out_dims)}D"
    assert out_dims[1].dim_value == 3, f"Output dim[1] should be 3, got {out_dims[1].dim_value}"


def test_pipeline_numerical_correctness():
    """Pipeline output must match expected values computed from the correct pipeline."""
    X = np.load(TEST_INPUT_PATH)
    expected = np.load(EXPECTED_OUTPUT_PATH)

    sess = ort.InferenceSession(PIPELINE_PATH)
    input_name = sess.get_inputs()[0].name
    result = sess.run(None, {input_name: X})[0]

    assert result.shape == expected.shape, (
        f"Shape mismatch: got {result.shape}, expected {expected.shape}"
    )
    np.testing.assert_allclose(
        result, expected, rtol=1e-5, atol=1e-5,
        err_msg="Pipeline output does not match expected values"
    )


def test_pipeline_dynamic_batch():
    """Pipeline must handle variable batch sizes."""
    sess = ort.InferenceSession(PIPELINE_PATH)
    input_name = sess.get_inputs()[0].name

    # Single sample
    X1 = np.array([[1.0, 2.0, 3.0, 4.0]], dtype=np.float32)
    result1 = sess.run(None, {input_name: X1})[0]
    assert result1.shape == (1, 3), f"Batch=1: expected shape (1, 3), got {result1.shape}"
    # Softmax outputs must sum to 1
    np.testing.assert_allclose(
        result1.sum(axis=-1), [1.0], atol=1e-5,
        err_msg="Softmax output does not sum to 1 for batch=1"
    )

    # Larger batch
    X7 = np.random.RandomState(999).randn(7, 4).astype(np.float32)
    result7 = sess.run(None, {input_name: X7})[0]
    assert result7.shape == (7, 3), f"Batch=7: expected shape (7, 3), got {result7.shape}"
    np.testing.assert_allclose(
        result7.sum(axis=-1), np.ones(7), atol=1e-5,
        err_msg="Softmax output does not sum to 1 for batch=7"
    )


def test_pipeline_shape_inference():
    """Shape inference must succeed on the pipeline without errors."""
    model = onnx.load(PIPELINE_PATH)
    inferred = shape_inference.infer_shapes(model, check_type=True, strict_mode=True)
    # Verify output shape info was inferred
    assert len(inferred.graph.output) == 1
    out_shape = inferred.graph.output[0].type.tensor_type.shape
    assert len(out_shape.dim) == 2
