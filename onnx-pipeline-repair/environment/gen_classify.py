#!/usr/bin/env python3
"""Generate broken classify.onnx model.

Intended computation: probs = Softmax(X @ W + B, axis=-1)
Bugs planted:
  1. W initializer dims overridden to [3, 4] — actual data layout is [4, 3]
  2. Output value_info declares INT32 type instead of FLOAT
  3. Softmax axis set to 0 instead of -1 (normalizes over batch dim, not features)
"""
import numpy as np
import os
from onnx import helper, TensorProto, numpy_helper

os.makedirs('/app/models', exist_ok=True)

rng = np.random.RandomState(123)
W = (rng.randn(4, 3) * 0.5).astype(np.float32)  # Correct data shape [4, 3]
B = (rng.randn(3) * 0.1).astype(np.float32)

W_init = numpy_helper.from_array(W, name='W')
W_init.dims[:] = [3, 4]  # BUG 1: wrong dims metadata

B_init = numpy_helper.from_array(B, name='B')

matmul = helper.make_node('MatMul', ['X', 'W'], ['matmul_out'], name='matmul')
add = helper.make_node('Add', ['matmul_out', 'B'], ['logits'], name='add')
softmax = helper.make_node('Softmax', ['logits'], ['probs'], name='softmax', axis=0)  # BUG 3: axis=0

X = helper.make_tensor_value_info('X', TensorProto.FLOAT, [None, 4])
probs = helper.make_tensor_value_info('probs', TensorProto.INT32, [None, 3])  # BUG 2: INT32

graph = helper.make_graph(
    [matmul, add, softmax],
    'classify',
    [X],
    [probs],
    initializer=[W_init, B_init]
)

model = helper.make_model(graph, opset_imports=[helper.make_opsetid('', 13)])

with open('/app/models/classify.onnx', 'wb') as f:
    f.write(model.SerializeToString())

print("Generated classify.onnx (3 bugs)")
