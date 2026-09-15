# Pipeline Specification

## Overview

Three ONNX model files in `/app/models/` form a sequential data processing pipeline.
Each model has multiple bugs preventing validation. Fix them, compose them into a single
pipeline, and replace the ReLU activation with a custom SiLU function.

## Model 1: normalize.onnx

Computes element-wise normalization: `Y = (X - mean) / std`

- Input: float32 tensor "X" with shape [N, 4]
- Output: float32 tensor "Y" with shape [N, 4]
- Constants: `mean = [2.0, 3.0, 4.0, 5.0]`, `std = [1.0, 2.0, 1.0, 2.0]`
- All computation in float32

## Model 2: transform.onnx

Two-layer feed-forward network: `Z = activation(X @ W1 + B1) @ W2 + B2`

- Input: float32 tensor "X" with shape [N, 4]
- Output: float32 tensor "Z" with shape [N, 4]
- W1: shape [4, 8], B1: shape [8], W2: shape [8, 4], B2: shape [4]
- All weights generated with `numpy.random.RandomState(42)`, scaled by 0.5 for weights and 0.1 for biases
- **The activation in the final pipeline must be SiLU (x * sigmoid(x)), not ReLU**

## Model 3: classify.onnx

Softmax classifier: `probs = Softmax(X @ W + B, axis=-1)`

- Input: float32 tensor "X" with shape [N, 4]
- Output: float32 tensor "probs" with shape [N, 3]
- W: shape [4, 3], B: shape [3]
- Weights generated with `numpy.random.RandomState(123)`, scaled by 0.5 for W and 0.1 for B
- Softmax computed along the last axis (axis=-1)

## Pipeline Composition

Connect the three models sequentially: `normalize -> transform (SiLU) -> classify`

- Single pipeline input: float32 [N, 4]
- Single pipeline output: float32 [N, 3]
- Define SiLU as a model-local custom function using Sigmoid and Mul operators
- Save the final pipeline to `/app/pipeline.onnx`

## Test Data

- Input: `/app/test_data/input.npy`
- Expected output: `/app/test_data/expected_output.npy`

The expected output was computed using the correct pipeline (with SiLU, not ReLU).
