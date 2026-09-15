#!/bin/bash


# Deploy fixed source files
cp /solution/solver_fixed.c /app/solver.c
cp /solution/fluid_fixed.py /app/fluid.py
cp /solution/Makefile_fixed /app/Makefile

# Build the C shared library
cd /app
make clean 2>/dev/null || true
make

# Verify the simulation produces correct results
python3 -c "
import math

from fluid import EulerianFluid

# Verify closed-tank pressure convergence
f = EulerianFluid(1000.0, 20, 20, 0.05)
n = f.numY
for i in range(f.numX):
    for j in range(n):
        if i == 0 or i == f.numX - 1 or j == 0 or j == n - 1:
            f.s[i * n + j] = 0.0
        else:
            f.s[i * n + j] = 1.0
ci, cj = f.numX // 2, n // 2
f.u[ci * n + cj] = 5.0
f.u[(ci + 1) * n + cj] = -3.0
f.v[ci * n + cj] = 2.0
f.solve_incompressibility(100, 1.0 / 60, 1.5)
div = f.max_divergence()
print(f'Tank divergence after 100 iters: {div:.6f}')
assert div < 0.01, f'Divergence too high: {div}'

# Verify wind tunnel with smoke transport
f2 = EulerianFluid(1000.0, 50, 50, 0.02)
f2.setup_wind_tunnel(2.0)
f2.set_obstacle(0.4, 0.5, 0.1)
for step in range(20):
    f2.simulate(1.0 / 60, 0.0, 40, 1.9)
div2 = f2.max_divergence()
n2 = f2.numY
has_smoke = any(
    f2.m[i * n2 + j] < 0.9
    for i in range(1, 15)
    for j in range(1, n2 - 1)
)
print(f'Wind tunnel divergence: {div2:.4f}')
print(f'Smoke propagated: {has_smoke}')
assert has_smoke, 'Smoke not propagating'

# Verify v-field interpolation
f3 = EulerianFluid(1000.0, 10, 10, 0.1)
n3 = f3.numY
h3 = f3.h
for i in range(f3.numX):
    for j in range(n3):
        f3.v[i * n3 + j] = float(j)
val = f3.sample_field(5 * h3 + 0.5 * h3, 5 * h3, 'v')
print(f'V-field interpolation at face: {val:.2f} (expected 5.0)')
assert abs(val - 5.0) < 0.1

print('All verification checks passed')
"
