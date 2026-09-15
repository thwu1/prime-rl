#!/bin/bash

# Copy all solution components to /app/
cp /solution/solver_impl.py /app/solver.py
cp /solution/dopt_kernel.c /app/dopt_kernel.c
cp /solution/Makefile /app/Makefile

# Build the C shared library
cd /app
make

# Verify the solver works on all instances
python3 -c "
import sys
sys.path.insert(0, '/app')
from gmpb import GMPB, GMPBConfig
from solver import DynamicOptimizer
import numpy as np

configs = [
    ('A', 10, 5, 5000, 1.5, 20, 9.0),
    ('B', 25, 5, 5000, 1.0, 20, 10.0),
    ('C', 10, 5, 1000, 2.0, 20, 20.0),
    ('D', 10, 10, 5000, 1.5, 20, 15.0),
]

for name, peaks, dim, freq, shift, envs, threshold in configs:
    config = GMPBConfig(
        num_peaks=peaks, dimension=dim, change_frequency=freq,
        shift_severity=shift, num_environments=envs,
    )
    gmpb = GMPB(config, seed=42)
    solver = DynamicOptimizer(dim=dim, bounds=(-50.0, 50.0), seed=123)
    for env in range(envs):
        solver.optimize_environment(gmpb.evaluate, freq)
        if env < envs - 1:
            gmpb.change_environment()
            solver.on_change()
    error = gmpb.offline_error()
    status = 'PASS' if error < threshold else 'FAIL'
    print(f'Instance {name}: offline_error={error:.4f} (threshold={threshold}) [{status}]')
    assert error < threshold, f'Instance {name} failed: {error:.4f} >= {threshold}'

print('All instances passed verification.')
"
