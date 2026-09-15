#!/usr/bin/env python3
"""
Equivalent-source gravity field continuation with optimal regularization
and uncertainty propagation.

Algorithm
---------
1. Place one fictitious point mass below each observation at candidate depth d.
2. Build the unscaled gravitational kernel K[i,j] = dz_ij / r_ij^3.
3. Scale observations: g_s = g_obs / (G * MGAL) so that K @ m = g_s.
4. Compute thin SVD of K for each candidate depth.
5. For each (depth, damping) pair evaluate Generalised Cross-Validation (GCV).
6. Select the pair that minimises GCV.
7. Recover source coefficients via SVD filtering:
       c = V diag(s/(s^2+lam)) U^T g_s
8. Predict on the regular grid: g_pred = (G*MGAL) * K_grid @ c
9. Propagate observation noise through the regularised inverse to obtain
   prediction standard deviations:
       sigma_pred_i^2 = sigma_noise^2 * sum_k (A_ik)^2 * s_k^2/(s_k^2+lam)^2
   where A = K_grid @ V.
"""
import json
import sys

import numpy as np
from scipy.linalg import svd

G_SI = 6.674e-11        # gravitational constant  [m^3 kg^-1 s^-2]
MGAL = 1e5              # 1 m/s^2 = 1e5 mGal
ALPHA = G_SI * MGAL     # combined scale factor  ~6.674e-6
SIGMA_NOISE = 0.002     # observation noise std  [mGal]


def load_survey(path):
    data = np.loadtxt(path, delimiter=",", skiprows=1)
    return data[:, 0], data[:, 1], data[:, 2], data[:, 3]


def load_grid(path):
    data = np.loadtxt(path, delimiter=",", skiprows=1)
    return data[:, 0], data[:, 1], data[:, 2]


def build_kernel(oe, on, oh, se, sn, sz):
    """
    Build the unscaled gravitational kernel for point-mass sources.

    K[i, j] = dz_ij / r_ij^3

    Full forward model:  g[i] = G * MGAL * sum_j K[i,j] * mass[j]
    """
    n_obs = len(oe)
    n_src = len(se)
    K = np.empty((n_obs, n_src))
    for j in range(n_src):
        dx = oe - se[j]
        dy = on - sn[j]
        dz = oh - sz[j]
        r = np.sqrt(dx * dx + dy * dy + dz * dz)
        K[:, j] = dz / (r * r * r)
    return K


def main(survey_path, grid_path, out_path, diag_path):
    # ------------------------------------------------------------------
    # Load data
    # ------------------------------------------------------------------
    oe, on, oh, og = load_survey(survey_path)
    ge, gn, gh = load_grid(grid_path)
    n_obs = len(oe)

    # Scale observations so K @ m = g_scaled  (removes gravitational constant)
    g_scaled = og / ALPHA

    # ------------------------------------------------------------------
    # Joint search over source depth and damping via GCV
    # ------------------------------------------------------------------
    depths = [200, 300, 400, 600, 800, 1000, 1500, 2000, 2500, 3000, 4000]

    best_gcv = np.inf
    best_depth = depths[0]
    best_lam = 1.0
    best_U = best_s = best_Vt = None
    best_sz = None

    for d in depths:
        sz = oh - d
        K = build_kernel(oe, on, oh, oe, on, sz)
        U, s, Vt = svd(K, full_matrices=False)
        s2 = s * s
        Utg = U.T @ g_scaled

        # Lambda range adapted to the singular-value spectrum of K
        lam_lo = max(s2[-1] * 1e-4, 1e-30)
        lam_hi = s2[0] * 1e2
        lambdas = np.logspace(np.log10(lam_lo), np.log10(lam_hi), 80)

        for lam in lambdas:
            f = s2 / (s2 + lam)
            resid = g_scaled - U @ (f * Utg)
            rss = np.dot(resid, resid)
            tr_H = f.sum()
            denom = n_obs - tr_H
            if denom < 1.0:
                continue
            gcv = n_obs * rss / (denom * denom)
            if gcv < best_gcv:
                best_gcv = gcv
                best_depth = d
                best_lam = lam
                best_U, best_s, best_Vt = U, s, Vt
                best_sz = sz.copy()

    # ------------------------------------------------------------------
    # Solve with optimal parameters
    # ------------------------------------------------------------------
    s2 = best_s * best_s
    f = s2 / (s2 + best_lam)
    Utg_scaled = best_U.T @ g_scaled
    coeffs = best_Vt.T @ (f * Utg_scaled / best_s)

    # RMS misfit in mGal (use unscaled observations)
    Utg_obs = best_U.T @ og
    pred_obs = best_U @ (f * Utg_obs)
    rms_misfit = float(np.sqrt(np.mean((og - pred_obs) ** 2)))

    # ------------------------------------------------------------------
    # Predict on grid
    # ------------------------------------------------------------------
    K_grid = build_kernel(ge, gn, gh, oe, on, best_sz)
    gz_pred = ALPHA * (K_grid @ coeffs)

    # ------------------------------------------------------------------
    # Uncertainty propagation
    # sigma_pred_i^2 = sigma_noise^2 * sum_k A_ik^2 * s_k^2 / (s_k^2+lam)^2
    # where A = K_grid @ V
    # ------------------------------------------------------------------
    V = best_Vt.T
    A = K_grid @ V
    fvar = s2 / (s2 + best_lam) ** 2
    var_pred = SIGMA_NOISE ** 2 * np.sum(A * A * fvar[np.newaxis, :], axis=1)
    gz_unc = np.sqrt(np.maximum(var_pred, 1e-30))
    mean_unc = float(gz_unc.mean())

    # ------------------------------------------------------------------
    # Write outputs
    # ------------------------------------------------------------------
    with open(out_path, "w") as fh:
        fh.write("easting,northing,gz_predicted,gz_uncertainty\n")
        for i in range(len(ge)):
            fh.write(
                "{:.1f},{:.1f},{:.10f},{:.10f}\n".format(
                    ge[i], gn[i], gz_pred[i], gz_unc[i]
                )
            )

    with open(diag_path, "w") as fh:
        json.dump(
            {
                "damping": float(best_lam),
                "rms_misfit": float(rms_misfit),
                "source_depth": float(best_depth),
                "n_sources": int(n_obs),
                "mean_prediction_uncertainty": float(mean_unc),
            },
            fh,
            indent=2,
        )

    print(
        "depth={} damp={:.4e} rms={:.6f} mean_unc={:.6f}".format(
            best_depth, best_lam, rms_misfit, mean_unc
        )
    )


if __name__ == "__main__":
    a = sys.argv[1:]
    main(
        a[0] if len(a) > 0 else "/app/survey.csv",
        a[1] if len(a) > 1 else "/app/prediction_grid.csv",
        a[2] if len(a) > 2 else "/app/predictions.csv",
        a[3] if len(a) > 3 else "/app/diagnostics.json",
    )
