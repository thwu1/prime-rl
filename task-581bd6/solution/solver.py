#!/usr/bin/env python3

"""
Continuation-based BVP solver for singularly perturbed problems.

Solves 5 BVP test problems at eps = 0.1, 0.01, 0.001 using parameter
continuation with adaptive mesh refinement via scipy.integrate.solve_bvp.
"""

import json
import sys

import numpy as np
from scipy.integrate import solve_bvp


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def log_cosh_safe(x):
    """Numerically stable ln(cosh(x)).  Avoids overflow for large |x|."""
    ax = np.abs(np.asarray(x, dtype=float))
    return ax + np.log1p(np.exp(-2.0 * ax)) - np.log(2.0)


def safe_exp(x, cutoff=700.0):
    """exp(x) with underflow protection (returns 0 for very negative x)."""
    xa = np.asarray(x, dtype=float)
    return np.where(xa > -cutoff, np.exp(np.clip(xa, -cutoff, cutoff)), 0.0)


def dense_mesh(a, b, layer_locs, layer_width, n_base=100, n_layer=250):
    """Build a mesh with points concentrated near layer locations."""
    parts = [np.linspace(a, b, n_base)]
    for loc in layer_locs:
        left = max(a, loc - 5.0 * layer_width)
        right = min(b, loc + 5.0 * layer_width)
        if right > left:
            parts.append(np.linspace(left, right, n_layer))
    mesh = np.sort(np.unique(np.concatenate(parts)))
    # Remove near-duplicates that cause division-by-zero in solve_bvp
    diffs = np.diff(mesh)
    keep = np.concatenate([[True], diffs > 1e-12])
    return mesh[keep]


# ---------------------------------------------------------------------------
# Problem definitions
# ---------------------------------------------------------------------------

def build_problem(pid, eps):
    """
    Return (fun, fun_jac, bc, domain, x0, y0) for a given problem / eps.
    """

    if pid == "bvpT2":
        # eps*z'' = z',  z(0)=1, z(1)=0,  t in [0,1]
        # Right boundary layer of width O(eps) at t=1
        a, b = 0.0, 1.0

        def fun(x, y):
            return np.vstack([y[1], y[1] / eps])

        def fun_jac(x, y):
            m = x.size
            J = np.zeros((2, 2, m))
            J[0, 1, :] = 1.0
            J[1, 1, :] = 1.0 / eps
            return J

        def bc(ya, yb):
            return np.array([ya[0] - 1.0, yb[0]])

        w = max(10.0 * eps, 0.02)
        x0 = dense_mesh(a, b, [1.0], w)
        y0 = np.vstack([1.0 - x0, -np.ones_like(x0)])

    elif pid == "bvpT10":
        # eps*z'' = -t*z',  z(-1)=0, z(1)=2,  t in [-1,1]
        # Turning point at t=0, width O(sqrt(eps))
        a, b = -1.0, 1.0

        def fun(x, y):
            return np.vstack([y[1], -x * y[1] / eps])

        def fun_jac(x, y):
            m = x.size
            J = np.zeros((2, 2, m))
            J[0, 1, :] = 1.0
            J[1, 1, :] = -x / eps
            return J

        def bc(ya, yb):
            return np.array([ya[0], yb[0] - 2.0])

        w = max(np.sqrt(eps), 0.02)
        x0 = dense_mesh(a, b, [0.0], w)
        y0 = np.vstack([x0 + 1.0, np.ones_like(x0)])

    elif pid == "bvpT14":
        # eps*z'' = z - (1+eps*pi^2)*cos(pi*t),
        # z(-1)=exp(-2/sqrt(eps)), z(1)=exp(-2/sqrt(eps)), t in [-1,1]
        # Double boundary layers at t=-1 and t=1, width O(sqrt(eps))
        a, b = -1.0, 1.0
        se = np.sqrt(eps)
        bc_val = float(safe_exp(-2.0 / se))

        def fun(x, y):
            return np.vstack([
                y[1],
                (y[0] - (1.0 + eps * np.pi ** 2) * np.cos(np.pi * x)) / eps,
            ])

        def fun_jac(x, y):
            m = x.size
            J = np.zeros((2, 2, m))
            J[0, 1, :] = 1.0
            J[1, 0, :] = 1.0 / eps
            return J

        def bc(ya, yb):
            return np.array([ya[0] - bc_val, yb[0] - bc_val])

        w = max(se, 0.02)
        x0 = dense_mesh(a, b, [-1.0, 1.0], w, n_base=100, n_layer=200)
        y0 = np.vstack([
            np.cos(np.pi * x0),
            -np.pi * np.sin(np.pi * x0),
        ])

    elif pid == "bvpT20":
        # eps*z'' = -(z')^2 + 1,  t in [0,1]
        # Nonlinear, corner layer at t=0.745, width O(eps)
        a, b = 0.0, 1.0
        bc_left = float(1.0 + eps * log_cosh_safe(-0.745 / eps))
        bc_right = float(1.0 + eps * log_cosh_safe(0.255 / eps))
        tc = 0.745

        def fun(x, y):
            return np.vstack([y[1], (-y[1] ** 2 + 1.0) / eps])

        def fun_jac(x, y):
            m = x.size
            J = np.zeros((2, 2, m))
            J[0, 1, :] = 1.0
            J[1, 1, :] = -2.0 * y[1] / eps
            return J

        def bc(ya, yb):
            return np.array([ya[0] - bc_left, yb[0] - bc_right])

        w = max(10.0 * eps, 0.02)
        x0 = dense_mesh(a, b, [tc], w, n_base=80, n_layer=300)
        # V-shape initial guess
        slope_l = (1.0 - bc_left) / (tc - a)
        slope_r = (bc_right - 1.0) / (b - tc)
        y0_z = np.where(
            x0 < tc,
            bc_left + slope_l * (x0 - a),
            1.0 + slope_r * (x0 - tc),
        )
        y0_zp = np.where(x0 < tc, slope_l, slope_r)
        y0 = np.vstack([y0_z, y0_zp])

    elif pid == "bvpT21":
        # eps*z'' = z + z^2 - exp(-2t/sqrt(eps)),  z(0)=1, z(1)=exp(-1/sqrt(eps))
        # Nonlinear, left boundary layer at t=0, width O(sqrt(eps))
        a, b = 0.0, 1.0
        se = np.sqrt(eps)
        bc_right = float(safe_exp(-1.0 / se))

        def fun(x, y):
            et = safe_exp(-2.0 * x / se)
            return np.vstack([y[1], (y[0] + y[0] ** 2 - et) / eps])

        def fun_jac(x, y):
            m = x.size
            J = np.zeros((2, 2, m))
            J[0, 1, :] = 1.0
            J[1, 0, :] = (1.0 + 2.0 * y[0]) / eps
            return J

        def bc(ya, yb):
            return np.array([ya[0] - 1.0, yb[0] - bc_right])

        w = max(se, 0.02)
        x0 = dense_mesh(a, b, [0.0], w)
        # Exponential-decay guess
        se_guess = max(se, 0.05)
        y0_z = np.exp(-x0 / se_guess)
        y0_zp = -y0_z / se_guess
        y0 = np.vstack([y0_z, y0_zp])

    else:
        raise ValueError(f"Unknown problem: {pid}")

    return fun, fun_jac, bc, (a, b), x0, y0


# ---------------------------------------------------------------------------
# Solver with continuation
# ---------------------------------------------------------------------------

def solve_at_eps(pid, eps, prev_sol=None):
    """Solve one BVP instance, optionally warm-starting from a previous sol."""
    fun, fun_jac, bc, (a, b), x0, y0 = build_problem(pid, eps)

    if prev_sol is not None and prev_sol.success:
        # Interpolate previous solution onto the new mesh (no mesh merging)
        y0 = prev_sol.sol(x0)

    sol = solve_bvp(
        fun, bc, x0, y0,
        fun_jac=fun_jac,
        tol=1e-8,
        max_nodes=30000,
        verbose=0,
    )

    if not sol.success:
        # Retry with relaxed tolerance
        sol = solve_bvp(
            fun, bc, x0, y0,
            fun_jac=fun_jac,
            tol=1e-4,
            max_nodes=30000,
            verbose=0,
        )

    return sol


def continuation_solve(pid, target_eps):
    """
    Solve a problem at all target eps values using continuation.

    Walks from the largest to smallest eps, optionally inserting
    intermediate values so that consecutive ratios stay <= 3.
    """
    targets = sorted(set(target_eps), reverse=True)

    # Build schedule with intermediates
    schedule = [targets[0]]
    for eps_next in targets[1:]:
        while schedule[-1] / eps_next > 3.5:
            schedule.append(round(schedule[-1] / 3.0, 10))
        schedule.append(eps_next)

    target_set = set(target_eps)
    results = {}
    prev_sol = None

    for eps in schedule:
        sol = solve_at_eps(pid, eps, prev_sol)
        if sol.success:
            prev_sol = sol
            if eps in target_set:
                _, _, _, (a, b), _, _ = build_problem(pid, eps)
                t_eval = np.linspace(a, b, 1000)
                y_eval = sol.sol(t_eval)[0]
                results[str(eps)] = {
                    "t": t_eval.tolist(),
                    "y": y_eval.tolist(),
                }
                print(f"    eps={eps:<8g}  nodes={sol.x.size:>5d}  OK")
        else:
            print(f"    eps={eps:<8g}  FAILED: {sol.message}", file=sys.stderr)

    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    pids = ["bvpT2", "bvpT10", "bvpT14", "bvpT20", "bvpT21"]
    eps_values = [0.1, 0.01, 0.001]
    out_path = "/app/results.json"

    all_results = {}
    for pid in pids:
        print(f"Solving {pid} ...")
        all_results[pid] = continuation_solve(pid, eps_values)

    with open(out_path, "w") as fh:
        json.dump(all_results, fh, indent=2)

    print(f"\nResults written to {out_path}")


if __name__ == "__main__":
    main()
