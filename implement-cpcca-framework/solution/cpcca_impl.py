"""Continuum Power CCA (CPCCA) framework implementation.

Implements the unified cross-decomposition framework from:
Swenson, E. (2015). Continuum Power CCA: A Unified Approach for Isolating
Coupled Modes. Journal of Climate 28, 1016-1030.

"""

import numpy as np
from numpy.linalg import svd, eigh, norm, solve, pinv


def fractional_matrix_power(C, alpha, regularization=1e-12):
    """Compute C^alpha for symmetric positive semi-definite matrix C.

    Uses eigendecomposition: C = V diag(lam) V^T, so C^a = V diag(lam^a) V^T.
    Eigenvalues are clipped to the regularization floor before exponentiation
    to handle near-singular matrices.
    """
    eigenvalues, eigenvectors = eigh(C)
    eigenvalues = np.maximum(eigenvalues, regularization)
    powered = eigenvalues ** alpha
    return eigenvectors @ np.diag(powered) @ eigenvectors.T


def whiten(X, alpha):
    """Fractional whitening of data matrix X.

    Returns (X_whitened, W) where X_whitened = X @ W and
    W = (X^T X / (n-1))^{(alpha-1)/2}.

    alpha=1 -> exponent=0 -> W=I -> no whitening (MCA)
    alpha=0 -> exponent=-1/2 -> full whitening (CCA)
    """
    n = X.shape[0]
    C = X.T @ X / (n - 1)
    exponent = (alpha - 1.0) / 2.0
    if abs(exponent) < 1e-14:
        return X.copy(), np.eye(C.shape[0])
    W = fractional_matrix_power(C, exponent)
    return X @ W, W


def _fix_signs(U, V):
    """Apply deterministic sign convention: make the largest-magnitude element
    in each column of U positive."""
    max_abs_rows = np.argmax(np.abs(U), axis=0)
    signs = np.sign(U[max_abs_rows, range(U.shape[1])])
    signs[signs == 0] = 1.0
    return U * signs, V * signs


def cpcca(X, Y, n_modes, alpha_x=1.0, alpha_y=1.0):
    """Continuum Power CCA decomposition.

    Whitens X and Y according to their respective alpha parameters,
    computes the cross-covariance of the whitened data, and performs SVD.

    Returns dict with:
        singular_values (k,): in descending order
        Qx (p,k), Qy (q,k): singular vectors in whitened space
        Px (p,k), Py (q,k): components in original feature space (P = W @ Q)
        Rx (n,k), Ry (n,k): scores (R = X_w @ Q)
    """
    n = X.shape[0]

    # Whiten both fields
    X_w, Wx = whiten(X, alpha_x)
    Y_w, Wy = whiten(Y, alpha_y)

    # Cross-covariance of whitened data
    C_xy = X_w.T @ Y_w / (n - 1)

    # SVD of cross-covariance
    U, s, Vt = svd(C_xy, full_matrices=False)
    V = Vt.T

    # Truncate to n_modes
    U_k = U[:, :n_modes]
    s_k = s[:n_modes]
    V_k = V[:, :n_modes]

    # Deterministic sign convention
    U_k, V_k = _fix_signs(U_k, V_k)

    # Singular vectors in whitened space
    Qx = U_k
    Qy = V_k

    # Scores: projection of whitened data onto singular vectors
    Rx = X_w @ Qx
    Ry = Y_w @ Qy

    # Components in original feature space
    Px = Wx @ Qx
    Py = Wy @ Qy

    return {
        'singular_values': s_k,
        'Qx': Qx,
        'Qy': Qy,
        'Px': Px,
        'Py': Py,
        'Rx': Rx,
        'Ry': Ry,
    }


def squared_covariance_fraction(singular_values):
    """Squared covariance fraction: SCF_i = sigma_i^2 / sum(sigma_j^2)."""
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
    """Pearson correlation between columns of X and the other field's scores.

    Returns array of shape (n_features, n_modes).
    """
    return homogeneous_patterns(X, other_scores)


def _varimax(L, max_iter=1000, tol=1e-8):
    """Compute the Varimax rotation matrix for loading matrix L.

    Maximizes the sum of squared column variances (simplicity criterion)
    using the iterative SVD-based algorithm.
    """
    p, k = L.shape
    R = np.eye(k)
    for _ in range(max_iter):
        A = L @ R
        # Varimax criterion gradient
        B = A ** 3 - A * (A ** 2).sum(axis=0) / p
        U_r, _, Vt_r = svd(L.T @ B, full_matrices=False)
        R_new = U_r @ Vt_r
        if np.max(np.abs(R_new - R)) < tol:
            return R_new
        R = R_new
    return R


def promax_rotation(Qx, Qy, singular_values, power=2):
    """Joint Promax rotation of paired singular vectors.

    Forms loadings L_x = Q_x * sqrt(sigma), L_y = Q_y * sqrt(sigma),
    stacks them vertically, and applies rotation:
    - power=1: pure orthogonal Varimax
    - power>1: oblique Promax (Varimax target raised to power, then
      least-squares transformation)

    Returns dict with:
        rotation_matrix (k,k)
        Qx_rot (p,k), Qy_rot (q,k): rotated normalized components
        singular_values_rot (k,): column norms of rotated stacked loadings
    """
    k = len(singular_values)
    sqrt_s = np.sqrt(singular_values)

    # Form loadings and stack
    Lx = Qx * sqrt_s
    Ly = Qy * sqrt_s
    L = np.vstack([Lx, Ly])

    # Step 1: Varimax rotation (orthogonal)
    R_varimax = _varimax(L)

    if power <= 1:
        R_final = R_varimax
    else:
        # Step 2: Promax target matrix
        H = L @ R_varimax
        H_target = np.sign(H) * np.abs(H) ** power

        # Step 3: Least-squares transformation to approximate target
        T = solve(H.T @ H, H.T @ H_target)

        # Normalize columns of T
        T_norms = norm(T, axis=0)
        T /= T_norms

        R_final = R_varimax @ T

    # Apply rotation
    L_rot = L @ R_final
    n_x = Qx.shape[0]
    Lx_rot = L_rot[:n_x]
    Ly_rot = L_rot[n_x:]

    # Singular values = column norms of rotated stacked loadings
    sv_rot = norm(L_rot, axis=0)

    # Sort by descending rotated singular value
    order = np.argsort(sv_rot)[::-1]
    sv_rot = sv_rot[order]
    R_final = R_final[:, order]
    Lx_rot = Lx_rot[:, order]
    Ly_rot = Ly_rot[:, order]

    # Normalized rotated components
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
    """Permutation-based significance test for CPCCA modes.

    Destroys temporal coupling by permuting Y's row (sample) axis,
    generating a null distribution of singular values. Each original
    singular value is tested against the null distribution at the
    corresponding mode index.

    Returns dict with:
        significant (k,): boolean, True if mode is significant
        pvalues (k,): fraction of null SVs >= observed SV
    """
    rng = np.random.RandomState(seed)
    n = X.shape[0]

    # Fit on original data
    original = cpcca(X, Y, n_modes, alpha_x, alpha_y)
    original_sv = original['singular_values']

    # Generate null distribution via permutation
    null_svs = np.zeros((n_bootstraps, n_modes))
    for b in range(n_bootstraps):
        perm = rng.permutation(n)
        Y_perm = Y[perm]
        null_result = cpcca(X, Y_perm, n_modes, alpha_x, alpha_y)
        null_svs[b] = null_result['singular_values']

    # Compute p-values: fraction of null SVs that exceed observed
    pvalues = np.zeros(n_modes)
    for m in range(n_modes):
        pvalues[m] = np.mean(null_svs[:, m] >= original_sv[m])

    significant = pvalues < (1.0 - confidence)

    return {
        'significant': significant,
        'pvalues': pvalues,
    }
