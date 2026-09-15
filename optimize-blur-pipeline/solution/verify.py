#!/usr/bin/env python3
"""Compare two edge detection output images for numerical correctness."""
import struct
import sys

import numpy as np


def read_img(path):
    with open(path, "rb") as f:
        w, h = struct.unpack("ii", f.read(8))
        return np.frombuffer(f.read(), dtype=np.float32).reshape(h, w)


ref = read_img(sys.argv[1])
opt = read_img(sys.argv[2])

diff = np.abs(ref.astype(np.float64) - opt.astype(np.float64))
max_err = float(np.max(diff))
mean_err = float(np.mean(diff))

print(f"Max pixel error:  {max_err:.6f}")
print(f"Mean pixel error: {mean_err:.6f}")

if max_err < 50.0 and mean_err < 1.0:
    print("PASS: output matches reference within tolerance")
    sys.exit(0)
else:
    print("FAIL: output differs from reference beyond tolerance")
    sys.exit(1)
