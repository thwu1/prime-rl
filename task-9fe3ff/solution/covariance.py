#!/usr/bin/env python3
"""
Marginal covariance recovery from the Gauss-Newton Hessian of an SE(2) pose graph.

"""
import argparse
import json
import math

import numpy as np


def parse_g2o(filename):
    edges = []
    fixed = set()
    vertex_ids = set()
    with open(filename) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if parts[0] == "VERTEX_SE2":
                vertex_ids.add(int(parts[1]))
            elif parts[0] == "EDGE_SE2":
                id1, id2 = int(parts[1]), int(parts[2])
                dx, dy, dtheta = float(parts[3]), float(parts[4]), float(parts[5])
                i11, i12, i13 = float(parts[6]), float(parts[7]), float(parts[8])
                i22, i23 = float(parts[9]), float(parts[10])
                i33 = float(parts[11])
                info = np.array([[i11, i12, i13], [i12, i22, i23], [i13, i23, i33]])
                measurement = np.array([dx, dy, dtheta])
                edges.append((id1, id2, measurement, info))
            elif parts[0] == "FIX":
                fixed.add(int(parts[1]))
    return sorted(vertex_ids), edges, fixed


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
                poses[vid] = np.array([x, y, theta])
    return poses


def compute_jacobians(xi, yi, ti, xj, yj, tj):
    c, s = math.cos(ti), math.sin(ti)
    dxg, dyg = xj - xi, yj - yi
    Ji = np.array([
        [-c, -s, -s * dxg + c * dyg],
        [s, -c, -c * dxg - s * dyg],
        [0.0, 0.0, -1.0],
    ])
    Jj = np.array([[c, s, 0.0], [-s, c, 0.0], [0.0, 0.0, 1.0]])
    return Ji, Jj


def main():
    parser = argparse.ArgumentParser(
        description="Marginal covariance recovery from pose-graph Hessian"
    )
    parser.add_argument("--graph", required=True, help="Input g2o file")
    parser.add_argument("--poses", required=True, help="Optimized poses file")
    parser.add_argument("--output", required=True, help="Output JSON report")
    args = parser.parse_args()

    vids, edges, fixed = parse_g2o(args.graph)
    poses = parse_poses(args.poses)

    n = len(vids)
    vid_to_idx = {vid: i for i, vid in enumerate(vids)}

    # Build Hessian H = sum_edges J_e^T Omega_e J_e
    H = np.zeros((3 * n, 3 * n))

    for id1, id2, meas, info in edges:
        i1 = vid_to_idx[id1]
        i2 = vid_to_idx[id2]
        p1 = poses[id1]
        p2 = poses[id2]
        Ji, Jj = compute_jacobians(p1[0], p1[1], p1[2], p2[0], p2[1], p2[2])

        for J_a, idx_a in [(Ji, i1), (Jj, i2)]:
            JtO = J_a.T @ info
            for J_b, idx_b in [(Ji, i1), (Jj, i2)]:
                block = JtO @ J_b
                H[3 * idx_a:3 * idx_a + 3, 3 * idx_b:3 * idx_b + 3] += block

    # Extract free sub-block (exclude fixed vertices)
    free_mask = np.ones(3 * n, dtype=bool)
    for vid in fixed:
        idx = vid_to_idx[vid]
        free_mask[3 * idx:3 * idx + 3] = False
    free_indices = np.where(free_mask)[0]

    H_free = H[np.ix_(free_indices, free_indices)]

    # Invert: Sigma = H_free^{-1}
    cov_free = np.linalg.inv(H_free)

    # Map free vertices to local indices in cov_free
    free_vid_to_local = {}
    local_idx = 0
    for vid in vids:
        if vid not in fixed:
            free_vid_to_local[vid] = local_idx
            local_idx += 1

    result = {"poses": {}, "covariance_matrix_size": len(free_indices)}

    for vid in vids:
        if vid in fixed:
            result["poses"][str(vid)] = {
                "covariance": [[0.0] * 3 for _ in range(3)],
                "ellipse": {
                    "semi_major": 0.0,
                    "semi_minor": 0.0,
                    "angle_rad": 0.0,
                },
                "pos_trace": 0.0,
            }
        else:
            li = free_vid_to_local[vid]
            cov_block = cov_free[3 * li:3 * li + 3, 3 * li:3 * li + 3]

            # Position sub-block (2x2)
            pos_cov = cov_block[:2, :2]
            pos_trace = float(pos_cov[0, 0] + pos_cov[1, 1])

            # Eigendecomposition for uncertainty ellipse
            eigenvalues, eigenvectors = np.linalg.eigh(pos_cov)
            idx_sort = np.argsort(eigenvalues)[::-1]
            eigenvalues = eigenvalues[idx_sort]
            eigenvectors = eigenvectors[:, idx_sort]

            semi_major = float(math.sqrt(max(eigenvalues[0], 0.0)))
            semi_minor = float(math.sqrt(max(eigenvalues[1], 0.0)))
            angle = float(math.atan2(eigenvectors[1, 0], eigenvectors[0, 0]))

            result["poses"][str(vid)] = {
                "covariance": cov_block.tolist(),
                "ellipse": {
                    "semi_major": semi_major,
                    "semi_minor": semi_minor,
                    "angle_rad": angle,
                },
                "pos_trace": pos_trace,
            }

    with open(args.output, "w") as f:
        json.dump(result, f, indent=2)

    print("Covariance recovery complete. Matrix size: %d" % len(free_indices))


if __name__ == "__main__":
    main()
