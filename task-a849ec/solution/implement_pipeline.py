#!/usr/bin/env python3
"""Implement all SLAM evaluation pipeline modules from stubs.

Writes complete implementations to /app/slam_eval/ replacing the stub files.
Each module is implemented according to the specification in /app/spec.md.
"""

import os


def write_file(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write(content)
    print(f"  Wrote {path}")


# ============================================================
# parsers.py — All three format parsers
# ============================================================
PARSERS_PY = '''\
"""Trajectory file parsers for KITTI, TUM, and EuRoC formats."""
import csv
import numpy as np


def quaternion_to_rotation_matrix(qx, qy, qz, qw):
    """Convert Hamilton quaternion (scalar-last: qx, qy, qz, qw) to 3x3 rotation matrix."""
    n = np.sqrt(qx**2 + qy**2 + qz**2 + qw**2)
    qx, qy, qz, qw = qx / n, qy / n, qz / n, qw / n
    return np.array([
        [1 - 2*(qy**2 + qz**2), 2*(qx*qy - qz*qw), 2*(qx*qz + qy*qw)],
        [2*(qx*qy + qz*qw), 1 - 2*(qx**2 + qz**2), 2*(qy*qz - qx*qw)],
        [2*(qx*qz - qy*qw), 2*(qy*qz + qx*qw), 1 - 2*(qx**2 + qy**2)]
    ])


def parse_kitti(filepath):
    """Parse KITTI format: 12 floats per line (row-major 3x4 [R|t])."""
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
    """Parse TUM format: timestamp tx ty tz qx qy qz qw (scalar-last)."""
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
    Timestamps in nanoseconds -> convert to seconds.
    Quaternion order: scalar-FIRST (qw, qx, qy, qz).
    """
    poses = []
    with open(filepath) as f:
        reader = csv.reader(f)
        for row in reader:
            if not row or row[0].strip().startswith('#'):
                continue
            ts_ns = float(row[0])
            ts_s = ts_ns * 1e-9
            px, py, pz = float(row[1]), float(row[2]), float(row[3])
            # EuRoC: qw, qx, qy, qz (scalar-first) -> reorder for our function
            qw, qx, qy, qz = float(row[4]), float(row[5]), float(row[6]), float(row[7])
            R = quaternion_to_rotation_matrix(qx, qy, qz, qw)
            poses.append((ts_s, np.array([px, py, pz]), R))
    return poses
'''


# ============================================================
# association.py — Index-based and timestamp-based association
# ============================================================
ASSOCIATION_PY = '''\
"""Pose association for trajectory evaluation."""
import numpy as np


def associate_by_index(gt_poses, est_poses):
    """Associate by sequential index (KITTI)."""
    n = min(len(gt_poses), len(est_poses))
    return [gt_poses[i] for i in range(n)], [est_poses[i] for i in range(n)]


def associate_by_timestamp(gt_poses, est_poses, max_diff=0.02):
    """Associate by nearest timestamp within max_diff (bijective)."""
    gt_times = np.array([p[0] for p in gt_poses])
    est_times = np.array([p[0] for p in est_poses])

    gt_matched = []
    est_matched = []
    used_gt = set()

    for i, est_t in enumerate(est_times):
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
'''


# ============================================================
# alignment.py — Umeyama SVD alignment
# ============================================================
ALIGNMENT_PY = '''\
"""SVD-based trajectory alignment using the Umeyama method."""
import numpy as np


def align_umeyama(source, target, with_scale=False):
    """Align source to target: target ~ s * R @ source + t.

    source: (N,3) estimated positions
    target: (N,3) ground truth positions
    """
    assert source.shape == target.shape
    n, dim = source.shape

    mu_s = source.mean(axis=0)
    mu_t = target.mean(axis=0)

    src_c = source - mu_s
    tgt_c = target - mu_t

    W = tgt_c.T @ src_c / n
    U, D, Vt = np.linalg.svd(W)

    S = np.eye(dim)
    if np.linalg.det(U) * np.linalg.det(Vt) < 0:
        S[dim - 1, dim - 1] = -1

    R = U @ S @ Vt

    if with_scale:
        var_src = np.sum(src_c ** 2) / n
        s = np.trace(np.diag(D) @ S) / var_src
    else:
        s = 1.0

    t = mu_t - s * R @ mu_s
    return R, t, s
'''


# ============================================================
# robust.py — RANSAC-based robust alignment
# ============================================================
ROBUST_PY = '''\
"""RANSAC-based robust trajectory alignment."""
import numpy as np
from slam_eval.alignment import align_umeyama


def ransac_align(source, target, with_scale=False, threshold=0.2,
                 max_iterations=1000, min_samples=3, seed=42):
    """Robust alignment using RANSAC + Umeyama.

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
'''


# ============================================================
# metrics.py — ATE and RPE computation
# ============================================================
METRICS_PY = '''\
"""Trajectory error metrics: ATE and RPE."""
import numpy as np


def compute_ate(gt_positions, aligned_est_positions, scale=1.0):
    """Absolute Trajectory Error metrics."""
    errors = np.linalg.norm(gt_positions - aligned_est_positions, axis=1)
    return {
        "rmse": float(np.sqrt(np.mean(errors ** 2))),
        "mean": float(np.mean(errors)),
        "median": float(np.median(errors)),
        "std": float(np.std(errors)),
        "max": float(np.max(errors)),
        "min": float(np.min(errors)),
        "num_poses": int(len(errors)),
        "scale": float(scale),
    }


def compute_rpe(gt_positions, aligned_est_positions):
    """Translational Relative Pose Error metrics."""
    gt_d = gt_positions[1:] - gt_positions[:-1]
    est_d = aligned_est_positions[1:] - aligned_est_positions[:-1]
    rpe = np.linalg.norm(gt_d - est_d, axis=1)
    return {
        "rpe_rmse": float(np.sqrt(np.mean(rpe ** 2))),
        "rpe_mean": float(np.mean(rpe)),
        "rpe_median": float(np.median(rpe)),
        "rpe_max": float(np.max(rpe)),
        "rpe_num_pairs": int(len(rpe)),
    }
'''


# ============================================================
# pipeline.py — Main CLI pipeline
# ============================================================
PIPELINE_PY = '''\
#!/usr/bin/env python3
"""SLAM trajectory evaluation pipeline."""
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


def evaluate(fmt, gt_path, est_path, output_path, align_mode="se3",
             max_diff=0.02, robust=False, ransac_threshold=0.2,
             ransac_iterations=1000, ransac_seed=42, compute_rpe_flag=False):
    """Run full trajectory evaluation pipeline."""

    # Parse trajectories based on format
    if fmt == "kitti":
        gt_poses = parse_kitti(gt_path)
        est_poses = parse_kitti(est_path)
    elif fmt == "tum":
        gt_poses = parse_tum(gt_path)
        est_poses = parse_tum(est_path)
    elif fmt == "euroc":
        gt_poses = parse_euroc_gt(gt_path)
        est_poses = parse_tum(est_path)
    else:
        raise ValueError(f"Unknown format: {fmt}")

    # Associate pose pairs
    if fmt == "kitti":
        gt_matched, est_matched = associate_by_index(gt_poses, est_poses)
    else:
        gt_matched, est_matched = associate_by_timestamp(
            gt_poses, est_poses, max_diff
        )

    if len(gt_matched) == 0:
        print("ERROR: No pose associations found.", file=sys.stderr)
        sys.exit(1)

    gt_pos = np.array([p[1] for p in gt_matched])
    est_pos = np.array([p[1] for p in est_matched])

    with_scale = (align_mode == "sim3")

    # Compute alignment (standard or robust)
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

    # Apply alignment to evaluation set
    aligned = (s * (R @ est_eval.T) + t.reshape(3, 1)).T

    # Compute ATE metrics
    metrics = compute_ate(gt_eval, aligned, s)

    if robust and inlier_mask is not None:
        metrics["num_inliers"] = int(np.sum(inlier_mask))

    # Optionally compute RPE
    if compute_rpe_flag:
        rpe_metrics = compute_rpe(gt_eval, aligned)
        metrics.update(rpe_metrics)

    # Save results
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(metrics, f, indent=2)

    return metrics


def main():
    parser = argparse.ArgumentParser(description="SLAM trajectory evaluation")
    parser.add_argument("--format", required=True, choices=["kitti", "tum", "euroc"])
    parser.add_argument("--gt", required=True)
    parser.add_argument("--est", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--align", default="se3", choices=["se3", "sim3"])
    parser.add_argument("--max_diff", type=float, default=0.02)
    parser.add_argument("--robust", action="store_true")
    parser.add_argument("--ransac_threshold", type=float, default=0.2)
    parser.add_argument("--ransac_iterations", type=int, default=1000)
    parser.add_argument("--ransac_seed", type=int, default=42)
    parser.add_argument("--rpe", action="store_true")
    args = parser.parse_args()

    metrics = evaluate(
        args.format, args.gt, args.est, args.output, args.align,
        args.max_diff, args.robust, args.ransac_threshold,
        args.ransac_iterations, args.ransac_seed, args.rpe
    )
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
'''


def main():
    print("Implementing SLAM evaluation pipeline...")
    write_file('/app/slam_eval/parsers.py', PARSERS_PY)
    write_file('/app/slam_eval/association.py', ASSOCIATION_PY)
    write_file('/app/slam_eval/alignment.py', ALIGNMENT_PY)
    write_file('/app/slam_eval/robust.py', ROBUST_PY)
    write_file('/app/slam_eval/metrics.py', METRICS_PY)
    write_file('/app/slam_eval/pipeline.py', PIPELINE_PY)
    print("All modules implemented successfully.")


if __name__ == '__main__':
    main()
