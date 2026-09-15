#!/usr/bin/env python3
"""
Reference solver for the multi-PDE verification suite.

Implements:
  1. Fokker-Planck (Ornstein-Uhlenbeck) via Crank-Nicolson
  2. Focusing NLS (1-soliton) via Strang split-step Fourier
  3. 2D Helmholtz (manufactured solution) via 5-point FD + sparse direct solve

Each solver includes a convergence study at 4 resolutions.

"""

import json
import os

import numpy as np
from scipy import sparse
from scipy.sparse.linalg import factorized, spsolve


# ═══════════════════════════════════════════════════════════════════════════
# 1. Fokker-Planck (Ornstein-Uhlenbeck)
# ═══════════════════════════════════════════════════════════════════════════

def solve_fokker_planck(Nx):
    """
    Solve  p_t = p_xx + (x p)_x  on [-6, 6], t in [0, 1]
    using Crank-Nicolson with central differences.

    Expanding the drift term: p_t = p_xx + x p_x + p

    IC: Gaussian(mu=1, sigma^2=0.25)
    BC: p(-6,t) = p(6,t) = 0

    Analytic at t=1: Gaussian(mu=e^{-1}, sigma^2 = 1 + (0.25-1)*e^{-2})
    """
    x_min, x_max, t_max = -6.0, 6.0, 1.0
    mu_0, sigma_sq_0 = 1.0, 0.25

    dx = (x_max - x_min) / (Nx + 1)
    x = np.linspace(x_min + dx, x_max - dx, Nx)  # interior points

    # Scale Nt with 1/dx^2 so temporal error O(dt^2) is negligible vs spatial O(dx^2)
    Nt = max(int(t_max / (0.4 * dx ** 2)), 200)
    dt = t_max / Nt

    # Initial condition: Gaussian PDF
    p = (1.0 / np.sqrt(2 * np.pi * sigma_sq_0)) * np.exp(
        -(x - mu_0) ** 2 / (2 * sigma_sq_0)
    )

    # Build tridiagonal operator L where L[p]_i = p_xx_i + x_i * p_x_i + p_i
    #   L[i, i]   = -2/dx^2 + 1
    #   L[i, i-1] = 1/dx^2 - x_i / (2 dx)
    #   L[i, i+1] = 1/dx^2 + x_i / (2 dx)
    main = np.full(Nx, -2.0 / dx ** 2 + 1.0)
    lower = 1.0 / dx ** 2 - x[1:] / (2 * dx)   # L[i, i-1] for i=1..Nx-1
    upper = 1.0 / dx ** 2 + x[:-1] / (2 * dx)   # L[i, i+1] for i=0..Nx-2

    L = sparse.diags([lower, main, upper], [-1, 0, 1],
                      shape=(Nx, Nx), format="csc")
    I_mat = sparse.eye(Nx, format="csc")

    # Crank-Nicolson: (I - dt/2 L) p^{n+1} = (I + dt/2 L) p^n
    A = I_mat - (dt / 2) * L
    B = I_mat + (dt / 2) * L

    solve_A = factorized(A)

    for _ in range(Nt):
        p = solve_A(B @ p)

    # Analytic solution at t_max
    mu_t = mu_0 * np.exp(-t_max)
    sigma_sq_t = 1.0 + (sigma_sq_0 - 1.0) * np.exp(-2 * t_max)
    p_exact = (1.0 / np.sqrt(2 * np.pi * sigma_sq_t)) * np.exp(
        -(x - mu_t) ** 2 / (2 * sigma_sq_t)
    )

    l2_error = float(np.sqrt(np.mean((p - p_exact) ** 2)))

    return {
        "u": p,
        "x": x,
        "l2_error": l2_error,
        "resolution": Nx,
        "min_solution_value": float(np.min(p)),
    }


# ═══════════════════════════════════════════════════════════════════════════
# 2. Focusing NLS (1-soliton)
# ═══════════════════════════════════════════════════════════════════════════

def solve_nls(Nx):
    """
    Solve  i psi_t + psi_xx + 2|psi|^2 psi = 0  on [-30, 30], t in [0, pi]
    using Strang split-step Fourier method.

    Rewrite as psi_t = i(psi_xx + 2|psi|^2 psi), then split:
      Linear:    psi_t = i psi_xx     => Fourier: psi_hat *= exp(-i k^2 dt)
      Nonlinear: psi_t = 2i|psi|^2 psi => psi *= exp(2i|psi|^2 dt)

    IC: psi(x,0) = sech(x)
    Analytic: psi(x,t) = sech(x) exp(it)
    """
    x_min, x_max = -30.0, 30.0
    t_max = np.pi
    L_domain = x_max - x_min
    dx = L_domain / Nx
    x = x_min + dx * np.arange(Nx)  # periodic grid

    # Scale Nt linearly with Nx for consistent O(dt^2) convergence
    Nt = 4 * Nx
    dt = t_max / Nt

    # Wavenumbers for FFT
    k = 2 * np.pi * np.fft.fftfreq(Nx, d=dx)

    # Initial condition (complex)
    psi = (1.0 / np.cosh(x)).astype(complex)
    mass_0 = float(np.sum(np.abs(psi) ** 2) * dx)

    # Linear propagator in Fourier space (full step)
    linear_prop = np.exp(-1j * k ** 2 * dt)

    # Strang splitting: half-NL, full-L, half-NL
    # Half nonlinear step propagates by dt/2: exp(2i|psi|^2 * dt/2) = exp(i|psi|^2 * dt)
    for _ in range(Nt):
        # Half nonlinear step
        psi *= np.exp(1j * np.abs(psi) ** 2 * dt)
        # Full linear step in Fourier space
        psi = np.fft.ifft(np.fft.fft(psi) * linear_prop)
        # Half nonlinear step
        psi *= np.exp(1j * np.abs(psi) ** 2 * dt)

    mass_f = float(np.sum(np.abs(psi) ** 2) * dx)
    mass_error = abs(mass_f - mass_0) / mass_0

    # Analytic solution at t_max
    psi_exact = (1.0 / np.cosh(x)) * np.exp(1j * t_max)
    l2_error = float(np.sqrt(np.mean(np.abs(psi - psi_exact) ** 2)))

    return {
        "psi": psi,
        "x": x,
        "l2_error": l2_error,
        "resolution": Nx,
        "mass_initial": mass_0,
        "mass_final": mass_f,
        "mass_conservation_error": mass_error,
    }


# ═══════════════════════════════════════════════════════════════════════════
# 3. 2D Helmholtz (manufactured solution)
# ═══════════════════════════════════════════════════════════════════════════

def solve_helmholtz(Nx):
    """
    Solve  -Lap(u) - k^2 u = f  on [0,1]^2, u=0 on boundary.

    k = 10, manufactured solution u = sin(pi x) sin(pi y)
    => f = (2 pi^2 - k^2) sin(pi x) sin(pi y)

    Uses 5-point FD stencil assembled via Kronecker products + sparse direct solve.
    """
    k_val = 10.0
    Ny = Nx
    h = 1.0 / (Nx + 1)

    x = np.linspace(h, 1.0 - h, Nx)
    y = np.linspace(h, 1.0 - h, Ny)
    X, Y = np.meshgrid(x, y, indexing="ij")

    # Source term from manufactured solution
    f = (2 * np.pi ** 2 - k_val ** 2) * np.sin(np.pi * X) * np.sin(np.pi * Y)

    N_total = Nx * Ny

    # Build -Laplacian via Kronecker products: -Lap_h = kron(T, I) + kron(I, T)
    # where T = (1/h^2) tridiag(-1, 2, -1) is the 1D negative Laplacian
    e = np.ones(Nx)
    T = sparse.diags([-e[1:], 2 * e, -e[:-1]], [-1, 0, 1],
                      format="csc") / h ** 2
    Ix = sparse.eye(Nx, format="csc")

    neg_laplacian = sparse.kron(T, Ix, format="csc") + \
                    sparse.kron(Ix, T, format="csc")

    # Full operator: (-Lap - k^2 I)
    A = neg_laplacian - k_val ** 2 * sparse.eye(N_total, format="csc")

    u_flat = spsolve(A, f.ravel())
    u = u_flat.reshape((Nx, Ny))

    # Analytic solution
    u_exact = np.sin(np.pi * X) * np.sin(np.pi * Y)
    l2_error = float(np.sqrt(np.mean((u - u_exact) ** 2)))

    return {
        "u": u,
        "x": x,
        "y": y,
        "l2_error": l2_error,
        "resolution": Nx,
    }


# ═══════════════════════════════════════════════════════════════════════════
# Convergence study
# ═══════════════════════════════════════════════════════════════════════════

def convergence_study(solver_fn, resolutions):
    """Run solver at multiple resolutions and estimate convergence order."""
    study = []
    finest_result = None

    for N in resolutions:
        result = solver_fn(N)
        study.append({"resolution": N, "l2_error": result["l2_error"]})
        finest_result = result

    # Estimate convergence rate from the two finest resolutions
    e1 = study[-2]["l2_error"]
    e2 = study[-1]["l2_error"]
    N1 = study[-2]["resolution"]
    N2 = study[-1]["resolution"]
    if e2 > 0 and e1 > e2:
        rate = float(np.log(e1 / e2) / np.log(N2 / N1))
    else:
        rate = 0.0

    return study, rate, finest_result


# ═══════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════

def main():
    os.makedirs("/app/solutions", exist_ok=True)
    all_results = {}

    # ── Fokker-Planck ──
    print("Solving Fokker-Planck (Ornstein-Uhlenbeck)...")
    fp_study, fp_rate, fp_fine = convergence_study(
        solve_fokker_planck, [50, 100, 200, 400]
    )
    np.savez(
        "/app/solutions/fokker_planck_ou.npz",
        u=fp_fine["u"],
        x=fp_fine["x"],
    )
    all_results["fokker_planck_ou"] = {
        "l2_error": fp_fine["l2_error"],
        "convergence_rate": fp_rate,
        "convergence_study": fp_study,
        "min_solution_value": fp_fine["min_solution_value"],
    }

    # ── NLS soliton ──
    print("Solving NLS (focusing 1-soliton)...")
    nls_study, nls_rate, nls_fine = convergence_study(
        solve_nls, [64, 128, 256, 512]
    )
    np.savez(
        "/app/solutions/nls_soliton.npz",
        psi=nls_fine["psi"],
        x=nls_fine["x"],
        mass_initial=nls_fine["mass_initial"],
        mass_final=nls_fine["mass_final"],
    )
    all_results["nls_soliton"] = {
        "l2_error": nls_fine["l2_error"],
        "convergence_rate": nls_rate,
        "convergence_study": nls_study,
        "mass_conservation_error": nls_fine["mass_conservation_error"],
    }

    # ── Helmholtz 2D ──
    print("Solving 2D Helmholtz (manufactured solution, k=10)...")
    helm_study, helm_rate, helm_fine = convergence_study(
        solve_helmholtz, [25, 50, 100, 200]
    )
    np.savez(
        "/app/solutions/helmholtz_2d.npz",
        u=helm_fine["u"],
        x=helm_fine["x"],
        y=helm_fine["y"],
    )
    all_results["helmholtz_2d"] = {
        "l2_error": helm_fine["l2_error"],
        "convergence_rate": helm_rate,
        "convergence_study": helm_study,
    }

    # ── Save results ──
    with open("/app/results.json", "w") as f:
        json.dump(all_results, f, indent=2)

    print("\nResults saved to /app/results.json")
    for pid, r in all_results.items():
        extras = ""
        if "mass_conservation_error" in r:
            extras = f", mass_err={r['mass_conservation_error']:.2e}"
        if "min_solution_value" in r:
            extras += f", min_val={r['min_solution_value']:.2e}"
        print(f"  {pid}: L2={r['l2_error']:.6e}, rate={r['convergence_rate']:.2f}{extras}")


if __name__ == "__main__":
    main()
