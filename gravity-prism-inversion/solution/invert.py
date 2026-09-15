
"""
Gravity inversion pipeline.
Implements:
1. Analytical forward model for right-rectangular prisms (Nagy/Plouff formula)
2. Jacobian matrix assembly
3. Tikhonov-regularized least-squares inversion with GCV
"""

import csv
import json
import math
import os

import numpy as np
from scipy import linalg

G_CONST = 6.674e-11  # gravitational constant in m^3/(kg*s^2)


# ============================================================
# Forward model: prism gravity
# ============================================================

def kernel_gz(x, y, z):
    """
    Kernel function for g_z (upward gravity component) at a single vertex.
    Based on Nagy (2000) / Plouff (1976) analytical formula.
    """
    r = math.sqrt(x * x + y * y + z * z)
    if r < 1e-20:
        return 0.0
    result = 0.0
    yr = y + r
    if abs(x) > 1e-15 and yr > 1e-15:
        result += x * math.log(yr)
    xr = x + r
    if abs(y) > 1e-15 and xr > 1e-15:
        result += y * math.log(xr)
    if abs(z) > 1e-15:
        result -= z * math.atan2(x * y, z * r)
    return result


def prism_gz_mgal(xp, yp, zp, prism, density):
    """
    Compute g_z (downward positive) in mGal at point (xp, yp, zp)
    from a rectangular prism [x1, x2, y1, y2, z1, z2] with given density.

    Uses the 8-vertex summation with alternating signs and the
    observation-minus-boundary coordinate convention.
    """
    x1, x2, y1, y2, z1, z2 = prism
    total = 0.0
    bounds_x = [x1, x2]
    bounds_y = [y1, y2]
    bounds_z = [z1, z2]
    for i in range(2):
        for j in range(2):
            for k in range(2):
                sign = (-1) ** (i + j + k)
                dx = xp - bounds_x[i]
                dy = yp - bounds_y[j]
                dz = zp - bounds_z[k]
                total += sign * kernel_gz(dx, dy, dz)
    # g_upward = G * rho * total; g_z (downward) = -g_upward
    gz_si = -G_CONST * density * total
    return gz_si * 1e5  # convert SI to mGal


def prism_gz_mgal_vectorized(obs_points, prism, density):
    """Compute g_z for an array of observation points from a single prism."""
    results = np.zeros(len(obs_points))
    for idx, (xp, yp, zp) in enumerate(obs_points):
        results[idx] = prism_gz_mgal(xp, yp, zp, prism, density)
    return results


# ============================================================
# Build prism grid
# ============================================================

def build_prism_grid(config):
    """Build prism grid from model config."""
    ms = config["model_space"]
    cell_e = ms["cell_size_east"]
    cell_n = ms["cell_size_north"]
    cell_d = ms["cell_size_depth"]
    prisms = []
    for ie in range(ms["n_east"]):
        for jn in range(ms["n_north"]):
            for kd in range(ms["n_depth"]):
                x1 = ms["east_min"] + ie * cell_e
                x2 = x1 + cell_e
                y1 = ms["north_min"] + jn * cell_n
                y2 = y1 + cell_n
                z2 = -kd * cell_d
                z1 = -(kd + 1) * cell_d
                prisms.append({
                    "id": len(prisms),
                    "bounds": [x1, x2, y1, y2, z1, z2],
                    "center": [(x1 + x2) / 2, (y1 + y2) / 2, (z1 + z2) / 2],
                })
    return prisms


# ============================================================
# Jacobian matrix assembly
# ============================================================

def build_jacobian(obs_points, prisms):
    """
    Build the sensitivity matrix G where G[i,j] is the g_z at observation
    point i from prism j with unit density (1 kg/m^3).
    """
    n_obs = len(obs_points)
    n_prisms = len(prisms)
    G = np.zeros((n_obs, n_prisms))

    for j, prism in enumerate(prisms):
        if j % 50 == 0:
            print(f"  Building Jacobian column {j}/{n_prisms}...")
        for i, (xp, yp, zp) in enumerate(obs_points):
            G[i, j] = prism_gz_mgal(xp, yp, zp, prism["bounds"], 1.0)

    return G


# ============================================================
# GCV-based regularization parameter selection
# ============================================================

def gcv_score(U, s, d_proj, lam, n):
    """
    Compute GCV score for a given lambda.

    Using SVD: G = U S V^T
    The GCV function is:
    GCV(lambda) = (1/n) * ||A(lambda) d||^2 / [(1/n) * trace(A(lambda))]^2

    where A(lambda) = I - G(G^T G + lambda^2 I)^{-1} G^T
    """
    # d_proj = U^T d (projection of data onto left singular vectors)
    # s = singular values
    p = len(s)

    # Filter factors
    f = s ** 2 / (s ** 2 + lam ** 2)

    # Residual norm squared
    residual_sq = 0.0
    for i in range(p):
        residual_sq += (1 - f[i]) ** 2 * d_proj[i] ** 2
    # Add contribution from components beyond SVD (if n > p)
    d_norm_sq = np.sum(d_proj[:n] ** 2)  # This might not be right
    if n > p:
        residual_sq += np.sum(d_proj[p:n] ** 2)

    # Effective degrees of freedom
    trace_A = n - np.sum(f)
    if n > p:
        trace_A = n - np.sum(f)

    if trace_A < 1e-15:
        return np.inf

    gcv = (residual_sq / n) / (trace_A / n) ** 2
    return gcv


def select_lambda_gcv(G, d):
    """Select regularization parameter by GCV using SVD."""
    n, m = G.shape
    U, s, Vt = linalg.svd(G, full_matrices=True)

    # Project data
    d_proj = U.T @ d

    # Search over lambda range
    s_max = s[0]
    s_min = s[min(len(s) - 1, m - 1)]
    if s_min < 1e-15:
        s_min = s_max * 1e-10

    lambdas = np.logspace(
        np.log10(s_min * 0.01),
        np.log10(s_max * 10),
        100,
    )

    best_gcv = np.inf
    best_lambda = lambdas[len(lambdas) // 2]

    for lam in lambdas:
        score = gcv_score(U, s, d_proj, lam, n)
        if score < best_gcv:
            best_gcv = score
            best_lambda = lam

    return best_lambda, U, s, Vt


# ============================================================
# Tikhonov inversion
# ============================================================

def tikhonov_inversion(G, d, lam):
    """
    Solve: min ||Gm - d||^2 + lambda^2 * ||m||^2
    Solution: m = (G^T G + lambda^2 I)^{-1} G^T d
    Using SVD for numerical stability.
    """
    U, s, Vt = linalg.svd(G, full_matrices=False)
    d_proj = U.T @ d

    # Damped pseudoinverse: m = V * diag(s/(s^2+lam^2)) * U^T * d
    f = s / (s ** 2 + lam ** 2)
    m = Vt.T @ (f * d_proj)
    return m


# ============================================================
# Main pipeline
# ============================================================

def main():
    print("=" * 60)
    print("3D Gravity Inversion Pipeline")
    print("=" * 60)

    # Load configuration
    with open("/app/model_config.json") as f:
        config = json.load(f)

    # Load observed data
    obs_points = []
    obs_gz = []
    with open("/app/observed_data.csv") as f:
        reader = csv.DictReader(f)
        for row in reader:
            obs_points.append((float(row["x"]), float(row["y"]), float(row["z"])))
            obs_gz.append(float(row["gz_mgal"]))

    obs_gz = np.array(obs_gz)
    n_obs = len(obs_points)
    print(f"Loaded {n_obs} observation points")

    # Build prism grid
    prisms = build_prism_grid(config)
    n_prisms = len(prisms)
    print(f"Built {n_prisms} prisms")

    # Build Jacobian
    print("\nBuilding Jacobian matrix...")
    G = build_jacobian(obs_points, prisms)
    print(f"Jacobian shape: {G.shape}")

    # Select regularization parameter
    print("\nSelecting regularization parameter via GCV...")
    best_lambda, _, _, _ = select_lambda_gcv(G, obs_gz)
    print(f"Selected lambda = {best_lambda:.6e}")

    # Perform inversion
    print("\nPerforming Tikhonov inversion...")
    m = tikhonov_inversion(G, obs_gz, best_lambda)
    print(f"Density range: [{m.min():.2f}, {m.max():.2f}] kg/m^3")

    # Compute predicted data
    predicted = G @ m
    residuals = obs_gz - predicted
    rms = float(np.sqrt(np.mean(residuals ** 2)))
    print(f"RMS misfit: {rms:.4f} mGal")

    # If RMS is too high, try adjusting lambda
    if rms > 0.15:
        print("\nRMS too high, refining lambda search...")
        lambdas_fine = np.logspace(
            np.log10(best_lambda * 0.001),
            np.log10(best_lambda * 10),
            200,
        )
        best_rms = rms
        for lam in lambdas_fine:
            m_trial = tikhonov_inversion(G, obs_gz, lam)
            pred_trial = G @ m_trial
            rms_trial = float(np.sqrt(np.mean((obs_gz - pred_trial) ** 2)))
            if rms_trial < best_rms and np.max(np.abs(m_trial)) < 2000:
                best_rms = rms_trial
                best_lambda = lam
                m = m_trial
                predicted = pred_trial
        rms = best_rms
        print(f"Refined lambda = {best_lambda:.6e}")
        print(f"Refined RMS = {rms:.4f} mGal")

    # Write output files
    os.makedirs("/app/results", exist_ok=True)

    # Write recovered densities
    print("\nWriting output files...")
    with open("/app/results/recovered_densities.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["prism_id", "x_center", "y_center", "z_center", "density_kg_m3"])
        for i, prism in enumerate(prisms):
            xc, yc, zc = prism["center"]
            writer.writerow([
                prism["id"],
                f"{xc:.1f}",
                f"{yc:.1f}",
                f"{zc:.1f}",
                f"{m[i]:.6f}",
            ])

    # Write predicted gravity
    with open("/app/results/predicted_gravity.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["x", "y", "z", "gz_predicted_mgal"])
        for i, (xp, yp, zp) in enumerate(obs_points):
            writer.writerow([
                f"{xp:.1f}",
                f"{yp:.1f}",
                f"{zp:.1f}",
                f"{predicted[i]:.8f}",
            ])

    # Write inversion summary
    summary = {
        "rms_misfit_mgal": round(rms, 6),
        "regularization_lambda": round(float(best_lambda), 8),
        "n_prisms": n_prisms,
        "n_observations": n_obs,
    }
    with open("/app/results/inversion_summary.json", "w") as f:
        json.dump(summary, f, indent=2)

    print(f"\nDone! RMS misfit = {rms:.4f} mGal")
    print(f"Output files written to /app/results/")


if __name__ == "__main__":
    main()
