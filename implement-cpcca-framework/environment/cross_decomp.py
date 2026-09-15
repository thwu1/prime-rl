"""Cross-field decomposition module for paired data analysis.

Provides parameterized decomposition of coupled data fields with
support for variable whitening, component rotation, and significance testing.

"""

import numpy as np
from numpy.linalg import svd, eigh, norm, solve
import h5py


def load_fields(path='/app/data/fields.h5'):
    """Load paired data fields from HDF5 file."""
    with h5py.File(path, 'r') as f:
        X = np.array(f['observations']['X'])
        Y = np.array(f['observations']['Y'])
    return X, Y


def fractional_matrix_power(C, alpha, regularization=1e-12):
    """Compute C^alpha for symmetric positive semi-definite matrix C.

    Uses eigendecomposition with regularization floor for numerical stability.
    Eigenvalues are clipped to the regularization floor before exponentiation.
    """
    eigenvalues, eigenvectors = eigh(C)
    eigenvalues = np.maximum(eigenvalues, regularization)
    powered = eigenvalues ** alpha
    return eigenvectors @ np.diag(powered) @ eigenvectors.T


def whiten(X, alpha):
    """Apply fractional whitening controlled by alpha parameter.

    alpha=1: no whitening (identity transform)
    alpha=0: full whitening (identity covariance)
    Intermediate values interpolate between these extremes.
    """
    n = X.shape[0]
    C = X.T @ X / (n - 1)
    exponent = alpha / 2.0
    if abs(exponent) < 1e-14:
        return X.copy(), np.eye(C.shape[0])
    W = fractional_matrix_power(C, exponent)
    return X @ W, W


def _fix_signs(U, V):
    """Apply deterministic sign convention: largest-magnitude element positive."""
    max_abs_rows = np.argmax(np.abs(U), axis=0)
    signs = np.sign(U[max_abs_rows, range(U.shape[1])])
    signs[signs == 0] = 1.0
    return U * signs, V * signs


def cpcca(X, Y, n_modes, alpha_x=1.0, alpha_y=1.0):
    """Parameterized cross-decomposition of paired data fields.

    Applies whitening controlled by alpha_x and alpha_y, computes
    cross-covariance of whitened data, and extracts coupled modes via SVD.

    Returns dict with keys:
        singular_values (k,): in descending order
        Qx (p,k), Qy (q,k): singular vectors in whitened space
        Px (p,k), Py (q,k): components in original feature space
        Rx (n,k), Ry (n,k): scores
    """
    n = X.shape[0]

    X_w, Wx = whiten(X, alpha_x)
    Y_w, Wy = whiten(Y, alpha_y)

    C_xy = X_w.T @ Y_w / n

    U, s, Vt = svd(C_xy, full_matrices=False)
    V = Vt.T

    U_k = U[:, :n_modes]
    s_k = s[:n_modes]
    V_k = V[:, :n_modes]

    U_k, V_k = _fix_signs(U_k, V_k)

    Qx = U_k
    Qy = V_k

    Rx = X @ Qx
    Ry = Y @ Qy

    Px = Wx @ Qx
    Py = Wy @ Qy

    return {
        'singular_values': s_k,
        'Qx': Qx, 'Qy': Qy,
        'Px': Px, 'Py': Py,
        'Rx': Rx, 'Ry': Ry,
    }


def squared_covariance_fraction(singular_values):
    """Fraction of squared covariance explained by each mode."""
    sc = singular_values ** 2
    return sc / sc.sum()


def homogeneous_patterns(X, scores):
    """Pearson correlation between each column of X and each column of scores.

    Returns array of shape (n_features, n_modes).
    """
    n = X.shape[0]
    X_c = X - X.mean(axis=0)
    S_c = scores - scores.mean(axis=0)
    X_std = X_c.std(axis=0, ddof=1)
    S_std = S_c.std(axis=0, ddof=1)
    corr = (X_c.T @ S_c) / (n - 1)
    corr /= np.outer(X_std, S_std)
    return corr


def heterogeneous_patterns(X, other_scores):
    """Correlation between each column of X and the other field's scores.

    Returns array of shape (n_features, n_modes).
    """
    return homogeneous_patterns(other_scores, X)


def _varimax(L, max_iter=1000, tol=1e-8):
    """Compute Varimax rotation matrix for loading matrix L.

    Maximizes simplicity of loading structure via iterative SVD-based
    optimization of the rotation matrix.
    """
    p, k = L.shape
    R = np.eye(k)
    for _ in range(max_iter):
        A = L @ R
        B = A ** 3 - A * (A ** 2).sum(axis=0) / p
        U_r, _, Vt_r = svd(L.T @ B, full_matrices=False)
        R_new = U_r @ Vt_r
        if np.max(np.abs(R_new - R)) < tol:
            return R_new
        R = R_new
    return R


def promax_rotation(Qx, Qy, singular_values, power=2):
    """Joint rotation of paired singular vectors.

    power=1: orthogonal rotation only
    power>1: oblique rotation using orthogonal solution as target

    Returns dict with keys:
        rotation_matrix (k,k)
        Qx_rot (p,k), Qy_rot (q,k): rotated components
        singular_values_rot (k,): column norms in descending order
    """
    k = len(singular_values)
    sqrt_s = np.sqrt(singular_values)

    Lx = Qx * sqrt_s
    Ly = Qy * sqrt_s
    L = np.vstack([Lx, Ly])

    R_varimax = _varimax(L)

    if power <= 1:
        R_final = R_varimax
    else:
        H = L @ R_varimax
        H_target = np.sign(H) * np.abs(H) ** power
        T = solve(H.T @ H, H.T @ H_target)
        T_norms = norm(T, axis=0)
        T /= T_norms
        R_final = R_varimax @ T

    L_rot = L @ R_final
    n_x = Qx.shape[0]
    Lx_rot = L_rot[:n_x]
    Ly_rot = L_rot[n_x:]

    sv_rot = norm(L_rot, axis=0)
    order = np.argsort(sv_rot)[::-1]
    sv_rot = sv_rot[order]
    R_final = R_final[:, order]
    Lx_rot = Lx_rot[:, order]
    Ly_rot = Ly_rot[:, order]

    Qx_rot = Lx_rot / sv_rot
    Qy_rot = Ly_rot / sv_rot

    return {
        'rotation_matrix': R_final,
        'Qx_rot': Qx_rot,
        'Qy_rot': Qy_rot,
        'singular_values_rot': sv_rot,
    }


def bootstrap_significance(X, Y, n_modes, alpha_x, alpha_y,
                           n_bootstraps=100, confidence=0.95, seed=42):
    """Permutation-based significance test for decomposition modes.

    Generates null distribution by destroying temporal coupling between
    fields, then compares observed values against the null.

    Returns dict with keys:
        significant (k,): boolean array
        pvalues (k,): fraction of null values >= observed
    """
    rng = np.random.RandomState(seed)
    n = X.shape[0]

    original = cpcca(X, Y, n_modes, alpha_x, alpha_y)
    original_sv = original['singular_values']

    null_svs = np.zeros((n_bootstraps, n_modes))
    for b in range(n_bootstraps):
        perm = rng.permutation(Y.shape[1])
        Y_perm = Y[:, perm]
        null_result = cpcca(X, Y_perm, n_modes, alpha_x, alpha_y)
        null_svs[b] = null_result['singular_values']

    pvalues = np.zeros(n_modes)
    for m in range(n_modes):
        pvalues[m] = np.mean(null_svs[:, m] >= original_sv[m])

    significant = pvalues < (1.0 - confidence)

    return {
        'significant': significant,
        'pvalues': pvalues,
    }
