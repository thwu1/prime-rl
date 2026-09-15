"""
Newton-Schulz coefficient optimizer.


Finds optimal NS iteration coefficients using penalty-method optimization
with multi-start Nelder-Mead, seeded from known Muon optimizer coefficient
ratios for reliability.
"""

import json
import math
import sys
import warnings

import numpy as np
from scipy.optimize import minimize

warnings.filterwarnings("ignore")

sys.path.insert(0, "/app")
from ns_analysis import EVAL_GRID, generate_test_matrix, ns_orthogonalize_matrix

# Grids: small for fast optimization, full for verification
GRID_FULL = EVAL_GRID.copy()
GRID_SMALL = np.linspace(0.01, 1.0, 2000)

EPS_TARGET = 0.295  # internal target (tighter than test threshold 0.305)


def q_dev(grid, a, b, c, N=5):
    """Max |phi^N(x) - 1| for quintic phi(x) = ax + bx^3 + cx^5."""
    x = grid.copy()
    for _ in range(N):
        x = a * x + b * x**3 + c * x**5
    if np.any(np.isnan(x)) or np.any(np.isinf(x)):
        return 1e6
    return float(np.max(np.abs(x - 1.0)))


def s_dev(grid, a, b, c, d, N=5):
    """Max |phi^N(x) - 1| for septic phi(x) = ax + bx^3 + cx^5 + dx^7."""
    x = grid.copy()
    for _ in range(N):
        x2 = x * x
        x3 = x2 * x
        x5 = x2 * x3
        x7 = x2 * x5
        x = a * x + b * x3 + c * x5 + d * x7
        if np.any(np.isnan(x)) or np.any(np.isinf(x)) or np.max(np.abs(x)) > 1e10:
            return 1e6
    return float(np.max(np.abs(x - 1.0)))


def optimize_quintic():
    """Maximize a subject to q_dev(a, b, c, 5) <= EPS_TARGET using penalty method."""
    print("=== Quintic Optimization ===")

    def obj_fast(p):
        a, b, c = p
        dev = q_dev(GRID_SMALL, a, b, c, 5)
        if dev > EPS_TARGET:
            return -a + 100 * (dev - EPS_TARGET) ** 2
        return -a

    # Multi-start from various initial guesses around known-good region
    starts = [
        [3.55, -4.20, 1.53],
        [3.50, -4.10, 1.47],
        [3.60, -4.30, 1.58],
        [3.45, -3.95, 1.42],
        [3.65, -4.45, 1.63],
        [3.40, -3.83, 1.37],
    ]

    best_q = None
    best_qa = -1e6
    for start in starts:
        r = minimize(obj_fast, start, method="Nelder-Mead",
                     options={"maxiter": 20000, "adaptive": True,
                              "xatol": 1e-10, "fatol": 1e-10})
        dev = q_dev(GRID_FULL, r.x[0], r.x[1], r.x[2], 5)
        if dev <= 0.305 and r.x[0] > best_qa:
            best_qa = r.x[0]
            best_q = list(r.x)

    if best_q is None:
        # Emergency fallback: use a very conservative setting
        best_q = [3.20, -3.42, 1.21]

    # Polish with full grid
    def obj_full(p):
        a, b, c = p
        dev = q_dev(GRID_FULL, a, b, c, 5)
        if dev > EPS_TARGET:
            return -a + 100 * (dev - EPS_TARGET) ** 2
        return -a

    r = minimize(obj_full, best_q, method="Nelder-Mead",
                 options={"maxiter": 5000, "adaptive": True,
                          "xatol": 1e-12, "fatol": 1e-12})
    qa, qb, qc = r.x
    dev = q_dev(GRID_FULL, qa, qb, qc, 5)

    # Safety backoff if constraint violated
    backoff = 0
    while dev > 0.30 and backoff < 40:
        qa *= 0.998
        r = minimize(lambda p: q_dev(GRID_FULL, qa, p[0], p[1], 5), [qb, qc],
                     method="Nelder-Mead",
                     options={"maxiter": 5000, "adaptive": True})
        qb, qc = r.x
        dev = q_dev(GRID_FULL, qa, qb, qc, 5)
        backoff += 1

    print(f"  Final: a={qa:.8f}, b={qb:.8f}, c={qc:.8f}, dev={dev:.6f}")
    return qa, qb, qc


def optimize_septic(qa, qb, qc):
    """Maximize a subject to s_dev(a, b, c, d, 5) <= EPS_TARGET."""
    print("=== Septic Optimization ===")

    def obj_fast(p):
        a, b, c, d = p
        try:
            dev = s_dev(GRID_SMALL, a, b, c, d, 5)
        except (OverflowError, FloatingPointError):
            return 1e6
        if dev > EPS_TARGET:
            return -a + 100 * (dev - EPS_TARGET) ** 2
        return -a

    # Generate starts from quintic solution, trying to push a higher
    starts = []
    for d_start in [0.0, -0.2, 0.2, -0.5, 0.5, -1.0, 1.0]:
        for a_boost in [0.0, 0.03, 0.06, 0.10, 0.15, 0.20]:
            a_s = qa + a_boost
            scale = a_s / qa
            starts.append([a_s, qb * scale, qc * scale, d_start])

    best_s = None
    best_sa = qa - 0.2
    for start in starts:
        try:
            r = minimize(obj_fast, start, method="Nelder-Mead",
                         options={"maxiter": 15000, "adaptive": True,
                                  "xatol": 1e-10, "fatol": 1e-10})
            dev = s_dev(GRID_FULL, r.x[0], r.x[1], r.x[2], r.x[3], 5)
            if dev <= 0.305 and r.x[0] > best_sa:
                best_sa = r.x[0]
                best_s = list(r.x)
        except Exception:
            pass

    if best_s is None:
        best_s = [qa, qb, qc, 0.0]

    # Polish with full grid
    def obj_full(p):
        a, b, c, d = p
        try:
            dev = s_dev(GRID_FULL, a, b, c, d, 5)
        except (OverflowError, FloatingPointError):
            return 1e6
        if dev > EPS_TARGET:
            return -a + 100 * (dev - EPS_TARGET) ** 2
        return -a

    r = minimize(obj_full, best_s, method="Nelder-Mead",
                 options={"maxiter": 5000, "adaptive": True,
                          "xatol": 1e-12, "fatol": 1e-12})
    sa, sb, sc, sd = r.x
    dev = s_dev(GRID_FULL, sa, sb, sc, sd, 5)

    # Safety backoff
    backoff = 0
    while dev > 0.30 and backoff < 30:
        sa *= 0.998
        try:
            r = minimize(lambda p: s_dev(GRID_FULL, sa, p[0], p[1], p[2], 5),
                         [sb, sc, sd], method="Nelder-Mead",
                         options={"maxiter": 3000, "adaptive": True})
            sb, sc, sd = r.x
        except Exception:
            pass
        dev = s_dev(GRID_FULL, sa, sb, sc, sd, 5)
        backoff += 1

    # Absolute fallback: quintic with d=0
    if dev > 0.305 or sa < qa - 0.15:
        sa, sb, sc, sd = qa, qb, qc, 0.0
        dev = q_dev(GRID_FULL, qa, qb, qc, 5)
        print("  Fell back to quintic with d=0")

    print(f"  Final: a={sa:.8f}, b={sb:.8f}, c={sc:.8f}, d={sd:.8f}, dev={dev:.6f}")
    return sa, sb, sc, sd


def find_fixed_points(a, b, c):
    """Find all non-negative real fixed points of phi(x) = ax + bx^3 + cx^5.

    phi(x) = x  =>  x * ((a-1) + b*x^2 + c*x^4) = 0
    x=0 is trivial. For x>0: c*u^2 + b*u + (a-1) = 0 where u = x^2.
    """
    fps = [0.0]
    if abs(c) < 1e-15:
        if abs(b) > 1e-15:
            u = -(a - 1) / b
            if u > 1e-12:
                fps.append(math.sqrt(u))
    else:
        disc = b * b - 4 * c * (a - 1)
        if disc >= 0:
            sqrt_disc = math.sqrt(disc)
            u1 = (-b + sqrt_disc) / (2 * c)
            u2 = (-b - sqrt_disc) / (2 * c)
            for u in [u1, u2]:
                if u > 1e-12:
                    fps.append(math.sqrt(u))
    return sorted(fps)


def phi_prime(x, a, b, c):
    """Derivative of phi at x."""
    return a + 3 * b * x**2 + 5 * c * x**4


def convergence_profile(a, b, c, max_N=20):
    """Compute max deviation at N=1..max_N."""
    profile = []
    for N in range(1, max_N + 1):
        profile.append(q_dev(GRID_FULL, a, b, c, N))
    return profile


def matrix_analysis(a, b, c):
    """Apply NS iteration to test matrix and compute orthogonality error."""
    G = generate_test_matrix(42)
    X = ns_orthogonalize_matrix(G, a, b, c, n_iters=5)
    XtX = X.T @ X
    frob = float(np.linalg.norm(XtX - np.eye(48), "fro"))
    sv = np.linalg.svd(X, compute_uv=False)
    max_sv = float(np.max(np.abs(sv - 1.0)))
    return frob, max_sv


def main():
    # 1. Optimize quintic coefficients
    qa, qb, qc = optimize_quintic()

    # 2. Compute convergence profile
    profile = convergence_profile(qa, qb, qc)
    print(f"\nConvergence profile[4] (N=5): {profile[4]:.6f}")

    # 3. Optimize septic coefficients
    sa, sb, sc, sd = optimize_septic(qa, qb, qc)

    # 4. Fixed-point analysis using quintic coefficients
    fps = find_fixed_points(qa, qb, qc)
    fp_data = []
    for x_val in fps:
        pp = phi_prime(x_val, qa, qb, qc)
        fp_data.append({"x": round(x_val, 8), "phi_prime": round(pp, 8)})
        stability = "stable" if abs(pp) < 1 else "unstable"
        print(f"  Fixed point x*={x_val:.6f}, phi'(x*)={pp:.6f} ({stability})")

    # 5. Matrix analysis using quintic coefficients
    frob, max_sv = matrix_analysis(qa, qb, qc)
    print(f"  Matrix: frob_err={frob:.6f}, max_sv_dev={max_sv:.6f}")

    # Build output
    results = {
        "quintic": {
            "a": round(qa, 8),
            "b": round(qb, 8),
            "c": round(qc, 8),
            "convergence_profile": [round(v, 8) for v in profile],
        },
        "septic": {
            "a": round(sa, 8),
            "b": round(sb, 8),
            "c": round(sc, 8),
            "d": round(sd, 8),
        },
        "fixed_points": fp_data,
        "matrix_analysis": {
            "frobenius_error": round(frob, 8),
            "max_sv_deviation": round(max_sv, 8),
        },
    }

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)
    print("\nResults written to /app/results.json")


if __name__ == "__main__":
    main()
