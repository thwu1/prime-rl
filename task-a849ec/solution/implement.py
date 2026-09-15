#!/usr/bin/env python3
"""Implement the complete SLAM trajectory evaluation pipeline.

Creates all required Python modules under /app/slam_eval/ based on the
mathematical specification at /app/spec.md.
"""
import os


def write_module(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write(content)


def create_parsers():
    write_module('/app/slam_eval/parsers.py', '''\
"""Trajectory file parsers for KITTI, TUM, and EuRoC benchmark formats.

Each parser returns a list of (timestamp_or_index, position_xyz, rotation_3x3) tuples.
"""
import csv
import numpy as np


def quaternion_to_rotation_matrix(qx, qy, qz, qw):
    """Convert scalar-last quaternion (qx, qy, qz, qw) to 3x3 rotation matrix."""
    n = np.sqrt(qx**2 + qy**2 + qz**2 + qw**2)
    qx, qy, qz, qw = qx / n, qy / n, qz / n, qw / n
    return np.array([
        [1 - 2*(qy**2 + qz**2), 2*(qx*qy - qz*qw), 2*(qx*qz + qy*qw)],
        [2*(qx*qy + qz*qw), 1 - 2*(qx**2 + qz**2), 2*(qy*qz - qx*qw)],
        [2*(qx*qz - qy*qw), 2*(qy*qz + qx*qw), 1 - 2*(qx**2 + qy**2)]
    ])


def parse_kitti(filepath):
    """Parse KITTI trajectory: 12 floats per line, row-major 3x4 [R|t]."""
    poses = []
    with open(filepath) as f:
        for idx, line in enumerate(f):
            vals = list(map(float, line.strip().split()))
            if len(vals) != 12:
                continue
            R = np.array([
                [vals[0], vals[1], vals[2]],
                [vals[4], vals[5], vals[6]],
                [vals[8], vals[9], vals[10]]
            ])
            t = np.array([vals[3], vals[7], vals[11]])
            poses.append((float(idx), t, R))
    return poses


def parse_tum(filepath):
    """Parse TUM trajectory: timestamp tx ty tz qx qy qz qw."""
    poses = []
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split()
            if len(parts) < 8:
                continue
            ts = float(parts[0])
            pos = np.array([float(parts[1]), float(parts[2]), float(parts[3])])
            R = quaternion_to_rotation_matrix(
                float(parts[4]), float(parts[5]), float(parts[6]), float(parts[7])
            )
            poses.append((ts, pos, R))
    return poses


def parse_euroc_gt(filepath):
    """Parse EuRoC ground truth CSV.

    Timestamps are in nanoseconds (converted to seconds).
    Quaternion order is scalar-first: qw, qx, qy, qz.
    """
    poses = []
    with open(filepath) as f:
        reader = csv.reader(f)
        for row in reader:
            if not row or row[0].strip().startswith('#'):
                continue
            ts = float(row[0]) * 1e-9
            px, py, pz = float(row[1]), float(row[2]), float(row[3])
            qw, qx, qy, qz = float(row[4]), float(row[5]), float(row[6]), float(row[7])
            R = quaternion_to_rotation_matrix(qx, qy, qz, qw)
            poses.append((ts, np.array([px, py, pz]), R))
    return poses
''')


def create_association():
    write_module('/app/slam_eval/association.py', '''\
"""Pose association: index-based (KITTI) and timestamp-based (TUM/EuRoC)."""
import numpy as np


def associate_by_index(gt_poses, est_poses):
    """Associate poses by sequential index (KITTI-style)."""
    n = min(len(gt_poses), len(est_poses))
    return [gt_poses[i] for i in range(n)], [est_poses[i] for i in range(n)]


def associate_by_timestamp(gt_poses, est_poses, max_diff=0.02):
    """Bijective nearest-timestamp association within tolerance.

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
''')


def create_alignment():
    write_module('/app/slam_eval/alignment.py', '''\
"""SVD-based trajectory alignment using the Umeyama method.

Computes optimal rotation, translation, and optionally scale
that aligns a source point set to a target point set.
"""
import numpy as np


def align_umeyama(source, target, with_scale=False):
    """Align source to target: target ~ s * R @ source + t.

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

    # Cross-covariance: W = T_c^T @ S_c / N
    W = tgt_c.T @ src_c / n
    U, D, Vt = np.linalg.svd(W)

    # Reflection correction
    S = np.eye(dim)
    if np.linalg.det(U) * np.linalg.det(Vt) < 0:
        S[dim - 1, dim - 1] = -1

    R = U @ S @ Vt

    if with_scale:
        # Scale uses SOURCE variance: sigma_S^2 = ||S_c||_F^2 / N
        var = np.sum(src_c ** 2) / n
        s = np.trace(np.diag(D) @ S) / var
    else:
        s = 1.0

    t = mu_t - s * R @ mu_s
    return R, t, s
''')


def create_robust():
    write_module('/app/slam_eval/robust.py', '''\
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
''')


def create_metrics():
    write_module('/app/slam_eval/metrics.py', '''\
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

    Uses forward differences: delta[i] = pos[i+1] - pos[i].
    """
    gt_rel = gt_positions[1:] - gt_positions[:-1]
    est_rel = aligned_est_positions[1:] - aligned_est_positions[:-1]
    rpe = np.linalg.norm(gt_rel - est_rel, axis=1)
    return {
        'rpe_rmse': float(np.sqrt(np.mean(rpe ** 2))),
        'rpe_mean': float(np.mean(rpe)),
        'rpe_median': float(np.median(rpe)),
        'rpe_max': float(np.max(rpe)),
        'rpe_num_pairs': int(len(rpe)),
    }
''')


def create_pipeline():
    write_module('/app/slam_eval/pipeline.py', '''\
#!/usr/bin/env python3
"""SLAM trajectory evaluation pipeline.

Evaluates estimated camera trajectories against ground truth.
Supports KITTI, TUM, and EuRoC formats with SE(3)/Sim(3) alignment,
optional RANSAC robust alignment, and ATE/RPE metrics.
"""
import argparse
import json
import os
import sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from slam_eval.parsers import parse_kitti, parse_tum, parse_euroc_gt
from slam_eval.association import associate_by_index, associate_by_timestamp
from slam_eval.alignment import align_umeyama
from slam_eval.robust import ransac_align
from slam_eval.metrics import compute_ate, compute_rpe


def evaluate(fmt, gt_path, est_path, output_path, align_mode='se3',
             max_diff=0.02, robust=False, ransac_threshold=0.2,
             ransac_iterations=1000, ransac_seed=42, compute_rpe_flag=False):
    """Run full trajectory evaluation pipeline."""

    # Parse trajectories
    if fmt == 'kitti':
        gt_poses = parse_kitti(gt_path)
        est_poses = parse_kitti(est_path)
    elif fmt == 'tum':
        gt_poses = parse_tum(gt_path)
        est_poses = parse_tum(est_path)
    elif fmt == 'euroc':
        gt_poses = parse_euroc_gt(gt_path)
        est_poses = parse_tum(est_path)
    else:
        raise ValueError(f'Unknown format: {fmt}')

    # Associate poses
    if fmt == 'kitti':
        gt_matched, est_matched = associate_by_index(gt_poses, est_poses)
    else:
        gt_matched, est_matched = associate_by_timestamp(
            gt_poses, est_poses, max_diff
        )

    if len(gt_matched) == 0:
        print('ERROR: No pose associations found.', file=sys.stderr)
        sys.exit(1)

    gt_pos = np.array([p[1] for p in gt_matched])
    est_pos = np.array([p[1] for p in est_matched])

    with_scale = (align_mode == 'sim3')

    # Alignment
    if robust:
        R, t, s, inlier_mask = ransac_align(
            est_pos, gt_pos, with_scale,
            ransac_threshold, ransac_iterations, seed=ransac_seed
        )
        # Evaluate on inlier poses only
        gt_eval = gt_pos[inlier_mask]
        est_eval = est_pos[inlier_mask]
    else:
        R, t, s = align_umeyama(est_pos, gt_pos, with_scale)
        gt_eval = gt_pos
        est_eval = est_pos
        inlier_mask = None

    # Apply alignment and compute metrics
    aligned = (s * (R @ est_eval.T) + t.reshape(3, 1)).T

    metrics = compute_ate(gt_eval, aligned, s)

    if robust and inlier_mask is not None:
        metrics['num_inliers'] = int(np.sum(inlier_mask))

    if compute_rpe_flag:
        rpe_metrics = compute_rpe(gt_eval, aligned)
        metrics.update(rpe_metrics)

    # Write output
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, 'w') as f:
        json.dump(metrics, f, indent=2)

    return metrics


def main():
    parser = argparse.ArgumentParser(description='SLAM trajectory evaluation')
    parser.add_argument('--format', required=True, choices=['kitti', 'tum', 'euroc'])
    parser.add_argument('--gt', required=True)
    parser.add_argument('--est', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--align', default='se3', choices=['se3', 'sim3'])
    parser.add_argument('--max_diff', type=float, default=0.02)
    parser.add_argument('--robust', action='store_true')
    parser.add_argument('--ransac_threshold', type=float, default=0.2)
    parser.add_argument('--ransac_iterations', type=int, default=1000)
    parser.add_argument('--ransac_seed', type=int, default=42)
    parser.add_argument('--rpe', action='store_true')
    args = parser.parse_args()

    metrics = evaluate(
        args.format, args.gt, args.est, args.output, args.align,
        args.max_diff, args.robust, args.ransac_threshold,
        args.ransac_iterations, args.ransac_seed, args.rpe
    )
    print(json.dumps(metrics, indent=2))


if __name__ == '__main__':
    main()
''')


def create_init():
    write_module('/app/slam_eval/__init__.py', '')


if __name__ == '__main__':
    print("Implementing SLAM trajectory evaluation pipeline...")
    create_init()
    create_parsers()
    create_association()
    create_alignment()
    create_robust()
    create_metrics()
    create_pipeline()
    print("Pipeline implementation complete.")
