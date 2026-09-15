#!/usr/bin/env python3
"""Generate a 2D pose graph SLAM dataset with outlier loop closures."""
import json
import math
import random


def normalize_angle(a):
    return (a + math.pi) % (2 * math.pi) - math.pi


def relative_transform(xi, yi, ti, xj, yj, tj):
    c, s = math.cos(ti), math.sin(ti)
    dx = c * (xj - xi) + s * (yj - yi)
    dy = -s * (xj - xi) + c * (yj - yi)
    dt = normalize_angle(tj - ti)
    return dx, dy, dt


def main():
    random.seed(42)
    num_poses = 100
    radius = 5.0

    # Ground truth: circular trajectory
    gt = []
    for i in range(num_poses):
        angle = 2 * math.pi * i / num_poses
        x = radius * math.cos(angle)
        y = radius * math.sin(angle)
        theta = normalize_angle(angle + math.pi / 2)
        gt.append((x, y, theta))

    # Odometry edges: 0->1, 1->2, ..., 98->99
    sigma_odom_xy = 0.05
    sigma_odom_t = 0.01
    odom_info = [400.0, 0.0, 0.0, 400.0, 0.0, 10000.0]

    odom_edges = []
    for i in range(num_poses - 1):
        j = i + 1
        dx, dy, dt = relative_transform(*gt[i], *gt[j])
        dx += random.gauss(0, sigma_odom_xy)
        dy += random.gauss(0, sigma_odom_xy)
        dt = normalize_angle(dt + random.gauss(0, sigma_odom_t))
        odom_edges.append({
            "i": i, "j": j,
            "dx": round(dx, 10), "dy": round(dy, 10),
            "dtheta": round(dt, 10),
            "information": list(odom_info)
        })

    # Correct loop closure edges (near start/end of trajectory)
    correct_pairs = [
        (99, 0), (98, 1), (97, 2), (96, 3), (95, 4),
        (99, 1), (98, 2), (97, 3), (96, 4), (95, 5)
    ]
    sigma_lc_xy = 0.02
    sigma_lc_t = 0.005
    lc_info = [2500.0, 0.0, 0.0, 2500.0, 0.0, 40000.0]

    all_lc = []
    for pi, pj in correct_pairs:
        dx, dy, dt = relative_transform(*gt[pi], *gt[pj])
        dx += random.gauss(0, sigma_lc_xy)
        dy += random.gauss(0, sigma_lc_xy)
        dt = normalize_angle(dt + random.gauss(0, sigma_lc_t))
        all_lc.append({
            "i": pi, "j": pj,
            "dx": round(dx, 10), "dy": round(dy, 10),
            "dtheta": round(dt, 10),
            "information": list(lc_info),
            "_outlier": False
        })

    # Outlier loop closure edges (distant poses, fake measurements)
    outlier_pairs = [(10, 50), (20, 60), (30, 70), (15, 65), (25, 75)]
    for pi, pj in outlier_pairs:
        dx = random.gauss(0.2, 0.1)
        dy = random.gauss(0.0, 0.1)
        dt = normalize_angle(random.gauss(0.0, 0.05))
        all_lc.append({
            "i": pi, "j": pj,
            "dx": round(dx, 10), "dy": round(dy, 10),
            "dtheta": round(dt, 10),
            "information": list(lc_info),
            "_outlier": True
        })

    # Shuffle loop closures deterministically
    indices = list(range(len(all_lc)))
    random.shuffle(indices)
    shuffled_lc = [all_lc[k] for k in indices]

    # Strip internal outlier flag before saving
    clean_lc = []
    for e in shuffled_lc:
        clean_lc.append({
            "i": e["i"], "j": e["j"],
            "dx": e["dx"], "dy": e["dy"], "dtheta": e["dtheta"],
            "information": e["information"]
        })

    # Initial estimates from accumulated noisy odometry
    x, y, theta = gt[0]
    initial = [[round(x, 10), round(y, 10), round(theta, 10)]]
    for edge in odom_edges:
        dx_l, dy_l, dt_l = edge["dx"], edge["dy"], edge["dtheta"]
        c, s = math.cos(theta), math.sin(theta)
        x += c * dx_l - s * dy_l
        y += s * dx_l + c * dy_l
        theta = normalize_angle(theta + dt_l)
        initial.append([round(x, 10), round(y, 10), round(theta, 10)])

    dataset = {
        "description": (
            "2D Pose Graph SLAM dataset. A robot traversed a closed loop and "
            "returned near its starting position. Odometry edges are sequential "
            "constraints between consecutive poses. Loop closure edges are "
            "constraints between non-consecutive poses detected by sensor "
            "matching. Some loop closure edges may be false positives (outliers) "
            "with incorrect measurements. The information matrix for each edge "
            "is stored as the upper triangle [i11, i12, i13, i22, i23, i33] of "
            "the symmetric 3x3 matrix. Pose 0 should be used as the gauge "
            "reference (do not optimize it)."
        ),
        "num_poses": num_poses,
        "initial_estimates": initial,
        "odometry_edges": odom_edges,
        "loop_closure_edges": clean_lc
    }

    with open("/app/pose_graph.json", "w") as f:
        json.dump(dataset, f, indent=2)

    print(f"Generated: {num_poses} poses, {len(odom_edges)} odometry edges, "
          f"{len(clean_lc)} loop closure edges")


if __name__ == "__main__":
    main()
