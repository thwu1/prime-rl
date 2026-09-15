"""RANSAC-based robust trajectory alignment."""

import numpy as np
from slam_eval.alignment import align_umeyama


def ransac_align(source, target, with_scale=False, threshold=0.2,
                 max_iterations=1000, min_samples=3, seed=42):
    """Robust alignment using RANSAC + Umeyama.

    Iteratively samples small subsets, computes alignment, classifies
    inliers by error threshold, and refines on the best inlier set.

    Returns (R, t, s, inlier_mask).
    """
    n = source.shape[0]
    rng = np.random.RandomState(seed)

    best_count = 0
    best_mask = np.zeros(n, dtype=bool)

    for _ in range(max_iterations):
        idx = rng.choice(n, size=min(min_samples, n), replace=False)
        try:
            R_s, t_s, s_s = align_umeyama(source[idx], target[idx], with_scale)
        except Exception:
            continue

        aligned = s_s * (R_s @ source.T).T + t_s
        errors = np.linalg.norm(target - aligned, axis=1)
        mask = errors < threshold
        count = np.sum(mask)

        if count > best_count:
            best_count = count
            best_mask = mask.copy()

    if best_count >= min_samples:
        R, t, s = align_umeyama(source[best_mask], target[best_mask], with_scale)
    else:
        R, t, s = align_umeyama(source, target, with_scale)
        best_mask = np.ones(n, dtype=bool)

    return R, t, s, best_mask
