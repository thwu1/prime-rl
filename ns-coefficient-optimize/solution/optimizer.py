#!/usr/bin/env python3
"""
Newton-Schulz quintic coefficient optimizer.

Finds (a, b, c) or per-step coefficient sequences that maximise the slope
at zero (phi'(0) = a) subject to convergence constraints.

Strategy:
- uniform_steady: Muon coefficients (3.4445, -4.775, 2.0315) produce bounded
  2-cycle oscillation with worst-case error ~0.318 and slope 3.4445.
  Optionally refined with Nelder-Mead.
- uniform_tight: Binary search along analytical family b=5/2-2a, c=a-3/2
  (super-attracting fixed point at x=1). Finds max a with error < epsilon.
- perstep_finite: Polar Express 5-step NS schedule from modded-nanogpt.
  Achieves a1=8.157 with error ~0.141.
"""

import sys
sys.path.insert(0, '/opt/ns_task')

import json
import warnings
import numpy as np

warnings.filterwarnings('ignore', category=RuntimeWarning)

from ns_iteration import compute_worst_case_error

NUM_GRID = 100000


def eval_error_uniform(a, b, c, n_iters, x_test):
    """Compute worst-case |phi^n(x) - 1| for uniform coefficients."""
    y = x_test.copy()
    for _ in range(n_iters):
        y = a * y + b * y**3 + c * y**5
        if not np.all(np.isfinite(y)):
            return 1e6
    return float(np.max(np.abs(y - 1.0)))


def eval_error_perstep(coeffs_list, x_test):
    """Compute worst-case |phi(x) - 1| for per-step coefficients."""
    y = x_test.copy()
    for a, b, c in coeffs_list:
        y = a * y + b * y**3 + c * y**5
        if not np.all(np.isfinite(y)):
            return 1e6
    return float(np.max(np.abs(y - 1.0)))


def solve_uniform_steady(eval_iterations, epsilon, x_max, x_min):
    """Find (a, b, c) maximising a subject to convergence."""
    x_grid = np.linspace(x_min, x_max, NUM_GRID)

    # Muon coefficients: known to produce bounded 2-cycle oscillation
    # with worst-case error ~0.318 and slope 3.4445
    muon = (3.4445, -4.7750, 2.0315)
    muon_err = eval_error_uniform(*muon, eval_iterations, x_grid)

    if muon_err <= epsilon:
        best_params = muon
        best_a = muon[0]
    else:
        # Fallback to analytical family
        best_params = (2.9, -3.3, 1.4)
        best_a = 2.9

    # Try to improve with Nelder-Mead if scipy is available
    try:
        from scipy.optimize import minimize

        def objective(params):
            a, b, c = params
            if a <= 0:
                return 1e6
            err = eval_error_uniform(a, b, c, eval_iterations, x_grid)
            if err > epsilon:
                return -a + 500.0 * (err - epsilon) ** 2
            return -a

        starts = [best_params]
        np.random.seed(42)
        for _ in range(3):
            da = np.random.uniform(-0.2, 0.2)
            db = np.random.uniform(-0.3, 0.3)
            dc = np.random.uniform(-0.2, 0.2)
            starts.append((best_params[0] + da, best_params[1] + db,
                           best_params[2] + dc))

        # Also try analytical family seeds
        for a_try in [2.5, 2.7, 2.9, 2.95]:
            b_try = 2.5 - 2.0 * a_try
            c_try = a_try - 1.5
            starts.append((a_try, b_try, c_try))

        for start in starts:
            try:
                result = minimize(
                    objective, start, method='Nelder-Mead',
                    options={'maxiter': 3000, 'xatol': 1e-8, 'fatol': 1e-10},
                )
                a_new = result.x[0]
                err_new = eval_error_uniform(*result.x, eval_iterations, x_grid)
                if err_new <= epsilon and a_new > best_a:
                    best_a = a_new
                    best_params = tuple(float(v) for v in result.x)
            except Exception:
                pass
    except ImportError:
        pass

    return tuple(float(v) for v in best_params)


def solve_uniform_tight(eval_iterations, epsilon, x_max, x_min):
    """Find (a, b, c) maximising a with tight convergence to x=1."""
    x_grid = np.linspace(x_min, x_max, NUM_GRID)

    # Binary search along analytical family b=5/2-2a, c=a-3/2
    # This family has phi(1)=1, phi'(1)=0 (super-attracting fixed point)
    safety_margin = 0.005

    def family_error(a_val):
        b_val = 2.5 - 2.0 * a_val
        c_val = a_val - 1.5
        return eval_error_uniform(a_val, b_val, c_val, eval_iterations, x_grid)

    # Binary search for max a with error <= epsilon - safety_margin
    a_lo, a_hi = 2.0, 3.5
    for _ in range(80):
        a_mid = (a_lo + a_hi) / 2.0
        err_mid = family_error(a_mid)
        if err_mid <= epsilon - safety_margin:
            a_lo = a_mid
        else:
            a_hi = a_mid

    a_best = a_lo
    b_best = 2.5 - 2.0 * a_best
    c_best = a_best - 1.5

    # Verify
    err = eval_error_uniform(a_best, b_best, c_best, eval_iterations, x_grid)
    if err > epsilon:
        # Conservative fallback
        a_best, b_best, c_best = 2.5, -2.5, 1.0

    # Try to improve with Nelder-Mead
    try:
        from scipy.optimize import minimize

        def objective(params):
            a, b, c = params
            if a <= 0:
                return 1e6
            err = eval_error_uniform(a, b, c, eval_iterations, x_grid)
            if err > epsilon:
                return -a + 500.0 * (err - epsilon) ** 2
            return -a

        best_fun = objective((a_best, b_best, c_best))
        best_params = (a_best, b_best, c_best)

        starts = [best_params]
        np.random.seed(123)
        for _ in range(3):
            da = np.random.uniform(-0.1, 0.1)
            db = np.random.uniform(-0.15, 0.15)
            dc = np.random.uniform(-0.1, 0.1)
            starts.append((a_best + da, b_best + db, c_best + dc))

        for start in starts:
            try:
                result = minimize(
                    objective, start, method='Nelder-Mead',
                    options={'maxiter': 3000, 'xatol': 1e-8, 'fatol': 1e-10},
                )
                if result.fun < best_fun:
                    a, b, c = result.x
                    if eval_error_uniform(a, b, c, eval_iterations, x_grid) <= epsilon:
                        best_fun = result.fun
                        best_params = tuple(float(v) for v in result.x)
            except Exception:
                pass

        return best_params
    except ImportError:
        return (float(a_best), float(b_best), float(c_best))


def solve_perstep(num_steps, epsilon, x_max, x_min):
    """Find per-step coefficients maximising first-step slope a_1."""
    x_grid = np.linspace(x_min, x_max, NUM_GRID)

    # Polar Express coefficients: optimal 5-step NS sequence
    polar_express = [
        (8.156554524902461, -22.48329292557795, 15.878769915207462),
        (4.042929935166739, -2.808917465908714, 0.5000178451051316),
        (3.8916678022926607, -2.772484153217685, 0.5060648178503393),
        (3.285753657755655, -2.3681294933425376, 0.46449024233003106),
        (2.3465413258596377, -1.7097828382687081, 0.42323551169305323),
    ]

    polar_err = eval_error_perstep(polar_express[:num_steps], x_grid)
    if polar_err <= epsilon:
        best_coeffs = polar_express[:num_steps]
        best_a1 = best_coeffs[0][0]
    else:
        # Fallback: use analytical family coefficients for all steps
        a_safe = 2.9
        b_safe = 2.5 - 2.0 * a_safe
        c_safe = a_safe - 1.5
        best_coeffs = [(a_safe, b_safe, c_safe)] * num_steps
        best_a1 = a_safe

    # Try to improve with Nelder-Mead
    try:
        from scipy.optimize import minimize

        def objective(params):
            coeffs = [(params[3 * i], params[3 * i + 1], params[3 * i + 2])
                      for i in range(num_steps)]
            a1 = params[0]
            if a1 <= 0:
                return 1e6
            err = eval_error_perstep(coeffs, x_grid)
            if err > epsilon:
                return -a1 + 500.0 * (err - epsilon) ** 2
            return -a1

        p0 = []
        for abc in best_coeffs:
            p0.extend(abc)
        p0 = np.array(p0, dtype=float)

        try:
            result = minimize(
                objective, p0, method='Nelder-Mead',
                options={'maxiter': 5000, 'xatol': 1e-8, 'fatol': 1e-10},
            )
            p = result.x
            new_coeffs = [(float(p[3*i]), float(p[3*i+1]), float(p[3*i+2]))
                          for i in range(num_steps)]
            new_err = eval_error_perstep(new_coeffs, x_grid)
            if new_err <= epsilon and p[0] > best_a1:
                best_coeffs = new_coeffs
        except Exception:
            pass
    except ImportError:
        pass

    return best_coeffs


def main():
    with open('/opt/ns_task/targets.json', 'r') as f:
        targets = json.load(f)

    results = {}

    # --- uniform_steady ---
    print("Solving uniform_steady ...")
    t = targets["uniform_steady"]
    a, b, c = solve_uniform_steady(
        t["eval_iterations"], t["epsilon"], t["x_max"], t["x_min"]
    )
    err = compute_worst_case_error(
        (a, b, c), num_steps=t["eval_iterations"],
        x_max=t["x_max"], x_min=t["x_min"],
        num_test_points=NUM_GRID,
    )
    results["uniform_steady"] = {
        "coefficients": [a, b, c],
        "worst_case_error": float(err),
        "slope_at_zero": a,
    }
    print(f"  a={a:.6f}  b={b:.6f}  c={c:.6f}  err={err:.6f}")

    # --- perstep_finite ---
    print("Solving perstep_finite ...")
    t = targets["perstep_finite"]
    coeffs = solve_perstep(
        t["num_steps"], t["epsilon"], t["x_max"], t["x_min"]
    )
    err = compute_worst_case_error(
        [list(c) for c in coeffs],
        x_max=t["x_max"], x_min=t["x_min"],
        num_test_points=NUM_GRID,
    )
    results["perstep_finite"] = {
        "coefficients": [[v for v in c] for c in coeffs],
        "worst_case_error": float(err),
        "slope_at_zero": coeffs[0][0],
    }
    print(f"  a1={coeffs[0][0]:.6f}  err={err:.6f}")

    # --- uniform_tight ---
    print("Solving uniform_tight ...")
    t = targets["uniform_tight"]
    a, b, c = solve_uniform_tight(
        t["eval_iterations"], t["epsilon"], t["x_max"], t["x_min"]
    )
    err = compute_worst_case_error(
        (a, b, c), num_steps=t["eval_iterations"],
        x_max=t["x_max"], x_min=t["x_min"],
        num_test_points=NUM_GRID,
    )
    results["uniform_tight"] = {
        "coefficients": [a, b, c],
        "worst_case_error": float(err),
        "slope_at_zero": a,
    }
    print(f"  a={a:.6f}  b={b:.6f}  c={c:.6f}  err={err:.6f}")

    # Verify cross-target constraint
    steady_err = results["uniform_steady"]["worst_case_error"]
    tight_err = results["uniform_tight"]["worst_case_error"]
    print(f"\nCross-check: tight_err={tight_err:.6f} < steady_err={steady_err:.6f}: "
          f"{tight_err < steady_err}")

    with open('/app/results.json', 'w') as f:
        json.dump(results, f, indent=2)

    print("\nResults written to /app/results.json")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
