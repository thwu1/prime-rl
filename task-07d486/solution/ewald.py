#!/usr/bin/env python3

"""
Standalone Ewald summation for periodic electrostatics.
Computes energy (real + reciprocal + self) and analytical forces
for charged particles in a cubic periodic box using Gaussian units.
Includes convergence evaluation of the reciprocal-space cutoff.
"""

import json
import numpy as np
from scipy.special import erfc as scipy_erfc


def ewald_energy_and_forces(positions, charges, box_length, alpha=None, k_max=None):
    """
    Full Ewald summation returning decomposed energy and forces.

    Parameters
    ----------
    positions : array_like, shape (N, 3)
    charges : array_like, shape (N,)
    box_length : float
    alpha : float, optional (default 5/L)
    k_max : int, optional (default 7)

    Returns
    -------
    E_real, E_recip, E_self, E_total : float
    forces : np.ndarray of shape (N, 3)
    """
    pos = np.array(positions, dtype=np.float64)
    q = np.array(charges, dtype=np.float64)
    N = len(q)
    L = float(box_length)
    V = L ** 3

    if alpha is None:
        alpha = 5.0 / L
    if k_max is None:
        k_max = 7

    inv_sqrt_pi = 1.0 / np.sqrt(np.pi)

    # ========== Real-space sum ==========
    E_real = 0.0
    F_real = np.zeros((N, 3))

    for i in range(N):
        if i + 1 >= N:
            break
        dr = pos[i + 1:] - pos[i]
        dr -= L * np.round(dr / L)           # minimum image
        r2 = np.sum(dr * dr, axis=1)
        r = np.sqrt(r2)

        ar = alpha * r
        erfc_ar = scipy_erfc(ar)
        exp_ar2 = np.exp(-ar * ar)
        qq = q[i] * q[i + 1:]

        E_real += np.sum(qq * erfc_ar / r)

        f_mag = qq * (erfc_ar / r2 + 2.0 * alpha * inv_sqrt_pi * exp_ar2 / r) / r
        f_vec = f_mag[:, np.newaxis] * dr
        F_real[i] -= np.sum(f_vec, axis=0)
        F_real[i + 1:] += f_vec

    # ========== Reciprocal-space sum ==========
    E_recip = 0.0
    F_recip = np.zeros((N, 3))

    two_pi_over_L = 2.0 * np.pi / L
    inv_4alpha2 = 1.0 / (4.0 * alpha * alpha)
    pref_const = 4.0 * np.pi / V

    for nx in range(-k_max, k_max + 1):
        for ny in range(-k_max, k_max + 1):
            for nz in range(-k_max, k_max + 1):
                if nx == 0 and ny == 0 and nz == 0:
                    continue

                k_vec = np.array([nx, ny, nz], dtype=np.float64) * two_pi_over_L
                k2 = k_vec[0] ** 2 + k_vec[1] ** 2 + k_vec[2] ** 2

                pref = (pref_const / k2) * np.exp(-k2 * inv_4alpha2)

                k_dot_r = pos @ k_vec
                cos_kr = np.cos(k_dot_r)
                sin_kr = np.sin(k_dot_r)

                S_cos = np.dot(q, cos_kr)
                S_sin = np.dot(q, sin_kr)

                E_recip += 0.5 * pref * (S_cos * S_cos + S_sin * S_sin)

                f_scalar = pref * q * (S_sin * cos_kr - S_cos * sin_kr)
                F_recip -= np.outer(f_scalar, k_vec)

    # ========== Self-energy correction ==========
    E_self = -(alpha * inv_sqrt_pi) * np.sum(q * q)

    # ========== Totals ==========
    E_total = E_real + E_recip + E_self
    F_total = F_real + F_recip

    return E_real, E_recip, E_self, E_total, F_total


def ewald_energy_only(positions, charges, box_length, alpha, k_max):
    """Compute only energy (skip force accumulation for speed)."""
    E_r, E_k, E_s, E_t, _ = ewald_energy_and_forces(
        positions, charges, box_length, alpha, k_max
    )
    return E_r, E_k, E_s, E_t


def main():
    # Load crystal data from NPZ files
    crystal_data = np.load('/app/data/nacl_crystal.npz')
    crystal_pos = crystal_data['positions'].copy()
    crystal_q = crystal_data['charges'].copy()
    L = float(crystal_data['box_length'])
    d = float(crystal_data['d'])
    N = int(crystal_data['n_particles'])
    crystal_data.close()

    perturbed_data = np.load('/app/data/perturbed_crystal.npz')
    pert_pos = perturbed_data['positions'].copy()
    pert_q = perturbed_data['charges'].copy()
    perturbed_data.close()

    alpha = 1.25  # from params.ini

    # --- Perfect crystal ---
    print("Computing Ewald sum for perfect NaCl crystal...")
    E_r_c, E_k_c, E_s_c, E_c, F_c = ewald_energy_and_forces(
        crystal_pos, crystal_q, L, alpha, 7
    )
    madelung = -2.0 * E_c * d / N
    max_force = float(np.max(np.linalg.norm(F_c, axis=1)))
    print(f"  Madelung constant = {madelung:.10f}  (ref: 1.7475645946)")
    print(f"  Max force = {max_force:.2e}")

    # --- Perturbed crystal ---
    print("Computing Ewald sum for perturbed crystal...")
    E_r_p, E_k_p, E_s_p, E_p, F_p = ewald_energy_and_forces(
        pert_pos, pert_q, L, alpha, 7
    )
    force_sum = np.sum(F_p, axis=0).tolist()
    print(f"  E_total = {E_p:.10f}")
    print(f"  Force sum = [{force_sum[0]:.2e}, {force_sum[1]:.2e}, {force_sum[2]:.2e}]")

    # --- Finite difference check ---
    print("Computing finite difference check...")
    dx = 1e-5

    pos_plus = pert_pos.copy()
    pos_plus[0, 0] = (pos_plus[0, 0] + dx) % L
    _, _, _, E_plus, _ = ewald_energy_and_forces(pos_plus, pert_q, L, alpha, 7)

    pos_minus = pert_pos.copy()
    pos_minus[0, 0] = (pos_minus[0, 0] - dx) % L
    _, _, _, E_minus, _ = ewald_energy_and_forces(pos_minus, pert_q, L, alpha, 7)

    numerical_fx = -(E_plus - E_minus) / (2.0 * dx)
    analytical_fx = float(F_p[0, 0])
    if abs(analytical_fx) > 1e-10:
        rel_err = abs(numerical_fx - analytical_fx) / abs(analytical_fx)
    else:
        rel_err = abs(numerical_fx - analytical_fx)
    print(f"  Analytical F_x[0] = {analytical_fx:.10f}")
    print(f"  Numerical  F_x[0] = {numerical_fx:.10f}")
    print(f"  Relative error    = {rel_err:.2e}")

    # --- Convergence study ---
    print("\n--- Convergence Study ---")
    ref_madelung = 1.7475645946
    convergence_study = []

    for km in [3, 4, 5, 6, 7, 8, 9]:
        _, E_k_km, _, E_t_km = ewald_energy_only(
            crystal_pos, crystal_q, L, alpha, km
        )
        M_km = -2.0 * E_t_km * d / N
        error = abs(M_km - ref_madelung)
        convergence_study.append({"k_max": km, "madelung": float(M_km)})
        print(f"  k_max={km}: M={M_km:.10f}, error={error:.2e}")

    min_converged_k_max = None
    for entry in convergence_study:
        if abs(entry["madelung"] - ref_madelung) < 1e-3:
            min_converged_k_max = entry["k_max"]
            break

    print(f"  min_converged_k_max = {min_converged_k_max}")

    # --- Write results ---
    result = {
        "nacl_madelung": float(madelung),
        "nacl_max_force": float(max_force),
        "perturbed_energy": float(E_p),
        "perturbed_energy_components": {
            "real": float(E_r_p),
            "recip": float(E_k_p),
            "self": float(E_s_p)
        },
        "perturbed_forces": F_p.tolist(),
        "perturbed_force_sum": force_sum,
        "fd_check": {
            "dx": dx,
            "energy_plus": float(E_plus),
            "energy_minus": float(E_minus),
            "numerical_force_x": float(numerical_fx)
        },
        "convergence_study": convergence_study,
        "min_converged_k_max": min_converged_k_max
    }

    with open("/app/result.json", "w") as f:
        json.dump(result, f, indent=2)

    print("\nResults written to /app/result.json")


if __name__ == "__main__":
    main()
