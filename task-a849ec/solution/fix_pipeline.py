#!/usr/bin/env python3
"""
Fix three bugs in the SLAM trajectory evaluation pipeline.

Bug 1 (parsers.py): EuRoC ground truth parser stores timestamps in nanoseconds
    instead of converting them to seconds. This causes timestamp-based association
    to fail because the GT timestamps (~1e18) are incomparable with the estimated
    trajectory timestamps in seconds (~1e3).
    Fix: multiply ts_ns by 1e-9 before storing.

Bug 2 (pipeline.py): The alignment function is called with arguments in the wrong
    order. align_umeyama(source, target) computes the transform from source to target,
    but the pipeline passes (gt_positions, est_positions), computing a gt->est transform.
    It then applies this transform to est_positions, which is mathematically incorrect.
    Fix: swap to align_umeyama(est_positions, gt_positions) so the transform maps est->gt.

Bug 3 (alignment.py): The Sim(3) scale estimation uses the variance of the target
    point set instead of the source point set. Per the Umeyama method, the scale
    factor s = trace(D @ S) / sigma_source^2, not sigma_target^2.
    Fix: compute variance from source_centered instead of target_centered.
"""


def fix_parsers():
    """Fix Bug 1: EuRoC timestamp nanoseconds not converted to seconds."""
    filepath = '/app/slam_eval/parsers.py'
    with open(filepath, 'r') as f:
        content = f.read()

    # The parser stores ts_ns directly; it should store ts_ns * 1e-9
    content = content.replace(
        "poses.append((ts_ns, np.array([px, py, pz]), R))",
        "poses.append((ts_ns * 1e-9, np.array([px, py, pz]), R))"
    )

    with open(filepath, 'w') as f:
        f.write(content)
    print("Fixed parsers.py: EuRoC timestamps now converted from ns to seconds")


def fix_pipeline():
    """Fix Bug 2: Alignment function called with source/target swapped."""
    filepath = '/app/slam_eval/pipeline.py'
    with open(filepath, 'r') as f:
        content = f.read()

    # The call has gt_positions as source and est_positions as target.
    # It should be est_positions as source and gt_positions as target,
    # because we want: gt ≈ s * R @ est + t
    content = content.replace(
        "R, t, s = align_umeyama(gt_positions, est_positions, with_scale=with_scale)",
        "R, t, s = align_umeyama(est_positions, gt_positions, with_scale=with_scale)"
    )

    with open(filepath, 'w') as f:
        f.write(content)
    print("Fixed pipeline.py: alignment now maps estimated -> ground truth")


def fix_alignment():
    """Fix Bug 3: Sim(3) scale uses wrong variance (target instead of source)."""
    filepath = '/app/slam_eval/alignment.py'
    with open(filepath, 'r') as f:
        content = f.read()

    # The Umeyama method requires sigma_source^2 in the denominator for scale.
    # The code incorrectly uses target variance.
    content = content.replace(
        "var_target = np.sum(target_centered ** 2) / n\n"
        "        s = np.trace(np.diag(D) @ S) / var_target",
        "var_source = np.sum(source_centered ** 2) / n\n"
        "        s = np.trace(np.diag(D) @ S) / var_source"
    )

    with open(filepath, 'w') as f:
        f.write(content)
    print("Fixed alignment.py: Sim(3) scale now uses source variance")


if __name__ == '__main__':
    fix_parsers()
    fix_pipeline()
    fix_alignment()
    print("\nAll pipeline bugs fixed successfully.")
