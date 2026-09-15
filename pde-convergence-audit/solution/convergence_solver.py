#!/usr/bin/env python3
"""
Convergence-order verification for four PDE/scheme combinations.

Solves each problem at N = 16, 32, 64, 128, computes L2 errors against
known exact / manufactured solutions, and writes /app/results.json.
"""

import json
import math

import numpy as np
from scipy import sparse
from scipy.sparse.linalg import spsolve


# ── Poisson 5-point ──────────────────────────────────────────────────


def solve_poisson_5pt(N):
    """
    2D Poisson  -nabla^2 u = f  on (0,1)^2 with u=0 on boundary.
    5-point finite-difference Laplacian.
    Manufactured solution: u* = sin(pi*x)*sin(pi*y).
    Returns the L2 (RMS) error.
    """
    h = 1.0 / (N + 1)
    x = np.linspace(h, 1.0 - h, N)
    y = np.linspace(h, 1.0 - h, N)
    X, Y = np.meshgrid(x, y, indexing="ij")

    u_exact = np.sin(np.pi * X) * np.sin(np.pi * Y)
    f = 2.0 * np.pi ** 2 * np.sin(np.pi * X) * np.sin(np.pi * Y)

    # A = (T kron I + I kron T) / h^2  with T = tridiag(-1, 2, -1)
    ones = np.ones(N)
    T = sparse.diags([-ones[:-1], 2.0 * ones, -ones[:-1]], [-1, 0, 1], format="csr")
    I_N = sparse.eye(N, format="csr")
    A = (sparse.kron(T, I_N, format="csr") + sparse.kron(I_N, T, format="csr")) / h ** 2

    u_num = spsolve(A, f.ravel()).reshape((N, N))
    return float(np.sqrt(np.mean((u_num - u_exact) ** 2)))


# ── Poisson compact 9-point (Mehrstellen) ────────────────────────────


def solve_poisson_compact(N):
    """
    Same PDE as above, but solved with the compact 4th-order
    Collatz / Mehrstellen 9-point stencil.

    Stencil equation (for interior point (i,j)):
        [20 u_{ij} - 4 sum(axial) - sum(diagonal)] / (6h^2)
            = [8 f_{ij} + sum(axial f)] / 12

    Multiply through by 6h^2:
        20 u - 4*axial_u - diag_u = (h^2/2)*(8 f + axial_f)
    """
    h = 1.0 / (N + 1)
    x = np.linspace(h, 1.0 - h, N)
    y = np.linspace(h, 1.0 - h, N)
    X, Y = np.meshgrid(x, y, indexing="ij")

    u_exact = np.sin(np.pi * X) * np.sin(np.pi * Y)
    f = 2.0 * np.pi ** 2 * np.sin(np.pi * X) * np.sin(np.pi * Y)

    I_N = sparse.eye(N, format="csr")
    S_p = sparse.diags([np.ones(N - 1)], [1], shape=(N, N), format="csr")
    S_m = sparse.diags([np.ones(N - 1)], [-1], shape=(N, N), format="csr")
    S = S_p + S_m  # shift-left + shift-right

    # Build the 9-point stencil matrix  (center=20, axial=-4, diagonal=-1)
    A = (
        20.0 * sparse.kron(I_N, I_N, format="csr")
        - 4.0
        * (
            sparse.kron(S, I_N, format="csr") + sparse.kron(I_N, S, format="csr")
        )
        - sparse.kron(S_p, S_p, format="csr")
        - sparse.kron(S_m, S_m, format="csr")
        - sparse.kron(S_p, S_m, format="csr")
        - sparse.kron(S_m, S_p, format="csr")
    )

    # Modified RHS:  b = (h^2 / 2) * (8*f_center + f_axial_sum)
    # Pad f with zeros on the boundary (sin(0)=sin(pi)=0).
    f_pad = np.zeros((N + 2, N + 2))
    f_pad[1:-1, 1:-1] = f
    b_2d = (h ** 2 / 2.0) * (
        8.0 * f_pad[1:-1, 1:-1]
        + f_pad[:-2, 1:-1]
        + f_pad[2:, 1:-1]
        + f_pad[1:-1, :-2]
        + f_pad[1:-1, 2:]
    )

    u_num = spsolve(A.tocsr(), b_2d.ravel()).reshape((N, N))
    return float(np.sqrt(np.mean((u_num - u_exact) ** 2)))


# ── Heat equation – Crank-Nicolson ───────────────────────────────────


def solve_heat_cn(N):
    """
    1D heat equation  u_t = u_xx  on (0,1), T_final = 0.1.
    Dirichlet BCs u(0)=u(1)=0.  IC: u(x,0) = sin(pi*x).
    Exact solution: exp(-pi^2 * t) * sin(pi*x).
    Crank-Nicolson in time, central finite difference in space.
    N_t = N  time steps.
    """
    T_final = 0.1
    N_t = N
    h = 1.0 / (N + 1)
    dt = T_final / N_t
    r = dt / h ** 2  # mesh ratio

    x = np.linspace(h, 1.0 - h, N)
    u = np.sin(np.pi * x)

    # LHS matrix: tridiag(-r/2, 1+r, -r/2)
    diag_L = (1.0 + r) * np.ones(N)
    off_L = (-r / 2.0) * np.ones(N - 1)
    L = np.diag(diag_L) + np.diag(off_L, -1) + np.diag(off_L, 1)

    # RHS matrix: tridiag(r/2, 1-r, r/2)
    diag_R = (1.0 - r) * np.ones(N)
    off_R = (r / 2.0) * np.ones(N - 1)
    R = np.diag(diag_R) + np.diag(off_R, -1) + np.diag(off_R, 1)

    for _ in range(N_t):
        u = np.linalg.solve(L, R @ u)

    u_exact = np.exp(-np.pi ** 2 * T_final) * np.sin(np.pi * x)
    return float(np.sqrt(np.mean((u - u_exact) ** 2)))


# ── Advection – Lax-Wendroff ────────────────────────────────────────


def solve_advection_lw(N):
    """
    1D advection  u_t + u_x = 0  on [0,1), periodic BCs.
    T_final = 1.0,  c = 1.   IC: sin(2*pi*x).
    Exact solution: sin(2*pi*(x - t)).
    Lax-Wendroff scheme with CFL = 0.8.
    """
    T_final = 1.0
    c = 1.0
    h = 1.0 / N
    CFL_target = 0.8
    dt = CFL_target * h / c
    N_t = int(round(T_final / dt))
    dt = T_final / N_t  # adjust to hit T_final exactly
    nu = c * dt / h  # actual CFL number

    x = np.linspace(0.0, 1.0 - h, N)
    u = np.sin(2.0 * np.pi * x)

    for _ in range(N_t):
        u_p = np.roll(u, -1)  # u_{i+1}
        u_m = np.roll(u, 1)  # u_{i-1}
        u = (
            u
            - 0.5 * nu * (u_p - u_m)
            + 0.5 * nu ** 2 * (u_p - 2.0 * u + u_m)
        )

    u_exact = np.sin(2.0 * np.pi * (x - T_final))
    return float(np.sqrt(np.mean((u - u_exact) ** 2)))


# ── Driver ───────────────────────────────────────────────────────────


def main():
    resolutions = [16, 32, 64, 128]
    problems = [
        ("poisson_5pt", solve_poisson_5pt),
        ("poisson_compact", solve_poisson_compact),
        ("heat_cn", solve_heat_cn),
        ("advection_lw", solve_advection_lw),
    ]

    results = {}
    for name, solver in problems:
        errors = [solver(n) for n in resolutions]
        orders = []
        for i in range(len(errors) - 1):
            if errors[i + 1] > 0:
                orders.append(
                    float(math.log(errors[i] / errors[i + 1]) / math.log(2))
                )
        results[name] = {
            "resolutions": resolutions,
            "l2_errors": errors,
            "convergence_orders": orders,
            "estimated_order": float(np.mean(orders)) if orders else 0.0,
        }

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    for name, data in results.items():
        errs = ", ".join(f"{e:.3e}" for e in data["l2_errors"])
        ords = ", ".join(f"{o:.2f}" for o in data["convergence_orders"])
        print(f"{name:20s}  errors=[{errs}]  orders=[{ords}]  est={data['estimated_order']:.2f}")


if __name__ == "__main__":
    main()
