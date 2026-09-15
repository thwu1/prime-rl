#!/usr/bin/env python3
"""Generate SE(3) pose graph dataset in g2o format for SLAM optimization task."""
import numpy as np
import os


def rotation_z(angle):
    c, s = np.cos(angle), np.sin(angle)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])


def make_pose(R, t):
    T = np.eye(4)
    T[:3, :3] = R
    T[:3, 3] = t
    return T


def skew(v):
    return np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])


def exp_so3(omega):
    theta = np.linalg.norm(omega)
    if theta < 1e-10:
        return np.eye(3) + skew(omega)
    K = skew(omega / theta)
    return np.eye(3) + np.sin(theta) * K + (1 - np.cos(theta)) * K @ K


def add_noise_to_pose(T, trans_std, rot_std, rng):
    noise_trans = rng.normal(0, trans_std, 3)
    noise_rot = rng.normal(0, rot_std, 3)
    T_noisy = T.copy()
    T_noisy[:3, :3] = exp_so3(noise_rot) @ T[:3, :3]
    T_noisy[:3, 3] = T[:3, 3] + noise_trans
    return T_noisy


def inv_pose(T):
    T_inv = np.eye(4)
    T_inv[:3, :3] = T[:3, :3].T
    T_inv[:3, 3] = -T[:3, :3].T @ T[:3, 3]
    return T_inv


def rot_to_quat(R):
    """Convert 3x3 rotation matrix to quaternion (qx, qy, qz, qw) scalar-last."""
    tr = R[0, 0] + R[1, 1] + R[2, 2]
    if tr > 0:
        s = 2.0 * np.sqrt(tr + 1.0)
        qw = 0.25 * s
        qx = (R[2, 1] - R[1, 2]) / s
        qy = (R[0, 2] - R[2, 0]) / s
        qz = (R[1, 0] - R[0, 1]) / s
    elif R[0, 0] > R[1, 1] and R[0, 0] > R[2, 2]:
        s = 2.0 * np.sqrt(1.0 + R[0, 0] - R[1, 1] - R[2, 2])
        qw = (R[2, 1] - R[1, 2]) / s
        qx = 0.25 * s
        qy = (R[0, 1] + R[1, 0]) / s
        qz = (R[0, 2] + R[2, 0]) / s
    elif R[1, 1] > R[2, 2]:
        s = 2.0 * np.sqrt(1.0 + R[1, 1] - R[0, 0] - R[2, 2])
        qw = (R[0, 2] - R[2, 0]) / s
        qx = (R[0, 1] + R[1, 0]) / s
        qy = 0.25 * s
        qz = (R[1, 2] + R[2, 1]) / s
    else:
        s = 2.0 * np.sqrt(1.0 + R[2, 2] - R[0, 0] - R[1, 1])
        qw = (R[1, 0] - R[0, 1]) / s
        qx = (R[0, 2] + R[2, 0]) / s
        qy = (R[1, 2] + R[2, 1]) / s
        qz = 0.25 * s
    return qx, qy, qz, qw


def generate_and_write_g2o(filepath, seed=42):
    rng = np.random.RandomState(seed)

    gt_poses = []
    for i in range(5):
        gt_poses.append(make_pose(rotation_z(0), np.array([i * 3.0, 0.0, 0.0])))
    for i in range(4):
        gt_poses.append(make_pose(rotation_z(np.pi / 2), np.array([12.0, (i + 1) * 3.0, 0.0])))
    for i in range(4):
        gt_poses.append(make_pose(rotation_z(np.pi), np.array([12.0 - (i + 1) * 3.0, 12.0, 0.0])))
    for i in range(3):
        gt_poses.append(make_pose(rotation_z(3 * np.pi / 2), np.array([0.0, 12.0 - (i + 1) * 3.0, 0.0])))

    info_odom_rt = np.diag([2500.0, 2500.0, 2500.0, 400.0, 400.0, 400.0])
    info_lc_rt = np.diag([4000.0, 4000.0, 4000.0, 600.0, 600.0, 600.0])

    edges = []
    for i in range(15):
        T_rel = inv_pose(gt_poses[i]) @ gt_poses[i + 1]
        T_meas = add_noise_to_pose(T_rel, 0.05, 0.015, rng)
        edges.append({"from": i, "to": i + 1, "measurement": T_meas, "information": info_odom_rt})

    T_rel = inv_pose(gt_poses[15]) @ gt_poses[0]
    T_meas = add_noise_to_pose(T_rel, 0.03, 0.01, rng)
    edges.append({"from": 15, "to": 0, "measurement": T_meas, "information": info_lc_rt})

    T_rel = inv_pose(gt_poses[14]) @ gt_poses[1]
    T_meas = add_noise_to_pose(T_rel, 0.03, 0.01, rng)
    edges.append({"from": 14, "to": 1, "measurement": T_meas, "information": info_lc_rt})

    T_wrong = make_pose(exp_so3(rng.normal(0, 0.5, 3)), rng.normal(0, 2.0, 3))
    edges.append({"from": 3, "to": 10, "measurement": T_wrong, "information": info_lc_rt})

    T_wrong = make_pose(exp_so3(rng.normal(0, 0.5, 3)), rng.normal(0, 2.0, 3))
    edges.append({"from": 6, "to": 13, "measurement": T_wrong, "information": info_lc_rt})

    # Dead-reckoning initial estimates
    initial_estimates = [gt_poses[0].copy()]
    current_pose = gt_poses[0].copy()
    for i in range(15):
        current_pose = current_pose @ edges[i]["measurement"]
        initial_estimates.append(current_pose.copy())

    # Write g2o file
    with open(filepath, "w") as f:
        for idx, pose in enumerate(initial_estimates):
            x, y, z = pose[0, 3], pose[1, 3], pose[2, 3]
            qx, qy, qz, qw = rot_to_quat(pose[:3, :3])
            f.write(f"VERTEX_SE3:QUAT {idx} {x:.10f} {y:.10f} {z:.10f} "
                    f"{qx:.10f} {qy:.10f} {qz:.10f} {qw:.10f}\n")
        f.write("FIX 0\n")
        for edge in edges:
            meas = edge["measurement"]
            x, y, z = meas[0, 3], meas[1, 3], meas[2, 3]
            qx, qy, qz, qw = rot_to_quat(meas[:3, :3])
            # Convert info from internal [r,t] to g2o [t,r] ordering
            info_rt = edge["information"]
            perm = [3, 4, 5, 0, 1, 2]
            info_tr = info_rt[np.ix_(perm, perm)]
            vals = []
            for i in range(6):
                for j in range(i, 6):
                    vals.append(info_tr[i, j])
            info_str = " ".join(f"{v:.6f}" for v in vals)
            f.write(f"EDGE_SE3:QUAT {edge['from']} {edge['to']} "
                    f"{x:.10f} {y:.10f} {z:.10f} "
                    f"{qx:.10f} {qy:.10f} {qz:.10f} {qw:.10f} "
                    f"{info_str}\n")

    print(f"Pose graph generated: 16 poses, {len(edges)} edges in g2o format")


if __name__ == "__main__":
    os.makedirs("/app/data", exist_ok=True)
    generate_and_write_g2o("/app/data/trajectory.g2o", seed=42)
