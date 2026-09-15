#!/usr/bin/env python3
"""Generate deterministic binary input data for CUDA kernel validation task."""
import random
import struct
import math
import os

random.seed(42)
os.makedirs('/app/data', exist_ok=True)


def randn():
    """Standard normal via Box-Muller transform."""
    u1 = random.random()
    while u1 == 0:
        u1 = random.random()
    u2 = random.random()
    return math.sqrt(-2.0 * math.log(u1)) * math.cos(2.0 * math.pi * u2)


def write_floats(filename, values):
    with open(filename, 'wb') as f:
        f.write(struct.pack('<{}f'.format(len(values)), *values))


# --- FDTD 3D Stencil ---
# RADIUS=4, DIM=16, padded outer dim = 24
OUTER = 24
fdtd_input = [randn() for _ in range(OUTER * OUTER * OUTER)]
write_floats('/app/data/fdtd_input.bin', fdtd_input)

# Stencil coefficients: 5 values (RADIUS+1) - realistic finite-difference weights
stencil_coeffs = [0.6, -0.1, 0.02, -0.003, 0.0004]
write_floats('/app/data/fdtd_stencil.bin', stencil_coeffs)

# --- Black-Scholes ---
N = 2048
stock_price = [random.uniform(10.0, 100.0) for _ in range(N)]
option_strike = [random.uniform(10.0, 100.0) for _ in range(N)]
option_years = [random.uniform(0.25, 2.0) for _ in range(N)]

write_floats('/app/data/stock_price.bin', stock_price)
write_floats('/app/data/option_strike.bin', option_strike)
write_floats('/app/data/option_years.bin', option_years)
