#!/usr/bin/env python3
"""Generate quantized data for the NF4 reverse-engineering task.
No ground-truth answers are stored — tests verify properties only."""
import numpy as np
from scipy.stats import norm
import json
import struct
import os

N_WEIGHTS = 16384
BLOCK_SIZE = 64
SEED = 12345
ALPHA = float(norm.cdf(np.sqrt(3)))

rng = np.random.RandomState(SEED)
weights = rng.randn(N_WEIGHTS).astype(np.float32)

Q = norm.ppf
Z = Q(ALPHA)
delta1 = (ALPHA - 0.5) / 7
delta2 = (ALPHA - 0.5) / 8

codebook = np.zeros(16, dtype=np.float64)
for i in range(7):
    codebook[i] = -Q(ALPHA - i * delta1) / Z
for i in range(8):
    codebook[i + 8] = Q(0.5 + (i + 1) * delta2) / Z
codebook_f32 = codebook.astype(np.float32)

n_blocks = N_WEIGHTS // BLOCK_SIZE
scales = np.zeros(n_blocks, dtype=np.float32)
indices = np.zeros(N_WEIGHTS, dtype=np.uint8)

for b in range(n_blocks):
    s, e = b * BLOCK_SIZE, (b + 1) * BLOCK_SIZE
    block = weights[s:e]
    scale = float(np.max(np.abs(block)))
    scales[b] = scale
    if scale > 0:
        normalized = block / scale
        dists = np.abs(normalized[:, None] - codebook_f32[None, :])
        indices[s:e] = np.argmin(dists, axis=1).astype(np.uint8)

packed = np.zeros(N_WEIGHTS // 2, dtype=np.uint8)
for i in range(0, N_WEIGHTS, 2):
    packed[i // 2] = (indices[i] & 0x0F) | ((indices[i + 1] & 0x0F) << 4)

os.makedirs('/app', exist_ok=True)
with open('/app/quantized_data.bin', 'wb') as f:
    f.write(struct.pack('<II', N_WEIGHTS, BLOCK_SIZE))
    scales.tofile(f)
    packed.tofile(f)

weights.tofile('/app/original_weights.bin')

with open('/app/metadata.json', 'w') as f:
    json.dump({
        "format": "nfq4",
        "description": "Custom 4-bit NormalFloat quantization with per-block absmax scaling",
        "n_weights": N_WEIGHTS,
        "block_size": BLOCK_SIZE,
        "bits": 4
    }, f, indent=2)
