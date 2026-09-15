#!/usr/bin/env python3
"""
Edge consistency analyzer using chi-squared test on SE(2) Mahalanobis distance.

"""
import argparse
import json
import math

import numpy as np


def normalize_angle(a):
    a = math.fmod(a, 2 * math.pi)
    if a > math.pi:
        a -= 2 * math.pi
    elif a < -math.pi:
        a += 2 * math.pi
    return a


def parse_g2o(filename):
    edges = []
    with open(filename) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if parts[0] == "EDGE_SE2":
                id1, id2 = int(parts[1]), int(parts[2])
                dx, dy, dtheta = float(parts[3]), float(parts[4]), float(parts[5])
                i11, i12, i13 = float(parts[6]), float(parts[7]), float(parts[8])
                i22, i23 = float(parts[9]), float(parts[10])
                i33 = float(parts[11])
                info = np.array([[i11, i12, i13], [i12, i22, i23], [i13, i23, i33]])
                measurement = np.array([dx, dy, dtheta])
                edges.append((id1, id2, measurement, info))
    return edges


def parse_poses(filename):
    poses = {}
    with open(filename) as f:
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


def compute_se2_error(xi, yi, ti, xj, yj, tj, measurement):
    c, s = math.cos(ti), math.sin(ti)
    dxg, dyg = xj - xi, yj - yi
    pred_dx = c * dxg + s * dyg
    pred_dy = -s * dxg + c * dyg
    pred_dtheta = normalize_angle(tj - ti)
    return np.array([
        pred_dx - measurement[0],
        pred_dy - measurement[1],
        normalize_angle(pred_dtheta - measurement[2]),
    ])


def main():
    parser = argparse.ArgumentParser(
        description="Edge consistency analysis via chi-squared test"
    )
    parser.add_argument("--graph", required=True, help="Input g2o file")
    parser.add_argument("--poses", required=True, help="Poses file")
    parser.add_argument(
        "--threshold", type=float, default=7.815,
        help="Chi-squared critical value (3 DOF, default 95%%)"
    )
    parser.add_argument("--output", required=True, help="Output JSON report")
    args = parser.parse_args()

    edges = parse_g2o(args.graph)
    poses = parse_poses(args.poses)

    results = []
    num_consistent = 0
    num_inconsistent = 0

    for id1, id2, meas, info in edges:
        xi, yi, ti = poses[id1]
        xj, yj, tj = poses[id2]

        e = compute_se2_error(xi, yi, ti, xj, yj, tj, meas)
        chi_sq = float(e @ info @ e)
        consistent = chi_sq <= args.threshold

        results.append({
            "from": id1,
            "to": id2,
            "chi_squared": chi_sq,
            "consistent": consistent,
        })

        if consistent:
            num_consistent += 1
        else:
            num_inconsistent += 1

    output = {
        "edges": results,
        "num_consistent": num_consistent,
        "num_inconsistent": num_inconsistent,
        "threshold": args.threshold,
    }

    with open(args.output, "w") as f:
        json.dump(output, f, indent=2)

    print(
        "Consistency analysis: %d consistent, %d inconsistent (threshold=%.3f)"
        % (num_consistent, num_inconsistent, args.threshold)
    )


if __name__ == "__main__":
    main()
