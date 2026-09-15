#!/usr/bin/env python3
"""
Solve the Taylor-Goldstein equation for the linear stability of a stratified
shear flow with U(z) = tanh(z), B(z) = Ri*tanh(z).

Approach — Newton iteration on the TG operator directly:

  The Taylor-Goldstein equation
      T(c) psi = (U-c) L psi - U'' psi + N^2/(U-c) psi = 0
  where L = D^2 - k^2.

  For Ri=0 (unstratified), this reduces to the Rayleigh equation:
      (U-c) L psi - U'' psi = 0
  which is a standard generalized eigenvalue problem.

  For Ri > 0, we track the physical eigenvalue from the Rayleigh
  solution using Newton iteration on T(c) directly, avoiding the
  quadratic eigenvalue problem (QEP) formulation entirely. The QEP
  companion linearization introduces spurious eigenvalues that
  contaminate results near the Miles-Howard stability boundary.

  Working with T(c) directly means the operator has ONLY physical
  eigenvalues (no spurious ones from multiplication by (U-c)), and
  inverse iteration naturally converges to the correct eigenvector.

  Boundary conditions: psi = 0 at z = +/- L_domain.
"""

import json
import os
import numpy as np
from scipy import linalg


def cheb(N):
    """Return (D, x): the (N+1)x(N+1) Chebyshev diff matrix and nodes on [-1,1]."""
    if N == 0:
        return np.array([[0.0]]), np.array([1.0])

    x = np.cos(np.pi * np.arange(N + 1) / N)
    c = np.ones(N + 1)
    c[0] = 2.0
    c[-1] = 2.0
    c *= (-1.0) ** np.arange(N + 1)

    X = np.tile(x, (N + 1, 1))
    dX = X - X.T
    D = np.outer(c, 1.0 / c) / (dX + np.eye(N + 1))
    D -= np.diag(D.sum(axis=1))
    return D, x


def newton_tg(L, U, Upp, N2, c_init, psi_init, max_iter=50, tol=1e-10):
    """
    Newton iteration for the Taylor-Goldstein eigenvalue problem:
        T(c) psi = diag(U-c) L psi - U'' psi + N^2/(U-c) psi = 0

    Uses inverse iteration on T(c) for the eigenvector and a
    Rayleigh-quotient Newton correction for c.

    Returns (c, psi) or (None, None) if mode is stable / lost.
    """
    c = complex(c_init)
    psi = psi_init.astype(complex).copy()
    psi /= np.linalg.norm(psi)

    for _ in range(max_iter):
        if c.imag < 1e-8:
            return None, None

        Umc = U - c
        if np.min(np.abs(Umc)) < 1e-10:
            return None, None

        Umc_inv = 1.0 / Umc

        # T(c) = diag(U-c) @ L - diag(U'') + diag(N2/(U-c))
        T = np.diag(Umc) @ L - np.diag(Upp) + np.diag(N2 * Umc_inv)

        # T'(c) = dT/dc = -L + diag(N2/(U-c)^2)
        Tp = -L + np.diag(N2 * Umc_inv ** 2)

        # Inverse iteration: find eigenvector of T nearest zero eigenvalue
        try:
            psi_new = np.linalg.solve(T, psi)
        except np.linalg.LinAlgError:
            break

        nrm = np.linalg.norm(psi_new)
        if nrm < 1e-14:
            break
        psi_new /= nrm

        # Newton correction: dc = -psi^H T psi / (psi^H T' psi)
        Tpn = T @ psi_new
        Tppn = Tp @ psi_new

        den = np.vdot(psi_new, Tppn)
        if abs(den) < 1e-14:
            break

        dc = -np.vdot(psi_new, Tpn) / den

        if abs(dc) > 2.0:
            break

        c += dc
        psi = psi_new

        if abs(dc) < tol:
            break

    if c.imag < 1e-6 or abs(c.real) > 1.0:
        return None, None
    return c, psi


def main():
    with open("/app/config.json") as f:
        cfg = json.load(f)

    z_min = cfg["domain"]["z_min"]
    z_max = cfg["domain"]["z_max"]
    N_cheb = cfg["discretization"]["N_chebyshev"]
    Ri_list = cfg["parameters"]["richardson_numbers"]
    k_lo, k_hi = cfg["parameters"]["wavenumber_range"]
    n_k = cfg["parameters"]["n_wavenumbers"]

    ks = np.linspace(k_lo, k_hi, n_k)

    # ── Precompute Chebyshev operators and base-state profiles ──
    D_ref, xi = cheb(N_cheb)
    half_L = (z_max - z_min) / 2.0
    z_all = (z_max + z_min) / 2.0 + half_L * xi

    D1 = D_ref / half_L
    D2_full = D1 @ D1

    # Interior points only (psi = 0 at boundaries)
    sl = slice(1, N_cheb)
    z = z_all[sl]
    n = N_cheb - 1

    D2 = D2_full[sl, sl]
    In = np.eye(n)

    U = np.tanh(z)
    sech2 = 1.0 / np.cosh(z) ** 2
    Upp = -2.0 * U * sech2

    Ud = np.diag(U)
    Uppd = np.diag(Upp)

    os.makedirs("/app/results", exist_ok=True)

    # ── Compute growth rates across (k, Ri) space ────────────
    sigma = np.zeros((n_k, len(Ri_list)))

    for i, k_val in enumerate(ks):
        if k_val < 1e-14:
            continue

        L = D2 - k_val ** 2 * In

        # ── Rayleigh equation (Ri=0): (UL - U'')psi = c L psi ──
        A_ray = Ud @ L - Uppd
        B_ray = L.copy()
        eigs_ray, vecs_ray = linalg.eig(A_ray, B_ray, right=True)

        # Select the most unstable physical eigenvalue
        mask = (
            np.isfinite(eigs_ray)
            & (eigs_ray.imag > 1e-6)
            & (np.abs(eigs_ray) < 1.0)
        )
        if not np.any(mask):
            continue  # stable at Ri=0 => stable for all Ri >= 0

        idx_u = np.where(mask)[0]
        best = idx_u[np.argmax(eigs_ray[idx_u].imag)]
        c_ray = eigs_ray[best]
        psi_ray = vecs_ray[:, best]

        # ── Sweep Ri, tracking the physical mode via Newton on T(c) ──
        c_prev = c_ray
        psi_prev = psi_ray.copy()

        for j, Ri in enumerate(Ri_list):
            if Ri < 1e-14:
                # Ri=0: use Rayleigh result directly
                sigma[i, j] = max(k_val * c_ray.imag, 0.0)
                continue

            N2 = Ri * sech2  # N^2(z) = Ri * sech^2(z)

            c_new, psi_new = newton_tg(
                L, U, Upp, N2, c_prev, psi_prev
            )

            if c_new is not None:
                sigma[i, j] = max(k_val * c_new.imag, 0.0)
                c_prev = c_new
                psi_prev = psi_new
            else:
                sigma[i, j] = 0.0
                # Don't update c_prev — mode is lost / stable

    # ── Write growth_rates.csv ────────────────────────────────
    hdr = "k," + ",".join(f"Ri_{Ri:.2f}" for Ri in Ri_list)
    with open(cfg["output"]["growth_rates_file"], "w") as f:
        f.write(hdr + "\n")
        for i in range(n_k):
            vals = ",".join(f"{sigma[i, j]:.8f}" for j in range(len(Ri_list)))
            f.write(f"{ks[i]:.6f},{vals}\n")

    # ── Write max_growth.csv ──────────────────────────────────
    with open(cfg["output"]["max_growth_file"], "w") as f:
        f.write("Ri,sigma_max,k_max\n")
        for j, Ri in enumerate(Ri_list):
            idx = int(np.argmax(sigma[:, j]))
            f.write(f"{Ri:.2f},{sigma[idx, j]:.8f},{ks[idx]:.6f}\n")

    # ── Write critical_ri.txt ─────────────────────────────────
    crit = Ri_list[-1]
    for j, Ri in enumerate(Ri_list):
        if np.max(sigma[:, j]) < 1e-3:
            crit = Ri
            break

    with open(cfg["output"]["critical_ri_file"], "w") as f:
        f.write(f"{crit:.3f}\n")


if __name__ == "__main__":
    main()
