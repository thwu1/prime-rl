#!/usr/bin/env python3
"""Generate deterministic float32 microscopy-like input data."""

import numpy as np

rng = np.random.RandomState(42)

T, Z, Y, X = 2, 3, 128, 192
data = np.zeros((T, Z, Y, X), dtype=np.float32)

for t in range(T):
    for z in range(Z):
        yy, xx = np.meshgrid(
            np.arange(Y, dtype=np.float32),
            np.arange(X, dtype=np.float32),
            indexing='ij',
        )
        base = (
            np.sin(yy * 0.05 + t * 0.3) * np.cos(xx * 0.04 + z * 0.5) * 500.0
            + 500.0
        )
        noise = rng.randn(Y, X).astype(np.float32) * 20.0
        data[t, z] = (base + noise).astype(np.float32)

np.save('/app/dataset.npy', data)
print(f"Generated dataset.npy: shape={data.shape}, dtype={data.dtype}")
