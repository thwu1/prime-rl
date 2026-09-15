"""SVD-based trajectory alignment using the Umeyama method.

Computes the optimal rotation, translation, and optionally scale
that aligns a source point set to a target point set.
"""

import numpy as np


def align_umeyama(source, target, with_scale=False):
    """Align source to target via least-squares: target ~ s * R @ source + t.

    Parameters:
        source: (N, 3) estimated positions
        target: (N, 3) ground truth positions
        with_scale: True for Sim(3), False for SE(3) (s=1.0)

    Returns:
        R: (3,3) rotation, t: (3,) translation, s: float scale
    """
    assert source.shape == target.shape
    n, dim = source.shape

    mu_s = source.mean(axis=0)
    mu_t = target.mean(axis=0)

    src_c = source - mu_s
    tgt_c = target - mu_t

    W = src_c.T @ tgt_c / n
    U, D, Vt = np.linalg.svd(W)

    S = np.eye(dim)
    if np.linalg.det(U) * np.linalg.det(Vt) < 0:
        S[dim - 1, dim - 1] = -1

    R = U @ S @ Vt

    if with_scale:
        var = np.sum(tgt_c ** 2) / n
        s = np.trace(np.diag(D) @ S) / var
    else:
        s = 1.0

    t = mu_t - s * R @ mu_s
    return R, t, s
