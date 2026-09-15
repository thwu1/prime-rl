#!/bin/bash

# Install the implementation
cp /solution/solver.py /app/quantizer.py

# Verify core functions are importable and produce valid output
python3 -c "
import sys, numpy as np
sys.path.insert(0, '/app')
from quantizer import (uniform_quantize, compute_hessian, obq_quantize,
                        obq_quantize_actorder, mixed_precision_search)

# Quick smoke test
x = np.array([0.5, -0.3, 0.8, -0.1])
q = uniform_quantize(x, 4)
print('uniform_quantize OK:', q)

X = np.random.randn(32, 8)
H = compute_hessian(X)
print('compute_hessian OK: shape', H.shape)

W = np.random.randn(4, 8) * 0.1
Q, err = obq_quantize(W, H, 4)
print('obq_quantize OK: error', err)

Q2, err2, perm = obq_quantize_actorder(W, H, 4)
print('obq_quantize_actorder OK: error', err2)

result = mixed_precision_search(
    [(4,8)], {(0,2): 10.0, (0,4): 3.0}, [2,4], 64)
print('mixed_precision_search OK:', result)
"
