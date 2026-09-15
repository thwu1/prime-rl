#!/usr/bin/env python3
"""
Benchmark runner: checks solver correctness against reference data
and reports efficiency metrics.
"""
import sys
import time
import numpy as np

try:
    import tomllib
except ImportError:
    import tomli as tomllib

sys.path.insert(0, '/app')
from solver import solve_brusselator

# Load configuration
with open('/app/config.toml', 'rb') as f:
    config = tomllib.load(f)

bru = config['brusselator']
sol = config['solver']

N = bru['N']
t_end = bru['t_end']
linear_solver = sol.get('linear_solver', 'direct')
c_backend = sol.get('c_backend', False)

print(f"=== Brusselator Solver Benchmark ===")
print(f"N={N}, t_end={t_end}, rtol={sol['rtol']}, atol={sol['atol']}")
print(f"controller={sol['controller']}, linear_solver={linear_solver}, c_backend={c_backend}")
print()

# Run solver
t0 = time.time()
t_arr, y_arr, stats = solve_brusselator(
    N=N, t_end=t_end,
    rtol=sol['rtol'], atol=sol['atol'],
    controller=sol['controller'],
    max_steps_per_jac=sol['max_steps_per_jacobian'],
    linear_solver=linear_solver,
    c_backend=c_backend,
)
elapsed = time.time() - t0
print(f"Solver completed in {elapsed:.1f}s")
print()

# Load reference
ref = np.load('/app/reference/solution_ref.npz')
y_ref = ref['y_final']

y_final = y_arr[-1]
rel_err = np.linalg.norm(y_final - y_ref) / np.linalg.norm(y_ref)

total_attempts = stats['n_steps'] + stats['n_rejected_steps']
rej_rate = stats['n_rejected_steps'] / max(1, total_attempts)

print(f"=== Results ===")
print(f"  Accepted steps:     {stats['n_steps']}")
print(f"  Rejected steps:     {stats['n_rejected_steps']} ({rej_rate:.1%})")
print(f"  Jacobian evals:     {stats['n_jacobian_evals']}")
print(f"  LU factorizations:  {stats['n_lu_factorizations']}")
print(f"  Function evals:     {stats['n_function_evals']}")
print(f"  u_max at t_end:     {y_final[0::2].max():.6f}")
print(f"  v_max at t_end:     {y_final[1::2].max():.6f}")
print(f"  Relative L2 error:  {rel_err:.6e}")
print()

# Checks
all_passed = True

if rel_err < 0.05:
    print("[PASS] Accuracy: relative error within 5%")
else:
    print(f"[FAIL] Accuracy: relative error {rel_err:.4e} > 0.05")
    all_passed = False

if stats['n_jacobian_evals'] < stats['n_steps']:
    print("[PASS] Jacobian reuse: fewer Jacobian evals than steps")
else:
    print(f"[FAIL] Jacobian reuse: {stats['n_jacobian_evals']} evals >= {stats['n_steps']} steps")
    all_passed = False

if rej_rate < 0.15:
    print("[PASS] Rejection rate within bounds")
else:
    print(f"[FAIL] Rejection rate: {rej_rate:.1%} > 15%")
    all_passed = False

if np.all(np.isfinite(y_arr)):
    print("[PASS] Solution is finite everywhere")
else:
    print("[FAIL] Solution contains NaN or Inf")
    all_passed = False

print()
if all_passed:
    print("=== ALL CHECKS PASSED ===")
else:
    print("=== CHECKS FAILED ===")
    sys.exit(1)
