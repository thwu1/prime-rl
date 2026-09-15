#!/usr/bin/env python3
"""
CPU reference implementation for CUDA kernels: FDTD 3D stencil and Black-Scholes.

Reads CUDA kernel source files, understands the computation, implements
equivalent CPU versions, and produces binary output files.

"""
import numpy as np
import os
import json

# Load spec
with open('/app/spec.json', 'r') as f:
    spec = json.load(f)

os.makedirs('/app/output', exist_ok=True)


# ============================================================
# FDTD 3D Star Stencil
# ============================================================
# The CUDA kernel (fdtd_3d.cu) implements a 3D star stencil using
# a complex z-slice sweeping algorithm with register-based front/back
# buffers and shared memory tiling. The underlying computation is:
#
# For each point (z, y, x) in the inner volume [R:R+DIM]:
#   output[z,y,x] = stencil[0] * input[z,y,x]
#                 + sum_{i=1}^{RADIUS} stencil[i] * (
#                     input[z-i,y,x] + input[z+i,y,x] +
#                     input[z,y-i,x] + input[z,y+i,x] +
#                     input[z,y,x-i] + input[z,y,x+i]
#                   )
#
# The output is zero-initialized; only the inner region is written.

fdtd_spec = spec['kernels'][0]
RADIUS = fdtd_spec['parameters']['RADIUS']
DIM = fdtd_spec['parameters']['DIMX']
OUTER = DIM + 2 * RADIUS

# Load input data
input_vol = np.fromfile(
    '/app/data/fdtd_input.bin', dtype=np.float32
).reshape(OUTER, OUTER, OUTER)

stencil = np.fromfile(
    '/app/data/fdtd_stencil.bin', dtype=np.float32
)

# Compute star stencil (using float64 for precision, cast back to float32)
output = np.zeros((OUTER, OUTER, OUTER), dtype=np.float64)
inp = input_vol.astype(np.float64)

R = RADIUS
s, e = R, OUTER - R  # inner region: [RADIUS : RADIUS + DIM]

# Center coefficient
output[s:e, s:e, s:e] = stencil[0] * inp[s:e, s:e, s:e]

# Axis-aligned neighbor contributions
for i in range(1, R + 1):
    output[s:e, s:e, s:e] += stencil[i] * (
        # z-axis neighbors
        inp[s - i:e - i, s:e, s:e] + inp[s + i:e + i, s:e, s:e] +
        # y-axis neighbors
        inp[s:e, s - i:e - i, s:e] + inp[s:e, s + i:e + i, s:e] +
        # x-axis neighbors
        inp[s:e, s:e, s - i:e - i] + inp[s:e, s:e, s + i:e + i]
    )

fdtd_output = output.astype(np.float32)
fdtd_output.tofile('/app/output/fdtd_output.bin')
print(f"FDTD 3D: wrote {fdtd_output.size} elements to /app/output/fdtd_output.bin")


# ============================================================
# Black-Scholes Option Pricing
# ============================================================
# The CUDA kernel (black_scholes.cu) computes European call and put
# option prices using the Black-Scholes formula. Key details:
#
# 1. The cumulative normal distribution uses a polynomial approximation
#    (Abramowitz & Stegun formula 26.2.17) with coefficients:
#    A1=0.31938153, A2=-0.356563782, A3=1.781477937,
#    A4=-1.821255978, A5=1.330274429
#
# 2. CND(d) = RSQRT2PI * exp(-0.5*d^2) * K * (A1 + K*(A2 + K*(A3 + K*(A4 + K*A5))))
#    where K = 1 / (1 + 0.2316419 * |d|)
#    If d > 0: CND(d) = 1 - CND(d)
#
# 3. __fdividef(1.0f, rsqrtf(T)) = sqrt(T)
#
# 4. d1 = (log(S/X) + (R + 0.5*V^2)*T) / (V * sqrt(T))
#    d2 = d1 - V * sqrt(T)
#
# 5. Call = S * CND(d1) - X * exp(-R*T) * CND(d2)
#    Put  = X * exp(-R*T) * (1 - CND(d2)) - S * (1 - CND(d1))

bs_spec = spec['kernels'][1]
Rf = bs_spec['parameters']['RISKFREE']
V = bs_spec['parameters']['VOLATILITY']
N = bs_spec['parameters']['OPT_N']


def cnd_polynomial(d):
    """Polynomial approximation of CND matching the CUDA cndGPU function."""
    A1 = np.float64(0.31938153)
    A2 = np.float64(-0.356563782)
    A3 = np.float64(1.781477937)
    A4 = np.float64(-1.821255978)
    A5 = np.float64(1.330274429)
    RSQRT2PI = np.float64(0.39894228040143267793994605993438)

    d = np.asarray(d, dtype=np.float64)
    K = 1.0 / (1.0 + 0.2316419 * np.abs(d))
    cnd = RSQRT2PI * np.exp(-0.5 * d * d) * (
        K * (A1 + K * (A2 + K * (A3 + K * (A4 + K * A5))))
    )
    return np.where(d > 0, 1.0 - cnd, cnd)


# Load input data
S = np.fromfile('/app/data/stock_price.bin', dtype=np.float32).astype(np.float64)
X = np.fromfile('/app/data/option_strike.bin', dtype=np.float32).astype(np.float64)
T = np.fromfile('/app/data/option_years.bin', dtype=np.float32).astype(np.float64)

# Compute Black-Scholes
sqrtT = np.sqrt(T)
d1 = (np.log(S / X) + (Rf + 0.5 * V * V) * T) / (V * sqrtT)
d2 = d1 - V * sqrtT

CNDD1 = cnd_polynomial(d1)
CNDD2 = cnd_polynomial(d2)

expRT = np.exp(-Rf * T)
call_result = (S * CNDD1 - X * expRT * CNDD2).astype(np.float32)
put_result = (X * expRT * (1.0 - CNDD2) - S * (1.0 - CNDD1)).astype(np.float32)

call_result.tofile('/app/output/call_out.bin')
put_result.tofile('/app/output/put_out.bin')
print(f"Black-Scholes: wrote {N} call and {N} put prices")
print("Done.")
