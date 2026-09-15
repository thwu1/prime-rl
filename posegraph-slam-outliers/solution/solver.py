#!/usr/bin/env python3

"""
Pose graph SLAM optimizer.

Strategy:
1. Pre-filter loop closures by checking consistency against the odometry
   chain (initial estimates). Outlier measurements connecting distant poses
   with bogus small-displacement readings produce huge discrepancies.
2. Optimize with Gauss-Newton using only consistent edges.
3. Post-optimization chi-squared check to catch any remaining outliers.
"""

import json
import math

import numpy as np
from scipy import sparse
from scipy.sparse.linalg import spsolve


def normalize_angle(a):
    return (a + math.pi) % (2 * math.pi) - math.pi


def info_matrix(ut):
    """Reconstruct symmetric 3x3 from upper triangle [i11,i12,i13,i22,i23,i33]."""
    return np.array([
        [ut[0], ut[1], ut[2]],
        [ut[1], ut[3], ut[4]],
        [ut[2], ut[4], ut[5]]
    ])


def compute_error(xi, yi, ti, xj, yj, tj, dxm, dym, dtm):
    """Compute residual e = z_measured - z_predicted."""
    c, s = math.cos(ti), math.sin(ti)
    dx_pred = c * (xj - xi) + s * (yj - yi)
    dy_pred = -s * (xj - xi) + c * (yj - yi)
    dt_pred = normalize_angle(tj - ti)
    return np.array([
        dxm - dx_pred,
        dym - dy_pred,
        normalize_angle(dtm - dt_pred)
    ])


def compute_jacobians(xi, yi, ti, xj, yj, tj):
    """
    Jacobians of error w.r.t. pose_i (A) and pose_j (B).

    e = z_meas - h(x_i, x_j)
    h = [R_i^T (t_j - t_i); theta_j - theta_i]
    """
    c, s = math.cos(ti), math.sin(ti)
    dx = xj - xi
    dy = yj - yi

    A = np.array([
        [c,  s,  s * dx - c * dy],
        [-s, c,  c * dx + s * dy],
        [0,  0,  1]
    ])

    B = np.array([
        [-c, -s, 0],
        [s,  -c, 0],
        [0,   0, -1]
    ])

    return A, B


def prefilter_loop_closures(data):
    """
    Reject loop closures whose measurements are wildly inconsistent with
    the odometry-accumulated initial estimates.

    For each LC edge (i,j) with measurement z, compute the predicted
    relative transform using the initial pose estimates (which embed the
    full odometry chain). If the position discrepancy exceeds a generous
    threshold, the edge is almost certainly an outlier.
    """
    init = data["initial_estimates"]
    rejected = set()

    for idx, lc in enumerate(data["loop_closure_edges"]):
        i, j = lc["i"], lc["j"]
        xi, yi, ti = init[i]
        xj, yj, tj = init[j]

        # Predicted relative measurement from i to j using initial estimates
        c, s = math.cos(ti), math.sin(ti)
        dx_pred = c * (xj - xi) + s * (yj - yi)
        dy_pred = -s * (xj - xi) + c * (yj - yi)

        # Position discrepancy between prediction and measurement
        dx_diff = lc["dx"] - dx_pred
        dy_diff = lc["dy"] - dy_pred
        pos_diff = math.sqrt(dx_diff ** 2 + dy_diff ** 2)

        # Generous threshold: odometry drift over full loop is ~1-2m,
        # so correct LCs should have < 3m discrepancy. Outliers connecting
        # distant poses have >> 5m discrepancy.
        if pos_diff > 3.0:
            rejected.add(idx)

    return rejected


def optimize(data, excluded_lc_indices):
    """Run Gauss-Newton pose graph optimization."""
    N = data["num_poses"]
    poses = np.array(data["initial_estimates"], dtype=np.float64)
    dim = 3 * N

    # Collect edges, skipping excluded loop closures
    edges = []
    for e in data["odometry_edges"]:
        edges.append((
            e["i"], e["j"], e["dx"], e["dy"], e["dtheta"],
            info_matrix(e["information"])
        ))
    for idx, e in enumerate(data["loop_closure_edges"]):
        if idx in excluded_lc_indices:
            continue
        edges.append((
            e["i"], e["j"], e["dx"], e["dy"], e["dtheta"],
            info_matrix(e["information"])
        ))

    for iteration in range(100):
        rows, cols, vals = [], [], []
        b = np.zeros(dim)

        for (i, j, dxm, dym, dtm, Om) in edges:
            xi, yi, ti = poses[i]
            xj, yj, tj = poses[j]

            e = compute_error(xi, yi, ti, xj, yj, tj, dxm, dym, dtm)
            A, B = compute_jacobians(xi, yi, ti, xj, yj, tj)

            ii, jj = 3 * i, 3 * j

            HAA = A.T @ Om @ A
            HAB = A.T @ Om @ B
            HBB = B.T @ Om @ B

            bA = -(A.T @ Om @ e)
            bB = -(B.T @ Om @ e)

            for r in range(3):
                for cc in range(3):
                    rows.extend([ii + r, ii + r, jj + r, jj + r])
                    cols.extend([ii + cc, jj + cc, ii + cc, jj + cc])
                    vals.extend([
                        HAA[r, cc], HAB[r, cc],
                        HAB.T[r, cc], HBB[r, cc]
                    ])

            b[ii:ii + 3] += bA
            b[jj:jj + 3] += bB

        # Fix pose 0 as gauge reference
        for k in range(3):
            rows.append(k)
            cols.append(k)
            vals.append(1e10)
        b[0:3] = 0.0

        H = sparse.coo_matrix(
            (vals, (rows, cols)), shape=(dim, dim)
        ).tocsc()

        dx = spsolve(H, b)
        poses += dx.reshape(-1, 3)
        poses[:, 2] = np.array([normalize_angle(a) for a in poses[:, 2]])

        step_norm = np.linalg.norm(dx)
        if step_norm < 1e-8:
            print(f"Converged at iteration {iteration}, "
                  f"step norm={step_norm:.2e}")
            break

    return poses


def postfilter_outliers(data, poses, already_rejected):
    """Post-optimization chi-squared check on remaining loop closures."""
    CHI2_THRESHOLD = 15.0
    rejected = set(already_rejected)

    for idx, e in enumerate(data["loop_closure_edges"]):
        if idx in rejected:
            continue
        Om = info_matrix(e["information"])
        err = compute_error(
            *poses[e["i"]], *poses[e["j"]],
            e["dx"], e["dy"], e["dtheta"]
        )
        chi2 = float(err @ Om @ err)
        if chi2 > CHI2_THRESHOLD:
            rejected.add(idx)

    return sorted(rejected)


def main():
    with open("/app/pose_graph.json") as f:
        data = json.load(f)

    print(f"Loaded: {data['num_poses']} poses, "
          f"{len(data['odometry_edges'])} odometry edges, "
          f"{len(data['loop_closure_edges'])} loop closure edges")

    # Step 1: Pre-filter outliers using odometry consistency
    prefiltered = prefilter_loop_closures(data)
    print(f"Pre-filter rejected {len(prefiltered)} loop closure(s): "
          f"{sorted(prefiltered)}")

    # Step 2: Optimize with consistent edges only
    poses = optimize(data, prefiltered)

    # Step 3: Post-optimization outlier check
    rejected = postfilter_outliers(data, poses, prefiltered)

    result = {
        "poses": [
            [round(float(p[0]), 10), round(float(p[1]), 10),
             round(float(p[2]), 10)]
            for p in poses
        ],
        "rejected_loop_closures": rejected
    }

    with open("/app/optimized_poses.json", "w") as f:
        json.dump(result, f, indent=2)

    print(f"Final: rejected {len(rejected)} loop closure(s): {rejected}")


if __name__ == "__main__":
    main()
