"""Trajectory error metrics: ATE and RPE."""

import numpy as np


def compute_ate(gt_positions, aligned_est_positions, scale=1.0):
    """Compute Absolute Trajectory Error statistics.

    Returns dict with rmse, mean, median, std, max, min, num_poses, scale.
    """
    errors = np.linalg.norm(gt_positions - aligned_est_positions, axis=1)
    return {
        'rmse': float(np.sqrt(np.mean(errors ** 2))),
        'mean': float(np.mean(errors)),
        'median': float(np.median(errors)),
        'std': float(np.std(errors)),
        'max': float(np.max(errors)),
        'min': float(np.min(errors)),
        'num_poses': int(len(errors)),
        'scale': float(scale),
    }


def compute_rpe(gt_positions, aligned_est_positions):
    """Compute translational Relative Pose Error.

    Measures the error in relative motion between consecutive poses.
    """
    gt_rel = gt_positions[:-1] - gt_positions[1:]
    est_rel = aligned_est_positions[1:] - aligned_est_positions[:-1]
    rpe = np.linalg.norm(gt_rel - est_rel, axis=1)
    return {
        'rpe_rmse': float(np.sqrt(np.mean(rpe ** 2))),
        'rpe_mean': float(np.mean(rpe)),
        'rpe_median': float(np.median(rpe)),
        'rpe_max': float(np.max(rpe)),
        'rpe_num_pairs': int(len(rpe)),
    }
