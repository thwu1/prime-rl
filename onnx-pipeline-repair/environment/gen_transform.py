#!/usr/bin/env python3
"""Generate broken transform.onnx model.

Intended computation: Z = ReLU(X @ W1 + B1) @ W2 + B2
Bugs planted:
  1. No opset_import at all (required for IR >= 3)
  2. Both MatMul nodes output to 'matmul_out' — SSA violation
  3. Add node references 'bias1' but initializer is named 'B1'
"""
import numpy as np
import os
from onnx import helper, TensorProto, numpy_helper

os.makedirs('/app/models', exist_ok=True)

rng = np.random.RandomState(42)
W1 = (rng.randn(4, 8) * 0.5).astype(np.float32)
B1 = (rng.randn(8) * 0.1).astype(np.float32)
W2 = (rng.randn(8, 4) * 0.5).astype(np.float32)
B2 = (rng.randn(4) * 0.1).astype(np.float32)

W1_init = numpy_helper.from_array(W1, name='W1')
B1_init = numpy_helper.from_array(B1, name='B1')  # Named 'B1'
W2_init = numpy_helper.from_array(W2, name='W2')
B2_init = numpy_helper.from_array(B2, name='B2')

# BUG 2: both MatMul nodes output 'matmul_out' — SSA violation
matmul1 = helper.make_node('MatMul', ['X', 'W1'], ['matmul_out'], name='matmul1')
add1 = helper.make_node('Add', ['matmul_out', 'bias1'], ['add1_out'], name='add1')  # BUG 3: 'bias1' not 'B1'
relu = helper.make_node('Relu', ['add1_out'], ['relu_out'], name='relu')
matmul2 = helper.make_node('MatMul', ['relu_out', 'W2'], ['matmul_out'], name='matmul2')  # BUG 2: duplicate
add2 = helper.make_node('Add', ['matmul_out', 'B2'], ['Z'], name='add2')

X = helper.make_tensor_value_info('X', TensorProto.FLOAT, [None, 4])
Z = helper.make_tensor_value_info('Z', TensorProto.FLOAT, [None, 4])

graph = helper.make_graph(
    [matmul1, add1, relu, matmul2, add2],
    'transform',
    [X],
    [Z],
    initializer=[W1_init, B1_init, W2_init, B2_init]
)

# BUG 1: create model with no opset_import
model = helper.make_model(graph, opset_imports=[])
# Ensure opset_import is truly empty
del model.opset_import[:]

with open('/app/models/transform.onnx', 'wb') as f:
    f.write(model.SerializeToString())

print("Generated transform.onnx (3 bugs)")
