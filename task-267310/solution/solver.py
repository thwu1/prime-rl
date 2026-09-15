#!/usr/bin/env python3

"""
Reference solver for singularly perturbed BVP test suite.
Uses scipy.solve_bvp with parameter continuation in epsilon and analytical Jacobians.
"""

import json
import numpy as np
from scipy.integrate import solve_bvp


def log_cosh_stable(x):
    """Numerically stable computation of log(cosh(x))."""
    x = np.asarray(x, dtype=float)
    ax = np.abs(x)
    return ax + np.log1p(np.exp(-2.0 * ax)) - np.log(2.0)


def solve_with_continuation(ode_fun, bc_fun, jac_fun, domain, eps_values,
                            initial_guess_fun):
    """Solve a BVP for a sequence of decreasing epsilon using continuation."""
    a, b = domain
    results = {}

    x = np.linspace(a, b, 51)
    y = initial_guess_fun(x, eps_values[0])

    for eps in eps_values:
        def fun(t, y, _e=eps):
            return ode_fun(t, y, _e)

        def bc(ya, yb, _e=eps):
            return bc_fun(ya, yb, _e)

        def jac(t, y, _e=eps):
            return jac_fun(t, y, _e)

        sol = solve_bvp(fun, bc, x, y, fun_jac=jac, tol=1e-6, max_nodes=10000)

        if not sol.success:
            # Retry with denser initial mesh
            x_dense = np.linspace(a, b, 501)
            y_dense = np.zeros((2, len(x_dense)))
            y_dense[0] = np.interp(x_dense, x, y[0])
            y_dense[1] = np.interp(x_dense, x, y[1])
            sol = solve_bvp(fun, bc, x_dense, y_dense, fun_jac=jac,
                            tol=1e-4, max_nodes=50000)

        t_eval = np.linspace(a, b, 201)
        y_eval = sol.sol(t_eval)

        results[str(eps)] = {
            "t": t_eval.tolist(),
            "y": y_eval[0].tolist()
        }

        # Continuation: use converged solution as initial guess for next eps
        x = sol.x.copy()
        y = sol.y.copy()

    return results


# ---------------------------------------------------------------------------
# Problem 1: exponential_layer (bvpT2)
# eps*z'' = z',  z(0)=1, z(1)=0,  t in [0,1]
# ---------------------------------------------------------------------------

def solve_exponential_layer():
    def ode(t, y, eps):
        return np.vstack([y[1], y[1] / eps])

    def bc(ya, yb, eps):
        return np.array([ya[0] - 1.0, yb[0]])

    def jac(t, y, eps):
        m = len(t)
        J = np.zeros((2, 2, m))
        J[0, 1, :] = 1.0
        J[1, 1, :] = 1.0 / eps
        return J

    def guess(x, eps):
        return np.vstack([1.0 - x, -np.ones_like(x)])

    return solve_with_continuation(ode, bc, jac, (0.0, 1.0),
                                   [0.1, 0.01, 0.001, 0.0001], guess)


# ---------------------------------------------------------------------------
# Problem 2: turning_point_shock (bvpT6)
# eps*z'' = -t*z' - eps*pi^2*cos(pi*t) - pi*t*sin(pi*t)
# z(-1)=-2, z(1)=0,  t in [-1,1]
# ---------------------------------------------------------------------------

def solve_turning_point_shock():
    def ode(t, y, eps):
        return np.vstack([
            y[1],
            (-t * y[1] - eps * np.pi**2 * np.cos(np.pi * t)
             - np.pi * t * np.sin(np.pi * t)) / eps
        ])

    def bc(ya, yb, eps):
        return np.array([ya[0] + 2.0, yb[0]])

    def jac(t, y, eps):
        m = len(t)
        J = np.zeros((2, 2, m))
        J[0, 1, :] = 1.0
        J[1, 1, :] = -t / eps
        return J

    def guess(x, eps):
        return np.vstack([
            np.cos(np.pi * x),
            -np.pi * np.sin(np.pi * x)
        ])

    return solve_with_continuation(ode, bc, jac, (-1.0, 1.0),
                                   [0.1, 0.01, 0.001, 0.0001], guess)


# ---------------------------------------------------------------------------
# Problem 3: dual_boundary_layers (bvpT14)
# eps*z'' = z - (1 + eps*pi^2)*cos(pi*t)
# z(-1)=exp(-2/sqrt(eps)), z(1)=exp(-2/sqrt(eps)),  t in [-1,1]
# ---------------------------------------------------------------------------

def solve_dual_boundary_layers():
    def ode(t, y, eps):
        return np.vstack([
            y[1],
            (y[0] - (1.0 + eps * np.pi**2) * np.cos(np.pi * t)) / eps
        ])

    def bc(ya, yb, eps):
        bc_val = np.exp(-2.0 / np.sqrt(eps))
        return np.array([ya[0] - bc_val, yb[0] - bc_val])

    def jac(t, y, eps):
        m = len(t)
        J = np.zeros((2, 2, m))
        J[0, 1, :] = 1.0
        J[1, 0, :] = 1.0 / eps
        return J

    def guess(x, eps):
        return np.vstack([
            np.cos(np.pi * x),
            -np.pi * np.sin(np.pi * x)
        ])

    return solve_with_continuation(ode, bc, jac, (-1.0, 1.0),
                                   [0.1, 0.01, 0.001, 0.0001], guess)


# ---------------------------------------------------------------------------
# Problem 4: nonlinear_corner (bvpT20)
# eps*z'' = -(z')^2 + 1
# z(0) = 1 + eps*ln(cosh(0.745/eps))
# z(1) = 1 + eps*ln(cosh(0.255/eps))
# t in [0,1]
# ---------------------------------------------------------------------------

def solve_nonlinear_corner():
    def ode(t, y, eps):
        return np.vstack([y[1], (-y[1]**2 + 1.0) / eps])

    def bc(ya, yb, eps):
        bc_left = 1.0 + eps * float(log_cosh_stable(0.745 / eps))
        bc_right = 1.0 + eps * float(log_cosh_stable(0.255 / eps))
        return np.array([ya[0] - bc_left, yb[0] - bc_right])

    def jac(t, y, eps):
        m = len(t)
        J = np.zeros((2, 2, m))
        J[0, 1, :] = 1.0
        J[1, 1, :] = -2.0 * y[1] / eps
        return J

    def guess(x, eps):
        # Use outer solution shape: 1 + |t - 0.745|
        return np.vstack([
            1.0 + np.abs(x - 0.745),
            np.where(x < 0.745, -1.0, 1.0)
        ])

    return solve_with_continuation(ode, bc, jac, (0.0, 1.0),
                                   [0.1, 0.01, 0.001, 0.0001], guess)


# ---------------------------------------------------------------------------
# Problem 5: double_corner_layers (bvpT25)
# eps*z'' = -z*z' + z
# z(0) = -1/3, z(1) = 1/3,  t in [0,1]
# No exact solution. Corner layers at t=1/3 and t=2/3.
# ---------------------------------------------------------------------------

def solve_double_corner_layers():
    def ode(t, y, eps):
        return np.vstack([y[1], (-y[0] * y[1] + y[0]) / eps])

    def bc(ya, yb, eps):
        return np.array([ya[0] + 1.0 / 3.0, yb[0] - 1.0 / 3.0])

    def jac(t, y, eps):
        m = len(t)
        J = np.zeros((2, 2, m))
        J[0, 1, :] = 1.0
        J[1, 0, :] = (-y[1] + 1.0) / eps
        J[1, 1, :] = -y[0] / eps
        return J

    def guess(x, eps):
        # Linear interpolation between boundary values
        return np.vstack([
            -1.0 / 3.0 + 2.0 / 3.0 * x,
            np.full_like(x, 2.0 / 3.0)
        ])

    return solve_with_continuation(ode, bc, jac, (0.0, 1.0),
                                   [0.1, 0.01, 0.001, 0.0001], guess)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    results = {}
    results["exponential_layer"] = solve_exponential_layer()
    results["turning_point_shock"] = solve_turning_point_shock()
    results["dual_boundary_layers"] = solve_dual_boundary_layers()
    results["nonlinear_corner"] = solve_nonlinear_corner()
    results["double_corner_layers"] = solve_double_corner_layers()

    with open("/app/results.json", "w") as f:
        json.dump(results, f)

    print("All problems solved. Results written to /app/results.json")


if __name__ == "__main__":
    main()
