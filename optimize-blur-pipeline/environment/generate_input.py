#!/usr/bin/env python3
"""Generate a deterministic 2048x2048 test image for benchmarking."""
import struct
import random
import array

W, H = 2048, 2048
SEED = 42

random.seed(SEED)
pixels = array.array('f', (random.uniform(0.0, 255.0) for _ in range(W * H)))

with open("/app/input.bin", "wb") as f:
    f.write(struct.pack("ii", W, H))
    pixels.tofile(f)

print(f"Generated {W}x{H} test image ({W * H * 4} bytes)")
