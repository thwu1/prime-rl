"""
EOF Analysis Pipeline
Extracts leading modes of variability from SST data via singular value
decomposition, applies Varimax rotation, and tests mode significance
with bootstrap resampling.
"""
import numpy as np
import xarray as xr
import json
import os
from scipy.linalg import svd


def load_and_preprocess(data_path):
    """Load SST data, extract ocean grid points, and prepare for analysis."""
    ds = xr.open_dataset(data_path)
    sst = ds['sst_anomaly'].values  # (time, lat, lon)
    lat = ds['lat'].values
    ntime, nlat, nlon = sst.shape

    # Identify ocean points using the NaN mask (constant across time)
    ocean_mask = ~np.isnan(sst[0])
    X = sst[:, ocean_mask]  # Flatten spatial dims -> (time, n_ocean_points)

    # Remove mean to center the data
    X = X - np.nanmean(X)

    return X, ocean_mask, lat, ntime, nlat, nlon


def compute_eof(X, n_modes=10):
    """Extract leading EOF modes via truncated SVD."""
    ntime = X.shape[0]
    U, s, Vt = svd(X, full_matrices=False)

    # Eigenvalues from singular values
    eigenvalues = s[:n_modes] ** 2 / ntime
    total_var = float(np.sum(np.var(X, axis=0, ddof=1)))
    ratios = eigenvalues / total_var

    return ratios, eigenvalues, s[:n_modes], Vt[:n_modes], total_var


def varimax_rotation(Vt, eigenvalues, total_var, n_rot=5, max_iter=1000, tol=1e-8):
    """Apply Varimax rotation to leading EOF loadings."""
    # Construct loadings: each mode scaled by its eigenvalue
    L = Vt[:n_rot].T * eigenvalues[:n_rot]

    p, k = L.shape
    R = np.eye(k)

    for iteration in range(max_iter):
        R_old = R.copy()

        for i in range(k):
            for j in range(i + 1, k):
                u = L[:, i] ** 2 - L[:, j] ** 2
                v = 2 * L[:, i] * L[:, j]

                A = np.sum(u)
                B = np.sum(v)
                C = np.sum(u ** 2 - v ** 2)
                D = 2 * np.sum(u * v)

                num = D - 2 * A * B / p
                den = C - (A ** 2 - B ** 2) / p
                theta = 0.25 * np.arctan2(num, den)

                cos_t, sin_t = np.cos(theta), np.sin(theta)

                Li = L[:, i] * cos_t + L[:, j] * sin_t
                Lj = -L[:, i] * sin_t + L[:, j] * cos_t
                L[:, i], L[:, j] = Li, Lj

                Ri = R[:, i] * cos_t + R[:, j] * sin_t
                Rj = -R[:, i] * sin_t + R[:, j] * cos_t
                R[:, i], R[:, j] = Ri, Rj

        if np.max(np.abs(R - R_old)) < tol:
            break

    # Rotated explained variance
    rot_var = np.sum(L ** 2, axis=0) / total_var
    order = np.argsort(-rot_var)

    return R[:, order].tolist(), rot_var[order].tolist()


def bootstrap_significance(X, n_modes=10, n_boot=100, seed=42):
    """Bootstrap resampling to assess eigenvalue significance."""
    rng = np.random.RandomState(seed)
    ntime = X.shape[0]

    boot_eigenvalues = []
    for _ in range(n_boot):
        idx = rng.choice(ntime, size=ntime, replace=True)
        X_boot = X[idx]
        X_boot = X_boot - X_boot.mean(axis=0)
        _, s_boot, _ = svd(X_boot, full_matrices=False)
        ev = s_boot[:n_modes] ** 2 / (ntime - 1)
        boot_eigenvalues.append(ev)

    boot_eigenvalues = np.array(boot_eigenvalues)

    # 95% confidence intervals using normal approximation
    means = np.mean(boot_eigenvalues, axis=0)
    stds = np.std(boot_eigenvalues, axis=0)
    ci_lower = means - 1.96 * stds
    ci_upper = means + 1.96 * stds

    # Count consecutive significant modes (CI non-overlap with next mode)
    n_sig = 0
    for k in range(n_modes - 1):
        if ci_lower[k] > ci_upper[k + 1]:
            n_sig += 1
        else:
            break

    ci_pairs = [[float(ci_lower[k]), float(ci_upper[k])] for k in range(n_modes)]
    return n_sig, ci_pairs


def main():
    data_path = '/app/data/sst_anomaly.nc'
    n_modes = 10
    n_rot = 5

    X, ocean_mask, lat, ntime, nlat, nlon = load_and_preprocess(data_path)

    ratios, eigenvalues, s, Vt, total_var = compute_eof(X, n_modes)
    cum_var = np.cumsum(ratios).tolist()

    R, rot_ratios = varimax_rotation(Vt, eigenvalues, total_var, n_rot)

    n_sig, ci_pairs = bootstrap_significance(X, n_modes)

    results = {
        'n_modes_computed': n_modes,
        'explained_variance_ratios': ratios.tolist(),
        'cumulative_variance': cum_var,
        'n_modes_rotated': n_rot,
        'rotation_matrix': R,
        'rotated_explained_variance_ratios': rot_ratios,
        'n_significant_modes': n_sig,
        'bootstrap_eigenvalue_ci': ci_pairs
    }

    os.makedirs('/app/pipeline/output', exist_ok=True)
    with open('/app/pipeline/output/results.json', 'w') as f:
        json.dump(results, f, indent=2)

    print("Analysis complete. Results saved to /app/pipeline/output/results.json")


if __name__ == '__main__':
    main()
