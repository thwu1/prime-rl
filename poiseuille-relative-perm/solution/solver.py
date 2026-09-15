#!/usr/bin/env python3
"""Solution for two-phase stratified Poiseuille flow relative permeability analysis.


Derives the analytical velocity profile for two immiscible fluid layers in a
planar channel, implements a cell-centered finite volume solver with harmonic
averaging for the viscosity discontinuity, and computes relative permeability
curves as functions of saturation and viscosity ratio.
"""

import json
import math
import sys

sys.path.insert(0, "/app")
from config import (
    H, G, MU1,
    VISCOSITY_RATIOS, SATURATIONS,
    CONV_MESH_SIZES, CONV_SW, CONV_MU_RATIO,
)


# ============================================================================
# Analytical solution
# ============================================================================

def analytical_constants(Sw, mu_ratio):
    """Compute the integration constants for the two-phase velocity profile.

    The velocity profile in each phase is:
        u1(y) = -(G/(2*mu1)) * y^2 + C1*y,          0 <= y <= h1
        u2(y) = -(G/(2*mu2)) * y^2 + C3*y + C4,     h1 <= y <= H

    Returns (C1, C3, C4).
    """
    mu1 = MU1
    mu2 = MU1 * mu_ratio
    h1 = Sw * H
    h2 = H - h1

    C1 = G * (mu2 * h1**2 + mu1 * h2 * (2 * h1 + h2)) / (
        2 * mu1 * (mu2 * h1 + mu1 * h2)
    )
    C3 = (mu1 / mu2) * C1
    C4 = (G / (2 * mu2)) * H**2 - C3 * H

    return C1, C3, C4


def analytical_velocity_scalar(y, Sw, mu_ratio):
    """Compute analytical velocity at a single position y."""
    mu1 = MU1
    mu2 = MU1 * mu_ratio
    h1 = Sw * H
    C1, C3, C4 = analytical_constants(Sw, mu_ratio)

    if y <= h1:
        return -(G / (2 * mu1)) * y**2 + C1 * y
    else:
        return -(G / (2 * mu2)) * y**2 + C3 * y + C4


def analytical_flow_rates(Sw, mu_ratio):
    """Compute analytical volumetric flow rates Q1, Q2 per unit width."""
    mu1 = MU1
    mu2 = MU1 * mu_ratio
    h1 = Sw * H
    C1, C3, C4 = analytical_constants(Sw, mu_ratio)

    Q1 = -(G / (6 * mu1)) * h1**3 + C1 * h1**2 / 2

    Q2 = (
        -(G / (6 * mu2)) * (H**3 - h1**3)
        + C3 * (H**2 - h1**2) / 2
        + C4 * (H - h1)
    )
    return Q1, Q2


def analytical_kr(Sw, mu_ratio):
    """Compute analytical relative permeabilities (kr1, kr2)."""
    mu1 = MU1
    mu2 = MU1 * mu_ratio
    Q1, Q2 = analytical_flow_rates(Sw, mu_ratio)

    kr1 = 12 * Q1 * mu1 / (H**3 * G)
    kr2 = 12 * Q2 * mu2 / (H**3 * G)
    return kr1, kr2


# ============================================================================
# Finite volume solver (pure Python, no numpy)
# ============================================================================

def fvm_solve(N, Sw, mu_ratio):
    """Cell-centered finite volume solver with harmonic face averaging.

    Solves  d/dy(mu(y) du/dy) = -G  on [0, H]
    with u(0) = u(H) = 0 and mu(y) piecewise constant.

    Returns (y_centers, u_values) as lists.
    """
    mu1 = MU1
    mu2 = MU1 * mu_ratio
    h1 = Sw * H
    dy = H / N

    # Cell centers
    y = [(i + 0.5) * dy for i in range(N)]

    # Cell-center viscosities
    mu = [mu1 if yi <= h1 else mu2 for yi in y]

    # Face viscosities via HARMONIC averaging
    mu_face = [2.0 * mu[i] * mu[i + 1] / (mu[i] + mu[i + 1]) for i in range(N - 1)]

    # Assemble tridiagonal system
    diag = [0.0] * N
    lower = [0.0] * (N - 1)
    upper = [0.0] * (N - 1)
    rhs = [-G * dy] * N

    # Bottom wall (cell 0)
    diag[0] = -(mu_face[0] + 2.0 * mu[0]) / dy
    upper[0] = mu_face[0] / dy

    # Interior cells
    for i in range(1, N - 1):
        lower[i - 1] = mu_face[i - 1] / dy
        diag[i] = -(mu_face[i - 1] + mu_face[i]) / dy
        upper[i] = mu_face[i] / dy

    # Top wall (cell N-1)
    lower[N - 2] = mu_face[N - 2] / dy
    diag[N - 1] = -(mu_face[N - 2] + 2.0 * mu[N - 1]) / dy

    # Solve tridiagonal system using Thomas algorithm
    u = solve_tridiagonal(lower, diag, upper, rhs)
    return y, u


def solve_tridiagonal(a, b, c, d):
    """Thomas algorithm for tridiagonal system (pure Python)."""
    n = len(b)
    c_prime = [0.0] * max(n - 1, 1)
    d_prime = [0.0] * n

    c_prime[0] = c[0] / b[0]
    d_prime[0] = d[0] / b[0]

    for i in range(1, n):
        denom = b[i] - a[i - 1] * c_prime[i - 1] if i > 0 else b[i]
        if i < n - 1:
            c_prime[i] = c[i] / denom
        d_prime[i] = (d[i] - a[i - 1] * d_prime[i - 1]) / denom

    x = [0.0] * n
    x[n - 1] = d_prime[n - 1]
    for i in range(n - 2, -1, -1):
        x[i] = d_prime[i] - c_prime[i] * x[i + 1]
    return x


def compute_numerical_flow_rates(y, u, Sw):
    """Compute flow rates from numerical solution, splitting at the interface."""
    h1 = Sw * H
    dy = y[1] - y[0]
    Q1 = 0.0
    Q2 = 0.0

    for i in range(len(y)):
        y_lo = y[i] - dy / 2
        y_hi = y[i] + dy / 2

        if y_hi <= h1 + 1e-15:
            Q1 += u[i] * dy
        elif y_lo >= h1 - 1e-15:
            Q2 += u[i] * dy
        else:
            frac1 = (h1 - y_lo) / dy
            Q1 += u[i] * frac1 * dy
            Q2 += u[i] * (1.0 - frac1) * dy

    return Q1, Q2


# ============================================================================
# Main computation
# ============================================================================

def main():
    results = {}

    # --- 1. Analytical relative permeability curves ---
    analytical_kr_data = {}
    for mu_ratio in VISCOSITY_RATIOS:
        key = f"mu_ratio_{mu_ratio}"
        kr1_list = []
        kr2_list = []
        for Sw in SATURATIONS:
            kr1, kr2 = analytical_kr(Sw, mu_ratio)
            kr1_list.append(float(kr1))
            kr2_list.append(float(kr2))
        analytical_kr_data[key] = {
            "Sw": list(SATURATIONS),
            "kr1": kr1_list,
            "kr2": kr2_list,
        }
    results["analytical_kr"] = analytical_kr_data

    # --- 2. Mesh convergence study ---
    l2_errors = []
    for N in CONV_MESH_SIZES:
        y_num, u_num = fvm_solve(N, CONV_SW, CONV_MU_RATIO)
        err_sq_sum = 0.0
        for i in range(N):
            u_exact = analytical_velocity_scalar(y_num[i], CONV_SW, CONV_MU_RATIO)
            err_sq_sum += (u_num[i] - u_exact) ** 2
        l2 = math.sqrt(err_sq_sum / N)
        l2_errors.append(l2)

    # Convergence order via least-squares fit of log(error) vs log(h)
    log_h = [math.log(H / N) for N in CONV_MESH_SIZES]
    log_e = [math.log(e) for e in l2_errors]
    n_pts = len(log_h)
    sum_x = sum(log_h)
    sum_y = sum(log_e)
    sum_xx = sum(x * x for x in log_h)
    sum_xy = sum(x * y for x, y in zip(log_h, log_e))
    convergence_order = (n_pts * sum_xy - sum_x * sum_y) / (n_pts * sum_xx - sum_x ** 2)

    results["convergence"] = {
        "mesh_sizes": list(CONV_MESH_SIZES),
        "l2_errors": l2_errors,
        "convergence_order": convergence_order,
    }

    # --- 3. Validation at finest mesh ---
    N_finest = CONV_MESH_SIZES[-1]
    y_fine, u_fine = fvm_solve(N_finest, CONV_SW, CONV_MU_RATIO)

    max_err = 0.0
    for i in range(N_finest):
        u_exact = analytical_velocity_scalar(y_fine[i], CONV_SW, CONV_MU_RATIO)
        err = abs(u_fine[i] - u_exact)
        if err > max_err:
            max_err = err

    Q1_num, Q2_num = compute_numerical_flow_rates(y_fine, u_fine, CONV_SW)
    mu2 = MU1 * CONV_MU_RATIO
    kr1_num = 12 * Q1_num * MU1 / (H**3 * G)
    kr2_num = 12 * Q2_num * mu2 / (H**3 * G)

    kr1_ana, kr2_ana = analytical_kr(CONV_SW, CONV_MU_RATIO)

    results["validation"] = {
        "finest_mesh_max_error": max_err,
        "kr1_numerical": kr1_num,
        "kr2_numerical": kr2_num,
        "kr1_analytical": float(kr1_ana),
        "kr2_analytical": float(kr2_ana),
    }

    # --- Write output ---
    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)
    print("Results written to /app/results.json")


if __name__ == "__main__":
    main()
