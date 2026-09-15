"""
Ground truth generation for multi-view homography task.
This file is mounted at /tests/ during verification only — NOT available
to the agent at solve time.

"""
import numpy as np


def _rodrigues(rvec):
    theta = np.linalg.norm(rvec)
    if theta < 1e-12:
        return np.eye(3)
    k = rvec / theta
    K_mat = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
    return np.eye(3) + np.sin(theta) * K_mat + (1 - np.cos(theta)) * (K_mat @ K_mat)


def generate_ground_truth():
    """Reproduce the exact ground truth from the data generation process.

    Returns a dict with keys:
        K, ref_homographies, pairwise_H, gt_inliers,
        gt_rotations_pairwise, poses, rotations
    """
    np.random.seed(20240517)

    K = np.array([[800.0, 0.0, 320.0],
                  [0.0, 800.0, 240.0],
                  [0.0, 0.0, 1.0]])

    grid_x, grid_y = np.meshgrid(np.linspace(-1.5, 1.5, 10),
                                  np.linspace(-1.0, 1.0, 7))
    world_pts_2d = np.column_stack([grid_x.ravel(), grid_y.ravel()])

    poses = [
        (np.array([0.0, 0.0, 0.0]),       np.array([0.0, 0.0, 5.0])),
        (np.array([0.15, 0.25, 0.05]),     np.array([0.5, -0.3, 4.8])),
        (np.array([-0.2, 0.12, -0.08]),    np.array([-0.4, 0.35, 5.3])),
        (np.array([0.1, -0.28, 0.12]),     np.array([0.6, 0.4, 4.5])),
        (np.array([-0.12, -0.18, -0.06]),  np.array([-0.55, -0.15, 5.6])),
    ]

    num_views = len(poses)
    outlier_ratio = 0.15

    homographies = []
    rotations = []
    for rvec, tvec in poses:
        R = _rodrigues(rvec)
        rotations.append(R)
        H = K @ np.column_stack([R[:, 0], R[:, 1], tvec])
        homographies.append(H)

    projected = []
    for H in homographies:
        pts_h = np.column_stack([world_pts_2d, np.ones(len(world_pts_2d))])
        proj = (H @ pts_h.T).T
        proj = proj[:, :2] / proj[:, 2:3]
        projected.append(proj)

    H0_inv = np.linalg.inv(homographies[0])
    ref_homographies = []
    for H in homographies:
        H_ref = H @ H0_inv
        H_ref = H_ref / H_ref[2, 2]
        ref_homographies.append(H_ref)

    pairwise_H = {}
    gt_inliers = {}

    for i in range(num_views):
        for j in range(i + 1, num_views):
            H_ij = homographies[j] @ np.linalg.inv(homographies[i])
            H_ij = H_ij / H_ij[2, 2]
            pair_key = f"{i}-{j}"
            pairwise_H[pair_key] = H_ij

            n_pts = len(world_pts_2d)
            n_outliers = int(n_pts * outlier_ratio)
            outlier_idx = np.random.choice(n_pts, n_outliers, replace=False)
            inlier_mask = np.ones(n_pts, dtype=bool)
            inlier_mask[outlier_idx] = False

            # Consume same random state as data generation
            _ = np.random.randn(n_pts, 2)
            _ = np.random.randn(n_pts, 2)
            _ = np.random.uniform(low=[0, 0], high=[640, 480],
                                   size=(n_outliers, 2))
            shuffle_idx = np.random.permutation(n_pts)
            inlier_mask = inlier_mask[shuffle_idx]
            gt_inliers[pair_key] = inlier_mask

    gt_rotations_pairwise = {}
    for i in range(num_views):
        for j in range(i + 1, num_views):
            R_i = rotations[i]
            R_j = rotations[j]
            R_ij = R_j @ R_i.T
            gt_rotations_pairwise[f"{i}-{j}"] = R_ij

    return {
        "K": K,
        "ref_homographies": ref_homographies,
        "pairwise_H": pairwise_H,
        "gt_inliers": gt_inliers,
        "gt_rotations_pairwise": gt_rotations_pairwise,
        "poses": poses,
        "rotations": rotations,
    }
