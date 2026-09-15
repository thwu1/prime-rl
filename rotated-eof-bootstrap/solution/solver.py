
"""Corrected EOF analysis pipeline — fixes all bugs in /app/pipeline/analyze.py."""

import numpy as np
import xarray as xr
import json
import os


def load_and_preprocess(data_path):
    """Load SST data with correct centering and area weighting."""
    ds = xr.open_dataset(data_path)
    sst = ds['sst_anomaly'].values
    lat = ds['lat'].values
    ntime, nlat, nlon = sst.shape

    ocean_mask = ~np.isnan(sst[0])
    X = sst[:, ocean_mask]

    # Fix 1: per-column temporal mean (not scalar global mean)
    X = X - X.mean(axis=0)

    # Fix 2: apply cosine-latitude area weighting
    lat_grid = np.broadcast_to(lat[:, None], (nlat, nlon))
    lat_ocean = lat_grid[ocean_mask]
    weights = np.sqrt(np.clip(np.cos(np.deg2rad(lat_ocean)), 0, 1))
    X = X * weights[None, :]

    return X, ntime


def compute_eof(X, n_modes):
    """Compute EOF modes via SVD with correct normalization."""
    ntime = X.shape[0]
    U, s, Vt = np.linalg.svd(X, full_matrices=False)

    s = s[:n_modes]
    V = Vt[:n_modes, :].T

    # Fix 3: sample variance normalization (N-1, not N)
    eigenvalues = s ** 2 / (ntime - 1)
    total_variance = float(np.sum(np.var(X, axis=0, ddof=1)))
    ev_ratios = eigenvalues / total_variance

    return V, eigenvalues, total_variance, ev_ratios


def varimax_rotation(L, max_iter=1000, tol=1e-8):
    """Kaiser varimax rotation on loadings matrix."""
    p, k = L.shape
    R = np.eye(k)
    L = L.copy()

    for _ in range(max_iter):
        R_old = R.copy()

        for i in range(k):
            for j in range(i + 1, k):
                u = L[:, i]
                v = L[:, j]

                x = u ** 2 - v ** 2
                y = 2 * u * v

                A = np.sum(x)
                B = np.sum(y)
                C = np.sum(x ** 2 - y ** 2)
                D = 2 * np.sum(x * y)

                num = D - 2 * A * B / p
                den = C - (A ** 2 - B ** 2) / p

                theta = 0.25 * np.arctan2(num, den)

                cos_t = np.cos(theta)
                sin_t = np.sin(theta)

                Li = L[:, i] * cos_t + L[:, j] * sin_t
                Lj = -L[:, i] * sin_t + L[:, j] * cos_t
                L[:, i] = Li
                L[:, j] = Lj

                Ri = R[:, i] * cos_t + R[:, j] * sin_t
                Rj = -R[:, i] * sin_t + R[:, j] * cos_t
                R[:, i] = Ri
                R[:, j] = Rj

        if np.max(np.abs(R - R_old)) < tol:
            break

    return L, R


def bootstrap_eigenvalues(X, n_modes, n_bootstrap, seed):
    """Bootstrap resampling for eigenvalue confidence intervals."""
    ntime = X.shape[0]
    rng = np.random.RandomState(seed)
    boot_eigs = np.zeros((n_bootstrap, n_modes))

    for b in range(n_bootstrap):
        idx = rng.choice(ntime, ntime, replace=True)
        X_b = X[idx, :]
        X_b = X_b - X_b.mean(axis=0)

        _, s_b, _ = np.linalg.svd(X_b, full_matrices=False)
        boot_eigs[b] = s_b[:n_modes] ** 2 / (ntime - 1)

    return boot_eigs


def main():
    n_modes = 10
    n_rot = 5
    n_bootstrap = 100
    seed = 42

    X, ntime = load_and_preprocess('/app/data/sst_anomaly.nc')

    V, eigenvalues, total_variance, ev_ratios = compute_eof(X, n_modes)
    cumulative = np.cumsum(ev_ratios)

    # Fix 4: loadings use sqrt(eigenvalue), not eigenvalue
    loadings = V[:, :n_rot] * np.sqrt(eigenvalues[:n_rot])
    rot_loadings, rot_matrix = varimax_rotation(loadings)

    rot_var = np.sum(rot_loadings ** 2, axis=0)
    rot_ev_ratios = rot_var / total_variance

    sort_idx = np.argsort(rot_ev_ratios)[::-1]
    rot_ev_ratios = rot_ev_ratios[sort_idx]
    rot_matrix = rot_matrix[:, sort_idx]

    boot_eigs = bootstrap_eigenvalues(X, n_modes, n_bootstrap, seed)

    # Fix 5: percentile-based CIs (not normal approximation)
    ci_lower = np.percentile(boot_eigs, 2.5, axis=0)
    ci_upper = np.percentile(boot_eigs, 97.5, axis=0)

    n_significant = 0
    for k in range(n_modes - 1):
        if ci_lower[k] > ci_upper[k + 1]:
            n_significant = k + 1
        else:
            break

    os.makedirs('/app/results', exist_ok=True)

    results = {
        'n_modes_computed': n_modes,
        'explained_variance_ratios': ev_ratios.tolist(),
        'cumulative_variance': cumulative.tolist(),
        'n_modes_rotated': n_rot,
        'rotation_matrix': rot_matrix.tolist(),
        'rotated_explained_variance_ratios': rot_ev_ratios.tolist(),
        'n_significant_modes': int(n_significant),
        'bootstrap_eigenvalue_ci': [
            [float(ci_lower[k]), float(ci_upper[k])] for k in range(n_modes)
        ]
    }

    with open('/app/results/eof_results.json', 'w') as f:
        json.dump(results, f, indent=2)

    print("Corrected analysis complete.")


if __name__ == '__main__':
    main()
