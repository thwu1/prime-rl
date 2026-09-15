"""
Complete Promax-rotated EOF analysis pipeline.

"""
import numpy as np
from scipy.linalg import svd as scipy_svd, inv
import json
import os


def load_data():
    """Load the synthetic climate dataset."""
    d = np.load('/app/climate_data.npz')
    return d['data'], d['lats'], d['lons'], d['land_mask']


def preprocess(data, lats, land_mask):
    """
    Apply cosine-latitude weighting, NaN masking, and centering.

    Returns:
        X_centered: (n_time, n_valid) centered, weighted data matrix
        valid_mask: boolean mask of valid (non-NaN) spatial points
        temporal_mean: (n_valid,) mean removed during centering
        coslat_weights: (n_lat, n_lon) weight array applied
    """
    n_time, n_lat, n_lon = data.shape

    # Cosine-latitude weighting: sqrt(cos(lat_radians))
    lat_rad = np.deg2rad(lats)
    coslat = np.sqrt(np.maximum(np.cos(lat_rad), 0.0))
    coslat_weights = coslat[:, None] * np.ones((1, n_lon))

    # Apply weights
    weighted = data * coslat_weights[None, :, :]

    # Flatten to 2D: (n_time, n_lat*n_lon)
    flat = weighted.reshape(n_time, -1)

    # Remove NaN columns (land points)
    valid_mask = ~land_mask.ravel()
    X = flat[:, valid_mask]

    # Center: remove temporal mean
    temporal_mean = X.mean(axis=0)
    X_centered = X - temporal_mean

    return X_centered, valid_mask, temporal_mean, coslat_weights


def eof_svd(X, n_modes):
    """
    EOF decomposition via SVD.

    X: (n_time, n_features) centered data matrix
    n_modes: number of modes to retain

    Returns:
        components: (n_modes, n_features) normalized EOFs (V^T rows)
        scores: (n_time, n_modes) unnormalized PC scores (U * s)
        singular_values: (n_modes,) singular values
        exp_var: (n_modes,) explained variance per mode
        exp_var_ratio: (n_modes,) explained variance fraction
        total_var: scalar total variance
    """
    n_time, n_features = X.shape

    U, s, Vt = scipy_svd(X, full_matrices=False)

    # Truncate to n_modes
    U = U[:, :n_modes]
    s = s[:n_modes]
    Vt = Vt[:n_modes, :]

    # Deterministic sign convention: for each mode, the element with
    # the largest absolute value in the component vector is positive
    for i in range(n_modes):
        max_idx = np.argmax(np.abs(Vt[i]))
        if Vt[i, max_idx] < 0:
            Vt[i] *= -1
            U[:, i] *= -1

    components = Vt
    scores = U * s[None, :]

    # Explained variance: eigenvalue of covariance matrix = s^2 / (n-1)
    exp_var = s**2 / (n_time - 1)
    total_var = np.sum(np.var(X, axis=0, ddof=1))
    exp_var_ratio = exp_var / total_var

    return components, scores, s, exp_var, exp_var_ratio, total_var


def varimax_criterion(loadings):
    """
    Compute the Varimax criterion: sum of column variances of squared
    loadings. Higher means simpler structure.

    V = sum_j [ E(L_j^4) - E(L_j^2)^2 ]
    """
    L2 = loadings**2
    return np.sum(np.mean(L2**2, axis=0) - np.mean(L2, axis=0)**2)


def varimax_rotation(loadings, max_iter=1000, rtol=1e-8):
    """
    Varimax rotation with Kaiser normalization.

    Uses the analytic SVD-based iteration (Sherin, 1966).

    loadings: (n_features, n_factors) loading matrix
    Returns:
        rotated_loadings: (n_features, n_factors)
        R: (n_factors, n_factors) orthogonal rotation matrix
    """
    n, k = loadings.shape

    # Kaiser normalization: normalize each row to unit length
    communalities = np.sqrt(np.sum(loadings**2, axis=1, keepdims=True))
    communalities = np.maximum(communalities, 1e-12)
    A = loadings / communalities

    R = np.eye(k)
    d = 0.0

    for iteration in range(max_iter):
        old_d = d
        B = A @ R

        # SVD-based Varimax step
        # Gradient: G = A^T (B^3 - B @ diag(mean(B^2)))
        B2 = B**2
        G = A.T @ (B**3 - B @ np.diag(np.mean(B2, axis=0)))

        P, S_vals, Qt = scipy_svd(G, full_matrices=False)
        R = P @ Qt

        d = np.sum(S_vals)
        if abs(d - old_d) / max(abs(d), 1e-12) < rtol:
            break

    # Apply rotation and undo Kaiser normalization
    rotated = (A @ R) * communalities

    return rotated, R


def promax_rotation(loadings, power=2, max_iter=1000, rtol=1e-8):
    """
    Promax oblique rotation.

    1. Perform Varimax rotation to get orthogonal solution
    2. Raise loadings to a power to create Procrustes target
    3. Solve least-squares for oblique rotation matrix
    4. Column-normalize the oblique rotation

    Returns:
        promax_loadings: (n_features, n_factors) oblique loadings
        R_combined: (n_factors, n_factors) combined rotation matrix
        phi: (n_factors, n_factors) factor correlation matrix
        varimax_loadings: (n_features, n_factors) intermediate Varimax result
    """
    # Step 1: Varimax rotation
    varimax_load, R_varimax = varimax_rotation(loadings, max_iter, rtol)

    if power == 1:
        phi = np.eye(loadings.shape[1])
        return varimax_load, R_varimax, phi, varimax_load

    # Step 2: Create Promax target matrix
    # P_ij = sign(H_ij) * |H_ij|^power
    target = np.sign(varimax_load) * np.abs(varimax_load)**power

    # Step 3: Solve least-squares for oblique rotation
    # H @ R_pro ≈ target  =>  R_pro = (H^T H)^(-1) H^T target
    H = varimax_load
    HtH_inv = inv(H.T @ H)
    R_pro = HtH_inv @ (H.T @ target)

    # Step 4: Normalize columns of R_pro to unit norm
    col_norms = np.sqrt(np.sum(R_pro**2, axis=0))
    R_pro_normalized = R_pro / col_norms[None, :]

    # Step 5: Apply oblique rotation
    promax_load = H @ R_pro_normalized

    # Combined rotation matrix (from original to promax)
    R_combined = R_varimax @ R_pro_normalized

    # Step 6: Factor correlation matrix (phi)
    # phi = (R^{-1}) (R^{-1})^T, normalized to correlation
    R_inv = inv(R_combined)
    C = R_inv @ R_inv.T
    d = np.sqrt(np.diag(C))
    phi = C / np.outer(d, d)

    return promax_load, R_combined, phi, varimax_load


def run_pipeline():
    """Execute the full rotated EOF pipeline."""
    # Load config
    with open('/app/task_config.json') as f:
        config = json.load(f)

    n_modes = config['n_modes']
    n_rotate = config['n_rotate']
    power = config['rotation_power']

    # Load and preprocess data
    data, lats, lons, land_mask = load_data()
    X, valid_mask, temporal_mean, coslat_weights = preprocess(data, lats, land_mask)

    # EOF decomposition
    components, scores, singular_values, exp_var, exp_var_ratio, total_var = \
        eof_svd(X, n_modes)

    # --- Rotation on top n_rotate modes ---
    # Compute loadings: component * sqrt(explained_variance)
    loadings = (components[:n_rotate].T * np.sqrt(exp_var[:n_rotate])[None, :])

    # Varimax criterion before rotation
    vc_before = varimax_criterion(loadings)

    # Promax rotation (returns intermediate Varimax result too)
    rot_loadings, R_combined, phi, varimax_loadings = \
        promax_rotation(loadings, power=power)

    # Varimax criterion after Varimax step (not Promax)
    vc_after = varimax_criterion(varimax_loadings)

    # Rotated explained variance (per mode, from Promax loadings)
    rot_exp_var = np.sum(rot_loadings**2, axis=0)

    # Reorder modes by descending variance
    order = np.argsort(rot_exp_var)[::-1]
    rot_loadings = rot_loadings[:, order]
    rot_exp_var = rot_exp_var[order]
    R_combined = R_combined[:, order]
    phi = phi[np.ix_(order, order)]

    # Rotated components: normalize loadings to unit column norm
    rot_components = (rot_loadings / np.sqrt(rot_exp_var)[None, :]).T

    # Deterministic sign convention for rotated components
    sign_mult = np.ones(n_rotate)
    for i in range(n_rotate):
        max_idx = np.argmax(np.abs(rot_components[i]))
        if rot_components[i, max_idx] < 0:
            sign_mult[i] = -1.0
            rot_components[i] *= -1

    # Rotated scores via inverse-transpose of rotation matrix
    # 1. Normalize original scores by singular values to get U
    U_truncated = scores[:, :n_rotate] / singular_values[None, :n_rotate]
    # 2. For oblique rotation: scores_rot = U @ R^{-T}
    R_invT = inv(R_combined).T
    rot_scores_normalized = U_truncated @ R_invT
    # 3. Scale by pseudo-norms: sqrt(rotated_variance * (N-1))
    n_time = X.shape[0]
    pseudo_norms = np.sqrt(rot_exp_var * (n_time - 1))
    rot_scores = rot_scores_normalized * pseudo_norms[None, :]
    # 4. Apply same sign convention as components
    rot_scores = rot_scores * sign_mult[None, :]

    # Rotated explained variance ratios
    rot_exp_var_ratio = rot_exp_var / total_var

    # --- Save results ---
    out_dir = '/app/results'
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
    run_pipeline()
