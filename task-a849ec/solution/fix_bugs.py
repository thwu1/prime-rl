#!/usr/bin/env python3
"""
Fix all bugs in the SLAM trajectory evaluation pipeline.

Five bugs are fixed across four files:

1. parsers.py: EuRoC ground truth timestamps are stored in nanoseconds
   without conversion to seconds, causing timestamp-based association
   to fail (GT timestamps ~1e18 vs EST timestamps ~1e3).

2. alignment.py: The cross-covariance matrix in Umeyama alignment is
   computed as src_c.T @ tgt_c instead of tgt_c.T @ src_c. This
   transposes W, causing the SVD to produce R^T (inverse rotation)
   instead of R, breaking all trajectory alignments.

3. alignment.py: The Sim(3) scale estimation uses the variance of the
   target (ground truth) point set instead of the source (estimated)
   point set. Per the Umeyama derivation, scale = trace(DS)/sigma_src^2.

4. pipeline.py: In RANSAC robust mode, metrics are evaluated on ALL
   associated poses instead of only the inlier subset identified by
   RANSAC. This includes outlier poses in the error computation.

5. metrics.py: RPE relative motion for ground truth is computed with
   reversed subtraction (positions[:-1] - positions[1:] gives backward
   motion instead of forward motion). This causes the RPE to measure
   the sum of motions rather than the difference, producing values
   approximately 2x the actual step length.
"""

import re


def fix_parsers():
    """Fix Bug 1: EuRoC timestamps not converted from nanoseconds to seconds."""
    path = '/app/slam_eval/parsers.py'
    with open(path) as f:
        content = f.read()

    # The parser reads float(row[0]) which is nanoseconds.
    # Must multiply by 1e-9 to get seconds.
    content = content.replace(
        '            ts = float(row[0])\n'
        '            px, py, pz = float(row[1]), float(row[2]), float(row[3])',
        '            ts = float(row[0]) * 1e-9\n'
        '            px, py, pz = float(row[1]), float(row[2]), float(row[3])'
    )

    with open(path, 'w') as f:
        f.write(content)
    print("Fixed parsers.py: EuRoC timestamps converted from ns to seconds")


def fix_alignment():
    """Fix Bug 2 and Bug 3 in alignment.py."""
    path = '/app/slam_eval/alignment.py'
    with open(path) as f:
        content = f.read()

    # Bug 2: Cross-covariance matrix is transposed.
    # src_c.T @ tgt_c gives W^T; should be tgt_c.T @ src_c.
    content = content.replace(
        'W = src_c.T @ tgt_c / n',
        'W = tgt_c.T @ src_c / n'
    )

    # Bug 3: Scale uses target variance instead of source variance.
    content = content.replace(
        'var = np.sum(tgt_c ** 2) / n',
        'var = np.sum(src_c ** 2) / n'
    )

    with open(path, 'w') as f:
        f.write(content)
    print("Fixed alignment.py: cross-covariance direction and scale variance")


def fix_pipeline():
    """Fix Bug 4: RANSAC evaluates on all poses instead of inliers only."""
    path = '/app/slam_eval/pipeline.py'
    with open(path) as f:
        content = f.read()

    # In the robust branch, gt_eval and est_eval should be filtered
    # to inlier poses only, not use all poses.
    content = content.replace(
        '        # Evaluate alignment quality on all associated poses\n'
        '        gt_eval = gt_pos\n'
        '        est_eval = est_pos',
        '        # Evaluate alignment quality on inlier poses only\n'
        '        gt_eval = gt_pos[inlier_mask]\n'
        '        est_eval = est_pos[inlier_mask]'
    )

    with open(path, 'w') as f:
        f.write(content)
    print("Fixed pipeline.py: RANSAC now evaluates on inlier poses only")


def fix_metrics():
    """Fix Bug 5: RPE ground truth relative motion is computed backwards."""
    path = '/app/slam_eval/metrics.py'
    with open(path) as f:
        content = f.read()

    # gt_rel uses positions[:-1] - positions[1:] (backward motion).
    # Should be positions[1:] - positions[:-1] (forward motion).
    content = content.replace(
        'gt_rel = gt_positions[:-1] - gt_positions[1:]',
        'gt_rel = gt_positions[1:] - gt_positions[:-1]'
    )

    with open(path, 'w') as f:
        f.write(content)
    print("Fixed metrics.py: RPE now uses correct forward motion direction")


if __name__ == '__main__':
    print("Fixing SLAM evaluation pipeline bugs...")
    fix_parsers()
    fix_alignment()
    fix_pipeline()
    fix_metrics()
    print("\nAll 5 bugs fixed successfully.")
