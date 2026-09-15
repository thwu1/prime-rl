#!/usr/bin/env python3
"""
Fix three broken ONNX models, compose them into a pipeline, and add a custom SiLU function.

Bugs fixed:
  normalize.onnx:
    1. ir_version 1 -> match onnx.IR_VERSION
    2. Sub inputs reversed (mean - X) -> (X - mean)
    3. std initializer DOUBLE -> FLOAT

  transform.onnx:
    1. Missing opset_import -> add default opset 13
    2. Duplicate output name 'matmul_out' -> rename second to 'matmul2_out'
    3. Add node references 'bias1' -> 'B1'

  classify.onnx:
    1. W dims [3, 4] -> [4, 3]
    2. Output type INT32 -> FLOAT
    3. Softmax axis 0 -> -1
"""

import numpy as np
import onnx
from onnx import helper, TensorProto, numpy_helper, checker, compose, shape_inference

TARGET_IR = onnx.IR_VERSION

# ============================================================
# Fix normalize.onnx
# ============================================================
norm = onnx.load('/app/models/normalize.onnx')

# Fix 1: IR version too low for opset 13
norm.ir_version = TARGET_IR

# Fix 2: Sub inputs reversed — should be (X - mean), not (mean - X)
sub_node = norm.graph.node[0]
assert sub_node.op_type == 'Sub'
sub_node.input[0] = 'X'
sub_node.input[1] = 'mean'

# Fix 3: std initializer is DOUBLE, should be FLOAT
for i, init in enumerate(norm.graph.initializer):
    if init.name == 'std':
        std_data = numpy_helper.to_array(init).astype(np.float32)
        new_init = numpy_helper.from_array(std_data, name='std')
        norm.graph.initializer[i].CopyFrom(new_init)

checker.check_model(norm, full_check=True)
print("normalize.onnx fixed")

# ============================================================
# Fix transform.onnx
# ============================================================
trans = onnx.load('/app/models/transform.onnx')

# Fix 1: Missing opset_import
op_import = trans.opset_import.add()
op_import.domain = ''
op_import.version = 13

# Ensure IR version matches
trans.ir_version = TARGET_IR

# Fix 2: SSA violation — both MatMul nodes output 'matmul_out'
# node[3] is matmul2, node[4] is add2 that consumes matmul2's output
trans.graph.node[3].output[0] = 'matmul2_out'
trans.graph.node[4].input[0] = 'matmul2_out'

# Fix 3: Add node references 'bias1' but initializer is 'B1'
trans.graph.node[1].input[1] = 'B1'

checker.check_model(trans, full_check=True)
print("transform.onnx fixed")

# ============================================================
# Fix classify.onnx
# ============================================================
cls = onnx.load('/app/models/classify.onnx')

# Ensure IR version matches
cls.ir_version = TARGET_IR

# Fix 1: W initializer dims should be [4, 3], not [3, 4]
for init in cls.graph.initializer:
    if init.name == 'W':
        init.dims[:] = [4, 3]

# Fix 2: Output type should be FLOAT, not INT32
cls.graph.output[0].type.tensor_type.elem_type = TensorProto.FLOAT

# Fix 3: Softmax axis should be -1 (feature dim), not 0 (batch dim)
for node in cls.graph.node:
    if node.op_type == 'Softmax':
        for attr in node.attribute:
            if attr.name == 'axis':
                attr.i = -1

checker.check_model(cls, full_check=True)
print("classify.onnx fixed")

# ============================================================
# Compose pipeline: normalize -> transform -> classify
# ============================================================

# Merge normalize + transform
pipeline_step = compose.merge_models(
    norm, trans,
    io_map=[('Y', 'X')],
    prefix1='norm_',
    prefix2='trans_',
)
print("Merged normalize + transform")

# Merge step + classify
pipeline = compose.merge_models(
    pipeline_step, cls,
    io_map=[('trans_Z', 'X')],
    prefix1='',
    prefix2='cls_',
)
print("Merged with classify")

# ============================================================
# Replace ReLU with SiLU in the composed pipeline
# ============================================================

# Find the Relu node (from transform, now prefixed)
for node in pipeline.graph.node:
    if node.op_type == 'Relu':
        node.op_type = 'SiLU'
        node.domain = 'custom'
        break

# Add custom domain opset import
custom_import = pipeline.opset_import.add()
custom_import.domain = 'custom'
custom_import.version = 1

# Define SiLU function: output = input * sigmoid(input)
silu_func = helper.make_function(
    domain='custom',
    fname='SiLU',
    inputs=['silu_in'],
    outputs=['silu_out'],
    nodes=[
        helper.make_node('Sigmoid', ['silu_in'], ['sig_out']),
        helper.make_node('Mul', ['silu_in', 'sig_out'], ['silu_out']),
    ],
    opset_imports=[helper.make_opsetid('', 13)],
)
pipeline.functions.append(silu_func)

# ============================================================
# Shape inference and final validation
# ============================================================
pipeline = shape_inference.infer_shapes(pipeline, check_type=True)
checker.check_model(pipeline, full_check=True)

# Save
onnx.save(pipeline, '/app/pipeline.onnx')
print("Pipeline saved to /app/pipeline.onnx")

# Quick verification with onnxruntime
import onnxruntime as ort

X = np.load('/app/test_data/input.npy')
expected = np.load('/app/test_data/expected_output.npy')

sess = ort.InferenceSession('/app/pipeline.onnx')
input_name = sess.get_inputs()[0].name
result = sess.run(None, {input_name: X})[0]

max_diff = np.max(np.abs(result - expected))
print(f"Max absolute difference from expected: {max_diff:.2e}")
assert max_diff < 1e-4, f"Output mismatch: max diff = {max_diff}"
print("Verification passed")
