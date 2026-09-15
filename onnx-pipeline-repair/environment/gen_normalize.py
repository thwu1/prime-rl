#!/usr/bin/env python3
"""Generate broken normalize.onnx model.

Intended computation: Y = (X - mean) / std
Bugs planted:
  1. ir_version set to 1 (too low for opset 13, needs >= 7)
  2. Sub node inputs reversed: computes (mean - X) instead of (X - mean)
  3. std initializer is float64 (DOUBLE) in a float32 graph — type mismatch in Div
"""
import numpy as np
import os
from onnx import helper, TensorProto, numpy_helper

os.makedirs('/app/models', exist_ok=True)

mean_data = np.array([2.0, 3.0, 4.0, 5.0], dtype=np.float32)
std_data = np.array([1.0, 2.0, 1.0, 2.0], dtype=np.float64)  # BUG 3: float64

mean_init = numpy_helper.from_array(mean_data, name='mean')
std_init = numpy_helper.from_array(std_data, name='std')  # DOUBLE type

# BUG 2: inputs reversed — computes mean - X instead of X - mean
sub_node = helper.make_node('Sub', inputs=['mean', 'X'], outputs=['centered'], name='sub_node')
div_node = helper.make_node('Div', inputs=['centered', 'std'], outputs=['Y'], name='div_node')

X = helper.make_tensor_value_info('X', TensorProto.FLOAT, [None, 4])
Y = helper.make_tensor_value_info('Y', TensorProto.FLOAT, [None, 4])

graph = helper.make_graph(
    [sub_node, div_node],
    'normalize',
    [X],
    [Y],
    initializer=[mean_init, std_init]
)

model = helper.make_model(graph, opset_imports=[helper.make_opsetid('', 13)])
model.ir_version = 1  # BUG 1: too low

with open('/app/models/normalize.onnx', 'wb') as f:
    f.write(model.SerializeToString())

print("Generated normalize.onnx (3 bugs)")
