
"""Synthetic data generation for affine-depth relative pose estimation."""

import numpy as np


def random_rotation(rng=None):
    """Generate a random proper rotation matrix via QR decomposition."""
    if rng is None:
        rng = np.random.default_rng()
    M = rng.standard_normal((3, 3))
    Q, R_ = np.linalg.qr(M)
    Q = Q * np.linalg.det(Q)  # ensure det = +1
    return Q


def generate_correspondences(n_points=3, seed=42):
    """Generate synthetic point correspondences with known affine depth corruption.

    Creates a rigid 3D scene viewed from two cameras, applies known affine
    transformations to the depths, and returns the corrupted observations
    along with ground truth parameters.

    Args:
        n_points: Number of point correspondences to generate.
        seed: Random seed for reproducibility.

    Returns:
        x1: (n_points, 3) bearing vectors in view 1 (last column = 1)
        x2: (n_points, 3) bearing vectors in view 2 (last column = 1)
        d1: (n_points,) predicted (corrupted) depths in view 1
        d2: (n_points,) predicted (corrupted) depths in view 2
        gt: dict with ground truth parameters including:
            R, t: true relative pose
            a1, b1, a2, b2: true affine parameters
            a1_norm, b1_norm, a2_norm, b2_norm: normalized affine parameters (a1_norm=1)
    """
    np.random.seed(seed)

    # Generate bearing vectors and positive true depths
    while True:
        x1 = np.c_[np.random.randn(n_points, 2), np.ones((n_points,))]
        d1_gt = 1.0 + 5 * np.random.rand(n_points)
        X = x1 * d1_gt[:, None]

        R = np.linalg.qr(np.random.randn(3, 3))[0]
        R = R * np.linalg.det(R)
        t = np.random.randn(3)
        X2 = X @ R.T + t
        d2_gt = X2[:, 2]
        x2 = X2 / d2_gt[:, None]

        if np.all(d2_gt > 0):
            break

    # Apply affine corruption: d_true = a * d_predicted + b
    a1_gt = np.random.rand() + 0.5
    b1_gt = np.random.randn()
    a2_gt = np.random.rand() + 0.5
    b2_gt = np.random.randn()

    d1 = (d1_gt - b1_gt) / a1_gt
    d2 = (d2_gt - b2_gt) / a2_gt

    gt = {
        'R': R, 't': t,
        'a1': a1_gt, 'b1': b1_gt,
        'a2': a2_gt, 'b2': b2_gt,
        'a1_norm': 1.0,
        'b1_norm': b1_gt / a1_gt,
        'a2_norm': a2_gt / a1_gt,
        'b2_norm': b2_gt / a1_gt,
    }

    return x1, x2, d1, d2, gt


def generate_correspondences_with_outliers(n_inliers=20, n_outliers=8, seed=42):
    """Generate correspondences with outlier contamination.

    Inliers are consistent with a single affine model and rigid pose.
    Outliers have random bearing vectors and depths.

    Args:
        n_inliers: Number of inlier correspondences.
        n_outliers: Number of outlier correspondences.
        seed: Random seed.

    Returns:
        Same as generate_correspondences, plus gt['inlier_mask'].
    """
    x1_in, x2_in, d1_in, d2_in, gt = generate_correspondences(n_inliers, seed)

    np.random.seed(seed + 1000)
    x1_out = np.c_[np.random.randn(n_outliers, 2), np.ones((n_outliers,))]
    x2_out = np.c_[np.random.randn(n_outliers, 2), np.ones((n_outliers,))]
    d1_out = np.random.rand(n_outliers) * 10
    d2_out = np.random.rand(n_outliers) * 10

    x1 = np.vstack([x1_in, x1_out])
    x2 = np.vstack([x2_in, x2_out])
    d1 = np.concatenate([d1_in, d1_out])
    d2 = np.concatenate([d2_in, d2_out])

    gt['inlier_mask'] = np.array([True] * n_inliers + [False] * n_outliers)

    return x1, x2, d1, d2, gt
