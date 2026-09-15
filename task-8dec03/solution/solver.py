#!/usr/bin/env python3

"""
Translate three stiff ODE problems from the Geneva Test Set (Hairer & Wanner)
from Fortran 77 to Python and solve them using scipy's implicit Radau solver.

Problems:
  - ROBER: Robertson's chemical kinetics (3 equations)
  - HIRES: High Irradiance RESponse (8 equations)
  - E5: Extremely stiff chemical kinetics (4 equations, rate constants span 19 orders of magnitude)
"""

import json
import numpy as np
from scipy.integrate import solve_ivp


# ============================================================
# ROBER: Robertson's chemical reaction
# Translated from fortran/rober/equation.f
#
# dy1/dt = -0.04*y1 + 1e4*y2*y3
# dy3/dt = 3e7*y2^2
# dy2/dt = -dy1 - dy3
#
# Initial conditions (from driver_radau5.f): y = [1, 0, 0]
# Conservation: y1 + y2 + y3 = 1
# ============================================================

def rober_rhs(t, y):
    y1, y2, y3 = y
    dy1 = -0.04 * y1 + 1.0e4 * y2 * y3
    dy3 = 3.0e7 * y2 * y2
    dy2 = -dy1 - dy3
    return [dy1, dy2, dy3]


def rober_jac(t, y):
    y1, y2, y3 = y
    prod1 = 1.0e4 * y2
    prod2 = 1.0e4 * y3
    prod3 = 6.0e7 * y2
    return [
        [-0.04, prod2, prod1],
        [0.04, -prod2 - prod3, -prod1],
        [0.0, prod3, 0.0],
    ]


def solve_rober():
    t_eval = [0.4, 4.0, 40.0, 400.0, 4000.0, 40000.0, 400000.0]
    y0 = [1.0, 0.0, 0.0]

    sol = solve_ivp(
        rober_rhs,
        [0, max(t_eval)],
        y0,
        method="Radau",
        jac=rober_jac,
        rtol=1e-12,
        atol=1e-14,
        t_eval=t_eval,
        dense_output=True,
    )
    assert sol.status == 0, f"ROBER solver failed: {sol.message}"

    solutions = {}
    conservation_errors = []
    for i, t in enumerate(t_eval):
        y = sol.y[:, i].tolist()
        solutions[str(t)] = y
        conservation_errors.append(abs(sum(y) - 1.0))

    return {
        "solutions": solutions,
        "conservation_max_error": max(conservation_errors),
    }


# ============================================================
# HIRES: High Irradiance RESponse (chemical reaction, 8 equations)
# Translated from fortran/hires/equation.f
#
# Nonlinear Jacobian: entries J(6,6), J(6,8), J(7,6), J(7,8),
#   J(8,6), J(8,8) depend on y(6) and y(8)
#
# Initial conditions (from driver_radau5.f):
#   y = [1, 0, 0, 0, 0, 0, 0, 0.0057]
#
# Algebraic invariant: y7 + y8 = 0.0057 (since dy7 + dy8 = 0)
# ============================================================

def hires_rhs(t, y):
    dy = np.zeros(8)
    dy[0] = -1.71 * y[0] + 0.43 * y[1] + 8.32 * y[2] + 0.0007
    dy[1] = 1.71 * y[0] - 8.75 * y[1]
    dy[2] = -10.03 * y[2] + 0.43 * y[3] + 0.035 * y[4]
    dy[3] = 8.32 * y[1] + 1.71 * y[2] - 1.12 * y[3]
    dy[4] = -1.745 * y[4] + 0.43 * y[5] + 0.43 * y[6]
    dy[5] = (
        -280.0 * y[5] * y[7]
        + 0.69 * y[3]
        + 1.71 * y[4]
        - 0.43 * y[5]
        + 0.69 * y[6]
    )
    dy[6] = 280.0 * y[5] * y[7] - 1.81 * y[6]
    dy[7] = -dy[6]
    return dy


def hires_jac(t, y):
    J = np.zeros((8, 8))
    J[0, 0] = -1.71
    J[0, 1] = 0.43
    J[0, 2] = 8.32
    J[1, 0] = 1.71
    J[1, 1] = -8.75
    J[2, 2] = -10.03
    J[2, 3] = 0.43
    J[2, 4] = 0.035
    J[3, 1] = 8.32
    J[3, 2] = 1.71
    J[3, 3] = -1.12
    J[4, 4] = -1.745
    J[4, 5] = 0.43
    J[4, 6] = 0.43
    J[5, 3] = 0.69
    J[5, 4] = 1.71
    J[5, 5] = -0.43 - 280.0 * y[7]
    J[5, 6] = 0.69
    J[5, 7] = -280.0 * y[5]
    J[6, 5] = 280.0 * y[7]
    J[6, 6] = -1.81
    J[6, 7] = 280.0 * y[5]
    J[7, 5] = -280.0 * y[7]
    J[7, 6] = 1.81
    J[7, 7] = -280.0 * y[5]
    return J


def solve_hires():
    t_eval = [200.0, 321.8122, 421.8122]
    y0 = [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0057]

    sol = solve_ivp(
        hires_rhs,
        [0, max(t_eval)],
        y0,
        method="Radau",
        jac=hires_jac,
        rtol=1e-12,
        atol=1e-14,
        t_eval=t_eval,
        dense_output=True,
    )
    assert sol.status == 0, f"HIRES solver failed: {sol.message}"

    solutions = {}
    invariant_errors = []
    for i, t in enumerate(t_eval):
        y = sol.y[:, i].tolist()
        solutions[str(t)] = y
        invariant_errors.append(abs(y[6] + y[7] - 0.0057))

    return {
        "solutions": solutions,
        "invariant_max_error": max(invariant_errors),
    }


# ============================================================
# E5: Extremely stiff chemical kinetics (4 equations)
# Translated from fortran/e5/equation.f
#
# Rate constants:
#   k1 = 7.89e-10, k2 = 1.1e7, k3 = 1.13e9, k4 = 1.13e3
#   (span 19 orders of magnitude!)
#
# dy1/dt = -k1*y1 - k2*y1*y3
# dy2/dt = k1*y1 - k3*y2*y3
# dy4/dt = k2*y1*y3 - k4*y4
# dy3/dt = dy2 - dy4
#
# Initial conditions (from driver_radau5.f):
#   y = [1.76e-3, 0, 0, 0]
#
# Requires very small absolute tolerance (~1e-20) because
# solution components become extremely small
# ============================================================

def e5_rhs(t, y):
    y1, y2, y3, y4 = y
    prod1 = 7.89e-10 * y1
    prod2 = 1.1e7 * y1 * y3
    prod3 = 1.13e9 * y2 * y3
    prod4 = 1.13e3 * y4
    f1 = -prod1 - prod2
    f2 = prod1 - prod3
    f4 = prod2 - prod4
    f3 = f2 - f4
    return [f1, f2, f3, f4]


def e5_jac(t, y):
    y1, y2, y3, y4 = y
    a = 7.89e-10
    b = 1.1e7
    cm = 1.13e9
    c = 1.13e3
    return [
        [-a - b * y3, 0.0, -b * y1, 0.0],
        [a, -cm * y3, -cm * y2, 0.0],
        [a - b * y3, -cm * y3, -b * y1 - cm * y2, c],
        [b * y3, 0.0, b * y1, -c],
    ]


def solve_e5():
    t_eval = [1.0, 10.0, 100.0, 1000.0, 10000.0]
    y0 = [1.76e-3, 0.0, 0.0, 0.0]

    sol = solve_ivp(
        e5_rhs,
        [0, max(t_eval)],
        y0,
        method="Radau",
        jac=e5_jac,
        rtol=1e-12,
        atol=1e-20,
        first_step=1e-10,
        t_eval=t_eval,
        dense_output=True,
    )
    assert sol.status == 0, f"E5 solver failed: {sol.message}"

    solutions = {}
    for i, t in enumerate(t_eval):
        y = sol.y[:, i].tolist()
        solutions[str(t)] = y

    return {"solutions": solutions}


def main():
    results = {
        "rober": solve_rober(),
        "hires": solve_hires(),
        "e5": solve_e5(),
    }

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print("Results written to /app/results.json")

    # Print summary
    for problem in ["rober", "hires", "e5"]:
        sols = results[problem]["solutions"]
        n_times = len(sols)
        first_key = list(sols.keys())[0]
        n_components = len(sols[first_key])
        print(f"  {problem}: {n_times} time points, {n_components} components each")

    if "conservation_max_error" in results["rober"]:
        print(f"  ROBER conservation max error: {results['rober']['conservation_max_error']:.2e}")
    if "invariant_max_error" in results["hires"]:
        print(f"  HIRES invariant max error: {results['hires']['invariant_max_error']:.2e}")


if __name__ == "__main__":
    main()
