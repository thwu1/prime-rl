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

    if robust:
        R, t, s, inlier_mask = ransac_align(
            est_pos, gt_pos, with_scale,
            ransac_threshold, ransac_iterations, seed=ransac_seed
        )
        # Evaluate alignment quality on all associated poses
        gt_eval = gt_pos
        est_eval = est_pos
    else:
        R, t, s = align_umeyama(est_pos, gt_pos, with_scale)
        gt_eval = gt_pos
        est_eval = est_pos
        inlier_mask = None

    aligned = (s * (R @ est_eval.T) + t.reshape(3, 1)).T

    metrics = compute_ate(gt_eval, aligned, s)

    if robust and inlier_mask is not None:
        metrics['num_inliers'] = int(np.sum(inlier_mask))

    if compute_rpe_flag:
        rpe_metrics = compute_rpe(gt_eval, aligned)
        metrics.update(rpe_metrics)

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
