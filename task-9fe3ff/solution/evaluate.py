#!/usr/bin/env python3
"""
Trajectory evaluation tool: computes ATE and RPE between estimated and reference poses.

"""
import argparse
import json
import math
import sys


def normalize_angle(a):
    """Normalize angle to [-pi, pi]."""
    a = math.fmod(a, 2 * math.pi)
    if a > math.pi:
        a -= 2 * math.pi
    elif a < -math.pi:
        a += 2 * math.pi
    return a


def parse_poses(filepath):
    """Parse a pose file (id x y theta per line) into a dict."""
    poses = {}
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) >= 4:
                vid = int(parts[0])
                x, y, theta = float(parts[1]), float(parts[2]), float(parts[3])
                poses[vid] = (x, y, theta)
    return poses


def se2_inverse(x, y, theta):
    """Invert an SE(2) pose: T^{-1}."""
    c, s = math.cos(theta), math.sin(theta)
    return (-c * x - s * y, s * x - c * y, normalize_angle(-theta))


def se2_compose(x1, y1, t1, x2, y2, t2):
    """Compose two SE(2) poses: T1 * T2."""
    c, s = math.cos(t1), math.sin(t1)
    return (
        x1 + c * x2 - s * y2,
        y1 + s * x2 + c * y2,
        normalize_angle(t1 + t2),
    )


def compute_ate(estimated, reference):
    """Compute Absolute Trajectory Error (position RMSE and max)."""
    common_ids = sorted(set(estimated.keys()) & set(reference.keys()))
    if not common_ids:
        return float("inf"), float("inf")

    sq_errors = []
    max_err = 0.0
    for vid in common_ids:
        ex, ey, _ = estimated[vid]
        rx, ry, _ = reference[vid]
        sq_err = (ex - rx) ** 2 + (ey - ry) ** 2
        sq_errors.append(sq_err)
        max_err = max(max_err, math.sqrt(sq_err))

    rmse = math.sqrt(sum(sq_errors) / len(sq_errors))
    return rmse, max_err


def compute_rpe(estimated, reference):
    """Compute Relative Pose Error over consecutive pose pairs.

    For each consecutive pair (i, j) in sorted common vertex IDs:
      - Compute relative transform in estimated: T_ei^{-1} * T_ej
      - Compute relative transform in reference: T_ri^{-1} * T_rj
      - Error = T_ref_rel^{-1} * T_est_rel
      - Accumulate translation and rotation errors
    """
    common_ids = sorted(set(estimated.keys()) & set(reference.keys()))
    if len(common_ids) < 2:
        return float("inf"), float("inf")

    trans_errors = []
    rot_errors = []

    for k in range(len(common_ids) - 1):
        i, j = common_ids[k], common_ids[k + 1]

        # Relative pose in estimated trajectory: T_ei^{-1} * T_ej
        ei_inv = se2_inverse(*estimated[i])
        e_rel = se2_compose(*ei_inv, *estimated[j])

        # Relative pose in reference trajectory: T_ri^{-1} * T_rj
        ri_inv = se2_inverse(*reference[i])
        r_rel = se2_compose(*ri_inv, *reference[j])

        # Error: T_ref_rel^{-1} * T_est_rel
        r_rel_inv = se2_inverse(*r_rel)
        err = se2_compose(*r_rel_inv, *e_rel)

        trans_err = math.sqrt(err[0] ** 2 + err[1] ** 2)
        rot_err = abs(normalize_angle(err[2]))

        trans_errors.append(trans_err)
        rot_errors.append(rot_err)

    return (
        sum(trans_errors) / len(trans_errors),
        sum(rot_errors) / len(rot_errors),
    )


def main():
    parser = argparse.ArgumentParser(description="Trajectory Evaluation Tool")
    parser.add_argument("--estimated", required=True, help="Estimated poses file")
    parser.add_argument(
        "--reference", required=True, help="Reference/ground truth poses file"
    )
    parser.add_argument("--output", required=True, help="Output JSON report")
    args = parser.parse_args()

    estimated = parse_poses(args.estimated)
    reference = parse_poses(args.reference)

    ate_rmse, ate_max = compute_ate(estimated, reference)
    rpe_trans, rpe_rot = compute_rpe(estimated, reference)

    report = {
        "ate_rmse": ate_rmse,
        "ate_max": ate_max,
        "rpe_trans_mean": rpe_trans,
        "rpe_rot_mean": rpe_rot,
        "num_poses": len(set(estimated.keys()) & set(reference.keys())),
    }

    with open(args.output, "w") as f:
        json.dump(report, f, indent=2)

    print("ATE RMSE: %.6f m, ATE Max: %.6f m" % (ate_rmse, ate_max))
    print("RPE Trans Mean: %.6f m, RPE Rot Mean: %.6f rad" % (rpe_trans, rpe_rot))


if __name__ == "__main__":
    main()
