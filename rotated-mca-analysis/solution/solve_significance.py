"""Reference solution: MCA with Varimax rotation and permutation significance testing.

Implements the full pipeline from scratch:
1. Load and preprocess NetCDF climate fields (center, area-weight, NaN removal)
2. Cross-covariance SVD with Bessel correction
3. Varimax rotation via pairwise Jacobi angle optimization
4. Monte Carlo permutation test for mode significance
5. Write structured results to JSON

"""
import json
import numpy as np
import xarray as xr


def load_and_preprocess(path):
    """Load NetCDF, center, sqrt(cos(lat)) weight, flatten, remove NaN features."""
    ds = xr.open_dataset(path, engine='scipy')
    data = ds['data'].values  # (time, lat, lon)
    lat = ds['lat'].values
    ds.close()

    nt, nlat, nlon = data.shape

    # Area weighting: sqrt(cos(lat)) accounts for meridian convergence
    w = np.sqrt(np.cos(np.radians(lat)))[:, None] * np.ones((1, nlon))

    # Remove temporal mean
    centered = data - np.nanmean(data, axis=0)

    # Apply spatial weights
    weighted = centered * w[None, :, :]

    # Flatten spatial dims and remove NaN features
    flat = weighted.reshape(nt, -1)
    valid = ~np.any(np.isnan(flat), axis=0)

    return flat[:, valid], int(valid.sum())


def varimax_rotation(loadings, max_iter=1000, tol=1e-8):
    """Varimax rotation via pairwise Jacobi angle optimization (Kaiser 1958).

    Maximizes the sum of variances of squared loadings across components.
    """
    p, k = loadings.shape
    R = np.eye(k)
    L = loadings.copy()

    for _ in range(max_iter):
        L_old = L.copy()
        for i in range(k - 1):
            for j in range(i + 1, k):
                u = L[:, i] ** 2 - L[:, j] ** 2
                v = 2.0 * L[:, i] * L[:, j]
                A = u.sum()
                B = v.sum()
                C = (u ** 2 - v ** 2).sum()
                D = (2.0 * u * v).sum()

                # Kaiser's angle formula for Varimax criterion
                num = D - 2.0 * A * B / p
                den = C - (A ** 2 - B ** 2) / p
                theta = 0.25 * np.arctan2(num, den)

                ct, st = np.cos(theta), np.sin(theta)

                # Rotate columns i, j of loadings
                Li, Lj = L[:, i].copy(), L[:, j].copy()
                L[:, i] = ct * Li + st * Lj
                L[:, j] = -st * Li + ct * Lj

                # Accumulate rotation matrix
                Ri, Rj = R[:, i].copy(), R[:, j].copy()
                R[:, i] = ct * Ri + st * Rj
                R[:, j] = -st * Ri + ct * Rj

        if np.max(np.abs(L - L_old)) < tol:
            break

    return L, R


def permutation_test(X, Y, observed_sv, n_perm=500, seed=2024, n_modes=6):
    """Monte Carlo permutation test for MCA mode significance.

    Shuffles Y's time dimension while keeping X fixed. For each permutation,
    recomputes the cross-covariance SVD and records squared singular values
    to build a null distribution. Tests whether observed squared covariance
    per mode exceeds chance levels.

    Uses squared singular values (not SCF) as the test statistic because
    normalizing by the total squared covariance conflates signal strength
    with concentration, inflating the null fraction.
    """
    rng = np.random.default_rng(seed)
    nt = X.shape[0]
    observed_sq = observed_sv[:n_modes] ** 2
    null_sq = np.zeros((n_perm, n_modes))

    for i in range(n_perm):
        perm_idx = rng.permutation(nt)
        Y_perm = Y[perm_idx, :]
        C_perm = X.T @ Y_perm / (nt - 1)
        _, s_perm, _ = np.linalg.svd(C_perm, full_matrices=False)
        null_sq[i, :] = s_perm[:n_modes] ** 2

    # One-sided p-values with +1 correction
    p_values = np.zeros(n_modes)
    for k in range(n_modes):
        count = np.sum(null_sq[:, k] >= observed_sq[k])
        p_values[k] = (count + 1) / (n_perm + 1)

    return p_values


def main():
    n_modes = 6

    # ------ Load and preprocess both fields ------
    X, n_feat_x = load_and_preprocess('/app/data/field_x.nc')
    Y, n_feat_y = load_and_preprocess('/app/data/field_y.nc')
    nt = X.shape[0]

    # ------ Cross-covariance SVD (Bessel-corrected) ------
    C = X.T @ Y / (nt - 1)
    U_full, s_full, Vt_full = np.linalg.svd(C, full_matrices=False)
    U = U_full[:, :n_modes]
    s = s_full[:n_modes]
    V = Vt_full[:n_modes, :].T

    # Squared covariance fractions (denominator uses ALL singular values)
    total_sq_cov = np.sum(s_full ** 2)
    scf = s ** 2 / total_sq_cov

    # ------ Concatenated loadings ------
    sqrt_s = np.sqrt(s)
    A = U * sqrt_s  # (n_feat_x, n_modes)
    B = V * sqrt_s  # (n_feat_y, n_modes)
    L = np.vstack([A, B])

    # ------ Varimax rotation ------
    L_rot, R = varimax_rotation(L)
    A_rot = L_rot[:n_feat_x, :]
    B_rot = L_rot[n_feat_x:, :]

    # ------ Rotated variance per mode ------
    rot_var = np.sum(L_rot ** 2, axis=0)
    rvf = rot_var / rot_var.sum()

    # ------ Sort by descending rotated variance ------
    sort_idx = np.argsort(-rot_var)
    rvf = rvf[sort_idx]
    R = R[:, sort_idx]
    A_rot = A_rot[:, sort_idx]
    B_rot = B_rot[:, sort_idx]

    # ------ Expansion coefficient cross-correlations ------
    a_norms = np.linalg.norm(A_rot, axis=0)
    b_norms = np.linalg.norm(B_rot, axis=0)
    scores_x = X @ (A_rot / a_norms)
    scores_y = Y @ (B_rot / b_norms)
    cc = [float(np.corrcoef(scores_x[:, i], scores_y[:, i])[0, 1])
          for i in range(n_modes)]

    # ------ Permutation significance test ------
    p_values = permutation_test(X, Y, s_full, n_perm=500, seed=2024,
                                n_modes=n_modes)
    significant = [bool(p < 0.05) for p in p_values]
    n_significant = sum(significant)

    # ------ Write results ------
    results = {
        'n_samples': int(nt),
        'n_features_x': int(n_feat_x),
        'n_features_y': int(n_feat_y),
        'singular_values': [float(v) for v in s],
        'scf': [float(v) for v in scf],
        'rotation_matrix': [[float(v) for v in row] for row in R.tolist()],
        'rotated_variance_fraction': [float(v) for v in rvf],
        'cross_correlations': cc,
        'permutation_p_values': [float(v) for v in p_values],
        'n_significant_modes': n_significant,
        'significant_modes': significant,
    }

    with open('/app/results.json', 'w') as fh:
        json.dump(results, fh, indent=2)

    print("Results written to /app/results.json")


if __name__ == '__main__':
    main()
