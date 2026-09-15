"""Timestamp-based pose association for trajectory evaluation."""

import numpy as np


def associate_by_index(gt_poses, est_poses):
    """Associate poses by sequential index (KITTI-style)."""
    n = min(len(gt_poses), len(est_poses))
    return [gt_poses[i] for i in range(n)], [est_poses[i] for i in range(n)]


def associate_by_timestamp(gt_poses, est_poses, max_diff=0.02):
    """Associate poses by nearest timestamp within tolerance (bijective).

    Each ground-truth pose is matched at most once.
    """
    gt_times = np.array([p[0] for p in gt_poses])
    gt_matched = []
    est_matched = []
    used_gt = set()

    for i in range(len(est_poses)):
        est_t = est_poses[i][0]
        diffs = np.abs(gt_times - est_t)
        sorted_indices = np.argsort(diffs)
        for j in sorted_indices:
            if j in used_gt:
                continue
            if diffs[j] <= max_diff:
                gt_matched.append(gt_poses[int(j)])
                est_matched.append(est_poses[i])
                used_gt.add(int(j))
                break
            else:
                break

    return gt_matched, est_matched
