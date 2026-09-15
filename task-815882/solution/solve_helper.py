#!/usr/bin/env python3
"""

Solves the Newton-Schulz septic orthogonalizer task.
"""
import json
import sys
import numpy as np
from scipy.optimize import differential_evolution

# ---------------------------------------------------------------------------
# 1. Load configuration
# ---------------------------------------------------------------------------
with open("/app/config.json") as f:
    config = json.load(f)

sc = config["septic_constraints"]
x_min, x_max = sc["x_range"]
tol_lo, tol_hi = sc["tolerance_band"]
n_iter = sc["num_steps"]

# ---------------------------------------------------------------------------
# 2. Optimize septic coefficients
# ---------------------------------------------------------------------------
# The septic polynomial is phi(x) = a*x + b*x^3 + c*x^5 + d*x^7
# We maximize the leading coefficient 'a' (slope at zero, which controls
# convergence speed for small singular values) subject to:
#   phi^N(x) in [tol_lo, tol_hi] for all x in [x_min, x_max]
# ---------------------------------------------------------------------------
x_coarse = np.linspace(x_min, x_max, 1000)
x_fine = np.linspace(x_min, x_max, 100000)


def phi_n(a, b, c, d, x, n):
    """Apply phi n times to array x (vectorized)."""
    y = x.copy()
    for _ in range(n):
        y2 = y * y
        y3 = y2 * y
        y = a * y + b * y3 + c * y2 * y3 + d * y3 * y3 * y
    return y


def objective(params):
    """Minimize -a subject to convergence constraints."""
    a, b, c, d = params

    y = x_coarse.copy()
    for i in range(n_iter):
        y2 = y * y
        y3 = y2 * y
        y = a * y + b * y3 + c * y2 * y3 + d * y3 * y3 * y
        if np.any(np.abs(y) > 50):
            return 1e6

    if np.any(np.isnan(y)):
        return 1e6

    viol_lo = np.maximum(tol_lo - y, 0).max()
    viol_hi = np.maximum(y - tol_hi, 0).max()
    max_viol = max(viol_lo, viol_hi)

    if max_viol > 0:
        return -a + 5000 * max_viol
    return -a


print("Running global optimization for septic coefficients...")
bounds = [(3.0, 12.0), (-50.0, 0.0), (-20.0, 60.0), (-50.0, 20.0)]
result = differential_evolution(
    objective,
    bounds,
    seed=42,
    maxiter=1000,
    tol=1e-10,
    polish=True,
    mutation=(0.5, 1.5),
    recombination=0.9,
    popsize=40,
)

a_opt, b_opt, c_opt, d_opt = result.x
print(f"Result: a={a_opt:.6f}, b={b_opt:.6f}, c={c_opt:.6f}, d={d_opt:.6f}")
print(f"Objective: {result.fun:.6f}")

# Verify on fine grid
y_verify = phi_n(a_opt, b_opt, c_opt, d_opt, x_fine, n_iter)
constraint_ok = bool(np.all(y_verify >= tol_lo - 1e-9) and np.all(y_verify <= tol_hi + 1e-9))
print(f"Fine-grid: constraint_satisfied={constraint_ok}, range=[{y_verify.min():.6f}, {y_verify.max():.6f}]")

# If fine-grid fails, retry with tighter margins
if not constraint_ok:
    print("Retrying with tighter margins and finer grid...")
    x_medium = np.linspace(x_min, x_max, 5000)

    def objective_tight(params):
        a, b, c, d = params
        y = x_medium.copy()
        for i in range(n_iter):
            y2 = y * y
            y3 = y2 * y
            y = a * y + b * y3 + c * y2 * y3 + d * y3 * y3 * y
            if np.any(np.abs(y) > 50):
                return 1e6
        if np.any(np.isnan(y)):
            return 1e6
        margin = 0.03
        viol_lo = np.maximum((tol_lo + margin) - y, 0).max()
        viol_hi = np.maximum(y - (tol_hi - margin), 0).max()
        max_viol = max(viol_lo, viol_hi)
        if max_viol > 0:
            return -a + 10000 * max_viol
        return -a

    result2 = differential_evolution(
        objective_tight,
        bounds,
        seed=7,
        maxiter=2000,
        tol=1e-10,
        polish=True,
        popsize=50,
    )
    a_opt, b_opt, c_opt, d_opt = result2.x
    y_verify = phi_n(a_opt, b_opt, c_opt, d_opt, x_fine, n_iter)
    constraint_ok = bool(np.all(y_verify >= tol_lo - 1e-9) and np.all(y_verify <= tol_hi + 1e-9))
    print(f"Refined: a={a_opt:.6f}, b={b_opt:.6f}, c={c_opt:.6f}, d={d_opt:.6f}")
    print(f"Constraint satisfied: {constraint_ok}, range=[{y_verify.min():.6f}, {y_verify.max():.6f}]")

max_deviation = float(np.max(np.abs(y_verify - 1.0)))
print(f"Max deviation from 1: {max_deviation:.6f}")

# ---------------------------------------------------------------------------
# 3. Write the completed newton_schulz.py
# ---------------------------------------------------------------------------
# The key insight: for a scalar polynomial phi(x) = ax + bx^3 + cx^5 + dx^7,
# the matrix-level recurrence uses A = X @ X.T (representing x^2 in singular-
# value space), then X = a*X + (b*A + c*A^2 + d*A^3) @ X.
ns_code = f'''import numpy as np


def newtonschulz5(G, steps=5):
    """Quintic Newton-Schulz iteration for matrix orthogonalization."""
    assert G.ndim == 2
    a, b, c = (3.4445, -4.7750, 2.0315)
    X = G.astype(np.float64).copy()
    transposed = False
    if G.shape[0] > G.shape[1]:
        X = X.T
        transposed = True

    X = X / (np.linalg.norm(X) + 1e-7)

    for _ in range(steps):
        A = X @ X.T
        B = b * A + c * A @ A
        X = a * X + B @ X

    if transposed:
        X = X.T
    return X


def newtonschulz7(G, steps=3):
    """Septic Newton-Schulz iteration for matrix orthogonalization."""
    assert G.ndim == 2
    a, b, c, d = ({a_opt:.15f}, {b_opt:.15f}, {c_opt:.15f}, {d_opt:.15f})

    X = G.astype(np.float64).copy()
    transposed = False
    if G.shape[0] > G.shape[1]:
        X = X.T
        transposed = True

    X = X / (np.linalg.norm(X) + 1e-7)

    for _ in range(steps):
        A = X @ X.T
        A2 = A @ A
        A3 = A2 @ A
        B = b * A + c * A2 + d * A3
        X = a * X + B @ X

    if transposed:
        X = X.T
    return X


def orthogonality_error(X):
    """Compute ||X^T X - I||_F / sqrt(min(m,n)) for a matrix X."""
    m, n = X.shape
    if m >= n:
        gram = X.T @ X
        eye = np.eye(n)
        return np.linalg.norm(gram - eye) / np.sqrt(n)
    else:
        gram = X @ X.T
        eye = np.eye(m)
        return np.linalg.norm(gram - eye) / np.sqrt(m)
'''

with open("/app/newton_schulz.py", "w") as f:
    f.write(ns_code)
print("Wrote updated /app/newton_schulz.py")

# ---------------------------------------------------------------------------
# 4. Run benchmarks
# ---------------------------------------------------------------------------
if "newton_schulz" in sys.modules:
    del sys.modules["newton_schulz"]
sys.path.insert(0, "/app")
from newton_schulz import newtonschulz5, newtonschulz7, orthogonality_error

bench_config = config["benchmark"]
np.random.seed(bench_config["seed"])

quintic_errors = []
septic_errors = []

for size in bench_config["matrix_sizes"]:
    m, n = size
    errs_q = []
    errs_s = []
    for _ in range(bench_config["num_trials"]):
        G = np.random.randn(m, n)
        X5 = newtonschulz5(G, steps=5)
        X7 = newtonschulz7(G, steps=3)
        errs_q.append(float(orthogonality_error(X5)))
        errs_s.append(float(orthogonality_error(X7)))
    quintic_errors.append(float(np.mean(errs_q)))
    septic_errors.append(float(np.mean(errs_s)))
    print(f"  {m}x{n}: quintic={quintic_errors[-1]:.6f}, septic={septic_errors[-1]:.6f}")

# ---------------------------------------------------------------------------
# 5. Write results.json
# ---------------------------------------------------------------------------
results = {
    "septic_coefficients": {
        "a": float(a_opt),
        "b": float(b_opt),
        "c": float(c_opt),
        "d": float(d_opt),
    },
    "constraint_satisfied": constraint_ok,
    "max_deviation": max_deviation,
    "slope_at_zero": float(a_opt),
    "benchmark": {
        "quintic_5step_errors": quintic_errors,
        "septic_3step_errors": septic_errors,
        "matrix_sizes": bench_config["matrix_sizes"],
    },
}

with open("/app/results.json", "w") as f:
    json.dump(results, f, indent=2)

print("\nResults written to /app/results.json")
print(json.dumps(results, indent=2))
