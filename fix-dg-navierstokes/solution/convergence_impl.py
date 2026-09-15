#!/usr/bin/env python3
"""
Convergence study for the DG Navier-Stokes solver.

Runs the solver on successively refined meshes, computes L2 errors,
and determines observed convergence rates via log-log linear regression.
For RT_{k+1}/DG_k with k=1, theory predicts velocity rates of ~2.
Pressure rates are ~1.0-1.2 due to upwind flux numerical viscosity.

"""

import json
import sys

import numpy as np

sys.path.insert(0, "/app")
from solver import solve

mesh_sizes = [8, 16, 32]
errors_u = []
errors_p = []

for n in mesh_sizes:
    print(f"Running mesh {n}x{n} ...")
    errs = solve(n_cells=n, num_time_steps=40, t_end=10.0)
    errors_u.append(errs["e_u"])
    errors_p.append(errs["e_p"])
    print(f"  e_u = {errs['e_u']:.5e},  e_p = {errs['e_p']:.5e}")

# Compute observed convergence rates via least-squares in log space:
#   log(error) = rate * log(h) + C
h_vals = [1.0 / n for n in mesh_sizes]
log_h = np.log(h_vals)

rate_u = float(np.polyfit(log_h, np.log(errors_u), 1)[0])
rate_p = float(np.polyfit(log_h, np.log(errors_p), 1)[0])

results = {
    "mesh_sizes": mesh_sizes,
    "errors_u": errors_u,
    "errors_p": errors_p,
    "rate_u": rate_u,
    "rate_p": rate_p,
}

with open("/app/convergence.json", "w") as f:
    json.dump(results, f, indent=2)

print(f"\nConvergence rates:")
print(f"  velocity: {rate_u:.2f}  (theory: ~2.0)")
print(f"  pressure: {rate_p:.2f}  (theory: ~1.0-1.2 with upwind DG)")
print("Results written to /app/convergence.json")
