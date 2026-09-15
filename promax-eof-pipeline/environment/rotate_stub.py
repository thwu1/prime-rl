"""Rotation module: Varimax and Promax factor rotation.

This module must provide orthogonal Varimax and oblique Promax rotation
of factor analysis loadings. Called by run_analysis.py.

"""
import numpy as np
from scipy.linalg import svd, inv


def varimax_criterion(loadings):
    """
    Compute the Varimax criterion: sum of column variances of squared
    loadings. Higher values indicate simpler structure.

    V = sum_j [ mean(L_j^4) - mean(L_j^2)^2 ]

    Parameters
    ----------
    loadings : ndarray, shape (n_features, n_factors)

    Returns
    -------
    float
    """
    L2 = loadings ** 2
    return np.sum(np.mean(L2 ** 2, axis=0) - np.mean(L2, axis=0) ** 2)


def varimax_rotation(loadings, max_iter=1000, rtol=1e-8):
    """
    Orthogonal Varimax rotation with Kaiser normalization.

    Implements the SVD-based analytic iteration (Sherin, 1966):

    1. Kaiser-normalize: divide each row by its communality
       (sqrt of sum of squared loadings in that row, floored at 1e-12)
    2. Initialize R = I (identity)
    3. Iterate until convergence:
       a. B = A @ R  (current rotated, Kaiser-normalized loadings)
       b. Compute gradient G = A^T @ (B^3 - B @ diag(colmeans(B^2)))
       c. SVD(G) = P S Q^T; update R = P @ Q^T
       d. Convergence when relative change in sum(S) < rtol
    4. Undo Kaiser normalization: rotated = (A @ R) * communalities

    Parameters
    ----------
    loadings : ndarray, shape (n_features, n_factors)
        Loading matrix to rotate.
    max_iter : int
        Maximum number of iterations.
    rtol : float
        Relative convergence tolerance.

    Returns
    -------
    rotated_loadings : ndarray, shape (n_features, n_factors)
    R : ndarray, shape (n_factors, n_factors)
        Orthogonal rotation matrix.
    """
    raise NotImplementedError(
        "varimax_rotation: implementation required"
    )


def promax_rotation(loadings, power=2, max_iter=1000, rtol=1e-8):
    """
    Oblique Promax rotation.

    Steps:
    1. Compute Varimax rotation of loadings -> (H, R_varimax)
    2. If power == 1, return Varimax result with phi = identity
    3. Construct Promax target matrix:
       T_ij = sign(H_ij) * |H_ij|^power
       (sign-preserving power to maintain loading polarity)
    4. Least-squares oblique rotation:
       R_pro = (H^T H)^{-1} H^T T
    5. Column-normalize R_pro (divide each column by its L2 norm)
    6. Promax loadings = H @ R_pro_normalized
    7. Combined rotation matrix:
       R_combined = R_varimax @ R_pro_normalized
    8. Factor correlation matrix phi:
       R_inv = inv(R_combined)
       C = R_inv @ R_inv^T
       phi_ij = C_ij / sqrt(C_ii * C_jj)

    Parameters
    ----------
    loadings : ndarray, shape (n_features, n_factors)
    power : int
        Promax power parameter (typically 2-4).
    max_iter : int
    rtol : float

    Returns
    -------
    promax_loadings : ndarray, shape (n_features, n_factors)
    R_combined : ndarray, shape (n_factors, n_factors)
    phi : ndarray, shape (n_factors, n_factors)
        Factor correlation matrix.
    varimax_loadings : ndarray, shape (n_features, n_factors)
    """
    raise NotImplementedError(
        "promax_rotation: implementation required"
    )
