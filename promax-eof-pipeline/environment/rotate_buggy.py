"""Rotation module: Varimax and Promax factor rotation."""
import numpy as np
from scipy.linalg import svd, inv


def varimax_criterion(loadings):
    """
    Compute the Varimax criterion: sum of column variances of squared
    loadings. Higher values indicate simpler structure.
    """
    L2 = loadings ** 2
    return np.sum(np.mean(L2 ** 2, axis=0) - np.mean(L2, axis=0) ** 2)


def varimax_rotation(loadings, max_iter=1000, rtol=1e-8):
    """
    Orthogonal Varimax rotation with Kaiser normalization.

    Parameters
    ----------
    loadings : ndarray, shape (n_features, n_factors)
    max_iter : int
    rtol : float

    Returns
    -------
    rotated_loadings : ndarray, shape (n_features, n_factors)
    R : ndarray, shape (n_factors, n_factors)
    """
    n, k = loadings.shape

    # Kaiser normalization: normalize rows to unit length
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


def promax_rotation(loadings, power=2, max_iter=1000, rtol=1e-8):
    """
    Oblique Promax rotation.

    Parameters
    ----------
    loadings : ndarray, shape (n_features, n_factors)
    power : int
    max_iter : int
    rtol : float

    Returns
    -------
    promax_loadings : ndarray, shape (n_features, n_factors)
    R_combined : ndarray, shape (n_factors, n_factors)
    phi : ndarray, shape (n_factors, n_factors)
    varimax_loadings : ndarray, shape (n_features, n_factors)
    """
    varimax_load, R_varimax = varimax_rotation(loadings, max_iter, rtol)

    if power == 1:
        phi = np.eye(loadings.shape[1])
        return varimax_load, R_varimax, phi, varimax_load

    # Construct Promax target matrix
    target = varimax_load ** power

    # Least-squares oblique rotation
    H = varimax_load
    HtH_inv = inv(H.T @ H)
    R_pro = HtH_inv @ (H.T @ target)

    # Column-normalize
    col_norms = np.sqrt(np.sum(R_pro ** 2, axis=0))
    R_pro_normalized = R_pro / col_norms[None, :]

    # Apply oblique rotation
    promax_load = H @ R_pro_normalized

    # Combined rotation matrix
    R_combined = R_varimax @ R_pro_normalized

    # Factor correlation matrix (phi)
    R_inv = inv(R_combined)
    C = R_inv @ R_inv.T
    d_diag = np.sqrt(np.diag(C))
    phi = C / np.outer(d_diag, d_diag)

    return promax_load, R_combined, phi, varimax_load
