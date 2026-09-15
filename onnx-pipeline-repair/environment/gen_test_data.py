#!/usr/bin/env python3
"""Generate test data for the correct pipeline.

Pipeline: normalize (X-mean)/std -> transform with SiLU -> classify with softmax(axis=-1)
"""
import numpy as np
import os

os.makedirs('/app/test_data', exist_ok=True)

# Test input
X = np.array([
    [1.0, 2.0, 3.0, 4.0],
    [0.5, 1.5, 2.5, 3.5],
    [0.0, 1.0, 2.0, 3.0]
], dtype=np.float32)
np.save('/app/test_data/input.npy', X)

# Step 1: Normalize — Y = (X - mean) / std
mean = np.array([2.0, 3.0, 4.0, 5.0], dtype=np.float32)
std = np.array([1.0, 2.0, 1.0, 2.0], dtype=np.float32)
Y = (X - mean) / std

# Step 2: Transform with SiLU activation
rng = np.random.RandomState(42)
W1 = (rng.randn(4, 8) * 0.5).astype(np.float32)
B1 = (rng.randn(8) * 0.1).astype(np.float32)
W2 = (rng.randn(8, 4) * 0.5).astype(np.float32)
B2 = (rng.randn(4) * 0.1).astype(np.float32)

hidden = Y @ W1 + B1
sigmoid_h = 1.0 / (1.0 + np.exp(-hidden))
silu_out = hidden * sigmoid_h
Z = silu_out @ W2 + B2

# Step 3: Classify — probs = Softmax(Z @ W + B, axis=-1)
rng2 = np.random.RandomState(123)
W = (rng2.randn(4, 3) * 0.5).astype(np.float32)
B = (rng2.randn(3) * 0.1).astype(np.float32)

logits = Z @ W + B
logits_shifted = logits - logits.max(axis=-1, keepdims=True)
exp_logits = np.exp(logits_shifted)
probs = exp_logits / exp_logits.sum(axis=-1, keepdims=True)

np.save('/app/test_data/expected_output.npy', probs)

print(f"Input shape: {X.shape}")
print(f"Expected output shape: {probs.shape}")
print(f"Expected output:\n{probs}")
