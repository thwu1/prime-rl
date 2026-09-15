"""
Generate reference outputs using the correct EOF/Promax implementation.
This script runs during Docker build and is removed afterward.

"""
import numpy as np
from scipy.linalg import svd, inv
import json
import os


def varimax_criterion(loadings):
    """Sum of column variances of squared loadings."""
    L2 = loadings ** 2
    return np.sum(np.mean(L2 ** 2, axis=0) - np.mean(L2, axis=0) ** 2)


def varimax_rotation(loadings, max_iter=1000, rtol=1e-8):
    """Kaiser-normalized Varimax rotation via SVD-based analytic iteration."""
    n, k = loadings.shape
    communalities = np.sqrt(np.sum(loadings ** 2, axis=1, keepdims=True))
    communalities = np.maximum(communalities, 1e-12)
    A = loadings / communalities
    R = np.eye(k)
    d = 0.0
    for _ in range(max_iter):
        old_d = d
        B = A @ R
        B2 = B ** 2
        G = A.T @ (B ** 3 - B @ np.diag(np.mean(B2, axis=0)))
        P, S_vals, Qt = svd(G, full_matrices=False)
        R = P @ Qt
        d = np.sum(S_vals)
        if abs(d - old_d) / max(abs(d), 1e-12) < rtol:
            break
    rotated = (A @ R) * communalities
    return rotated, R


def main():
    import xarray as xr

    # Read data from NetCDF
    ds = xr.open_dataset('/app/climate_data.nc')
    data = ds['sst_anomaly'].values
    lats = ds['latitude'].values
    land_mask = ds['land_mask'].values.astype(bool)
    ds.close()

    n_time, n_lat, n_lon = data.shape

    with open('/app/task_config.json') as f:
        config = json.load(f)
    n_modes = config['n_modes']
    n_rotate = config['n_rotate']
    power = config['rotation_power']

    # Correct preprocessing: sqrt(cos(lat)) weighting
    lat_rad = np.deg2rad(lats)
    coslat = np.sqrt(np.maximum(np.cos(lat_rad), 0.0))
    coslat_weights = coslat[:, None] * np.ones((1, n_lon))
    weighted = data * coslat_weights[None, :, :]
    flat = weighted.reshape(n_time, -1)
    valid_mask = ~land_mask.ravel()
    X = flat[:, valid_mask]
    X = X - X.mean(axis=0)

    # SVD decomposition
    U, s, Vt = svd(X, full_matrices=False)
    U = U[:, :n_modes]
    s = s[:n_modes]
    Vt = Vt[:n_modes, :]

    # Deterministic sign convention
    for i in range(n_modes):
        max_idx = np.argmax(np.abs(Vt[i]))
        if Vt[i, max_idx] < 0:
            Vt[i] *= -1
            U[:, i] *= -1

    components = Vt
    scores = U * s[None, :]

    # Correct explained variance: s^2 / (N-1)
    exp_var = s ** 2 / (n_time - 1)
    total_var = np.sum(np.var(X, axis=0, ddof=1))
    exp_var_ratio = exp_var / total_var

    # Loadings for rotation
    loadings = components[:n_rotate].T * np.sqrt(exp_var[:n_rotate])[None, :]
    vc_before = varimax_criterion(loadings)

    # Varimax rotation (with Kaiser normalization)
    varimax_load, R_varimax = varimax_rotation(loadings)
    vc_after = varimax_criterion(varimax_load)

    # Correct Promax target: sign-preserving power
    target = np.sign(varimax_load) * np.abs(varimax_load) ** power
    H = varimax_load
    HtH_inv = inv(H.T @ H)
    R_pro = HtH_inv @ (H.T @ target)
    col_norms = np.sqrt(np.sum(R_pro ** 2, axis=0))
    R_pro_normalized = R_pro / col_norms[None, :]
    promax_load = H @ R_pro_normalized
    R_combined = R_varimax @ R_pro_normalized

    R_inv_comb = inv(R_combined)
    C = R_inv_comb @ R_inv_comb.T
    d_diag = np.sqrt(np.diag(C))
    phi = C / np.outer(d_diag, d_diag)

    # Rotated variance and reordering
    rot_exp_var = np.sum(promax_load ** 2, axis=0)
    order = np.argsort(rot_exp_var)[::-1]
    promax_load = promax_load[:, order]
    rot_exp_var = rot_exp_var[order]
    R_combined = R_combined[:, order]
    phi = phi[np.ix_(order, order)]

    # Rotated components with sign convention
    rot_components = (promax_load / np.sqrt(rot_exp_var)[None, :]).T
    sign_mult = np.ones(n_rotate)
    for i in range(n_rotate):
        max_idx = np.argmax(np.abs(rot_components[i]))
        if rot_components[i, max_idx] < 0:
            sign_mult[i] = -1.0
            rot_components[i] *= -1

    # Correct rotated scores: inv(R)^T for oblique rotation
    U_trunc = scores[:, :n_rotate] / s[None, :n_rotate]
    R_invT = inv(R_combined).T
    rot_scores_norm = U_trunc @ R_invT
    pseudo_norms = np.sqrt(rot_exp_var * (n_time - 1))
    rot_scores = rot_scores_norm * pseudo_norms[None, :]
    rot_scores = rot_scores * sign_mult[None, :]

    rot_exp_var_ratio = rot_exp_var / total_var

    # Save reference outputs
    out_dir = '/app/reference'
    os.makedirs(out_dir, exist_ok=True)
    np.save(f'{out_dir}/total_variance.npy', total_var)
    np.save(f'{out_dir}/unrotated_expvar_ratio.npy', exp_var_ratio)
    np.save(f'{out_dir}/unrotated_components.npy', components)
    np.save(f'{out_dir}/unrotated_scores.npy', scores)
    np.save(f'{out_dir}/rotated_components.npy', rot_components)
    np.save(f'{out_dir}/rotated_scores.npy', rot_scores)
    np.save(f'{out_dir}/rotated_expvar_ratio.npy', rot_exp_var_ratio)
    np.save(f'{out_dir}/rotation_matrix.npy', R_combined)
    np.save(f'{out_dir}/phi_matrix.npy', phi)
    np.save(f'{out_dir}/varimax_criterion_before.npy', vc_before)
    np.save(f'{out_dir}/varimax_criterion_after.npy', vc_after)


if __name__ == '__main__':
    main()
