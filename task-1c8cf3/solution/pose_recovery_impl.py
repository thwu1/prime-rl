
"""Pose recovery from corrected 3D point correspondences.

Uses SVD-based Procrustes analysis (Arun's method) to recover the relative
rotation and translation from 3D point sets reconstructed with corrected depths.
"""

import numpy as np
from .types import AffineParams, PoseResult


def find_rotation(X1: np.ndarray, X2: np.ndarray) -> tuple:
    """Recover rotation and translation via SVD-based Procrustes analysis.

    Solves for R, t minimizing ||X2 - (R @ X1^T)^T - t||^2.
    """
    m1 = np.mean(X1, axis=0)
    m2 = np.mean(X2, axis=0)
    X1c = X1 - m1
    X2c = X2 - m2

    H = X2c.T @ X1c
    U, S, Vt = np.linalg.svd(H)

    # Ensure proper rotation (det = +1)
    d = np.linalg.det(U @ Vt)
    D = np.diag([1.0, 1.0, d])
    R = U @ D @ Vt

    t = m2 - R @ m1

    return R, t


def recover_pose(x1: np.ndarray, x2: np.ndarray,
                 d1: np.ndarray, d2: np.ndarray,
                 params: AffineParams) -> PoseResult:
    """Recover full pose from bearing vectors, depths, and affine parameters."""
    # Correct depths using affine parameters
    d1_corrected = params.a1 * d1 + params.b1
    d2_corrected = params.a2 * d2 + params.b2

    # Reconstruct 3D points
    X1 = x1 * d1_corrected[:, None]
    X2 = x2 * d2_corrected[:, None]

    # Recover rotation and translation
    R, t = find_rotation(X1, X2)

    return PoseResult(R=R, t=t, affine=params)
