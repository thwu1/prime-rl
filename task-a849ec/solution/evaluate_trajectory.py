#!/usr/bin/env python3
"""
Trajectory evaluation tool for Visual SLAM benchmarks.
Supports KITTI, TUM, and EuRoC formats with SE(3)/Sim(3) alignment.
"""
import argparse
import csv
import json
import os
import sys
import numpy as np


def rotmat_to_quaternion(R):
    """Rotation matrix to quaternion [qx, qy, qz, qw]."""
    tr = np.trace(R)
    if tr > 0:
        s = 0.5 / np.sqrt(tr + 1.0)
        w = 0.25 / s
        x = (R[2, 1] - R[1, 2]) * s
        y = (R[0, 2] - R[2, 0]) * s
        z = (R[1, 0] - R[0, 1]) * s
    elif R[0, 0] > R[1, 1] and R[0, 0] > R[2, 2]:
        s = 2.0 * np.sqrt(1.0 + R[0, 0] - R[1, 1] - R[2, 2])
        w = (R[2, 1] - R[1, 2]) / s
        x = 0.25 * s
        y = (R[0, 1] + R[1, 0]) / s
        z = (R[0, 2] + R[2, 0]) / s
    elif R[1, 1] > R[2, 2]:
        s = 2.0 * np.sqrt(1.0 + R[1, 1] - R[0, 0] - R[2, 2])
        w = (R[0, 2] - R[2, 0]) / s
        x = (R[0, 1] + R[1, 0]) / s
        y = 0.25 * s
        z = (R[1, 2] + R[2, 1]) / s
    else:
        s = 2.0 * np.sqrt(1.0 + R[2, 2] - R[0, 0] - R[1, 1])
        w = (R[1, 0] - R[0, 1]) / s
        x = (R[0, 2] + R[2, 0]) / s
        y = (R[1, 2] + R[2, 1]) / s
        z = 0.25 * s
    return np.array([x, y, z, w])


# ---- Format parsers ----

def parse_kitti(filepath):
    """Parse KITTI format: each line is 12 floats (row-major 3x4 matrix).
    Returns list of (index, position_xyz) tuples."""
    poses = []
    with open(filepath) as f:
        for idx, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            vals = list(map(float, line.split()))
            assert len(vals) == 12, f"KITTI line {idx}: expected 12 values, got {len(vals)}"
            # Row-major 3x4: r11 r12 r13 tx r21 r22 r23 ty r31 r32 r33 tz
            tx, ty, tz = vals[3], vals[7], vals[11]
            poses.append((float(idx), np.array([tx, ty, tz])))
    return poses


def parse_tum(filepath):
    """Parse TUM format: timestamp tx ty tz qx qy qz qw.
    Returns list of (timestamp, position_xyz) tuples."""
    poses = []
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            vals = line.split()
            ts = float(vals[0])
            tx, ty, tz = float(vals[1]), float(vals[2]), float(vals[3])
            poses.append((ts, np.array([tx, ty, tz])))
    return poses


def parse_euroc(filepath):
    """Parse EuRoC CSV format: timestamp_ns, px, py, pz, qw, qx, qy, qz, ...
    Returns list of (timestamp_seconds, position_xyz) tuples."""
    poses = []
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            vals = line.split(',')
            ts_ns = int(vals[0])
            ts_s = float(ts_ns) * 1e-9
            px, py, pz = float(vals[1]), float(vals[2]), float(vals[3])
            poses.append((ts_s, np.array([px, py, pz])))
    return poses


# ---- Timestamp association ----

def associate_by_index(gt_poses, est_poses):
    """Associate by line index (KITTI). Returns paired positions."""
    n = min(len(gt_poses), len(est_poses))
    gt_pos = np.array([gt_poses[i][1] for i in range(n)])
    est_pos = np.array([est_poses[i][1] for i in range(n)])
    return gt_pos, est_pos


def associate_by_timestamp(gt_poses, est_poses, max_diff=0.02):
    """Associate by nearest timestamp within max_diff. Returns paired positions."""
    gt_ts = np.array([p[0] for p in gt_poses])
    est_ts = np.array([p[0] for p in est_poses])

    gt_matched = []
    est_matched = []

    for i, t_est in enumerate(est_ts):
        diffs = np.abs(gt_ts - t_est)
        j = np.argmin(diffs)
        if diffs[j] <= max_diff:
            gt_matched.append(gt_poses[j][1])
            est_matched.append(est_poses[i][1])

    return np.array(gt_matched), np.array(est_matched)


# ---- Umeyama alignment ----

def umeyama_alignment(model, data, with_scale=False):
    """Umeyama alignment: find s, R, t such that model ~ s*R*data + t.
    model: Nx3 ground truth positions
    data: Nx3 estimated positions
    Returns (s, R, t)
    """
    mu_m = model.mean(axis=0)
    mu_d = data.mean(axis=0)
    model_zc = model - mu_m
    data_zc = data - mu_d
    n = model.shape[0]

    sigma2 = np.sum(data_zc ** 2) / n

    W = (model_zc.T @ data_zc) / n

    U, D, Vt = np.linalg.svd(W)

    S = np.eye(3)
    if np.linalg.det(U) * np.linalg.det(Vt) < 0:
        S[2, 2] = -1

    R = U @ S @ Vt

    if with_scale:
        s = np.trace(np.diag(D) @ S) / sigma2
    else:
        s = 1.0

    t = mu_m - s * R @ mu_d

    return s, R, t


# ---- ATE computation ----

def compute_ate(gt_pos, est_pos, with_scale=False):
    """Compute ATE metrics after Umeyama alignment."""
    s, R, t = umeyama_alignment(gt_pos, est_pos, with_scale)

    aligned = s * (R @ est_pos.T).T + t
    errors = np.linalg.norm(gt_pos - aligned, axis=1)

    return {
        'rmse': float(np.sqrt(np.mean(errors ** 2))),
        'mean': float(np.mean(errors)),
        'median': float(np.median(errors)),
        'std': float(np.std(errors)),
        'max': float(np.max(errors)),
        'min': float(np.min(errors)),
        'num_poses': int(len(errors)),
        'scale': float(s),
    }


def main():
    parser = argparse.ArgumentParser(description='Trajectory evaluation for Visual SLAM')
    parser.add_argument('--format', required=True, choices=['kitti', 'tum', 'euroc'])
    parser.add_argument('--gt', required=True, help='Ground truth file')
    parser.add_argument('--est', required=True, help='Estimated trajectory file')
    parser.add_argument('--output', required=True, help='Output JSON path')
    parser.add_argument('--align', default='se3', choices=['se3', 'sim3'])
    parser.add_argument('--max_diff', type=float, default=0.02,
                        help='Max timestamp diff for association (seconds)')
    args = parser.parse_args()

    # Parse trajectories
    if args.format == 'kitti':
        gt_poses = parse_kitti(args.gt)
        est_poses = parse_kitti(args.est)
        gt_pos, est_pos = associate_by_index(gt_poses, est_poses)
    elif args.format == 'tum':
        gt_poses = parse_tum(args.gt)
        est_poses = parse_tum(args.est)
        gt_pos, est_pos = associate_by_timestamp(gt_poses, est_poses, args.max_diff)
    elif args.format == 'euroc':
        gt_poses = parse_euroc(args.gt)
        est_poses = parse_tum(args.est)  # Estimated is in TUM format
        gt_pos, est_pos = associate_by_timestamp(gt_poses, est_poses, args.max_diff)

    if len(gt_pos) == 0:
        print("ERROR: No poses could be associated.", file=sys.stderr)
        sys.exit(1)

    with_scale = (args.align == 'sim3')
    metrics = compute_ate(gt_pos, est_pos, with_scale)

    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    with open(args.output, 'w') as f:
        json.dump(metrics, f, indent=2)

    print(f"ATE evaluation complete: {metrics['num_poses']} poses, RMSE={metrics['rmse']:.6f}")


if __name__ == '__main__':
    main()
