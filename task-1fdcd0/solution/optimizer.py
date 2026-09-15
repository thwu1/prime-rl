#!/usr/bin/env python3
"""
Pose graph optimizer: reads g2o format SE(3) pose graph, performs
robust optimization with graduated non-convexity and outlier rejection,
produces JSON + g2o + gnuplot outputs.
"""

import json
import os
import subprocess
import numpy as np


# ---------------------------------------------------------------------------
# Quaternion / rotation conversions
# ---------------------------------------------------------------------------

def quat_to_rot(qx, qy, qz, qw):
    """Unit quaternion (qx,qy,qz,qw) scalar-last to 3x3 rotation matrix."""
    return np.array([
        [1 - 2*(qy*qy + qz*qz), 2*(qx*qy - qz*qw), 2*(qx*qz + qy*qw)],
        [2*(qx*qy + qz*qw), 1 - 2*(qx*qx + qz*qz), 2*(qy*qz - qx*qw)],
        [2*(qx*qz - qy*qw), 2*(qy*qz + qx*qw), 1 - 2*(qx*qx + qy*qy)]
    ])


def rot_to_quat(R):
    """3x3 rotation matrix to unit quaternion (qx,qy,qz,qw) scalar-last."""
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


# ---------------------------------------------------------------------------
# g2o I/O
# ---------------------------------------------------------------------------

def parse_g2o(filepath):
    """Parse g2o file. Returns (poses, edges, fixed_id, raw_edge_lines)."""
    vertices = {}
    edges = []
    fixed_id = 0
    raw_edge_lines = []

    with open(filepath) as f:
        for line in f:
            parts = line.strip().split()
            if not parts:
                continue
            if parts[0] == 'VERTEX_SE3:QUAT':
                vid = int(parts[1])
                x, y, z = float(parts[2]), float(parts[3]), float(parts[4])
                qx, qy, qz, qw = float(parts[5]), float(parts[6]), float(parts[7]), float(parts[8])
                R = quat_to_rot(qx, qy, qz, qw)
                T = np.eye(4)
                T[:3, :3] = R
                T[:3, 3] = [x, y, z]
                vertices[vid] = T
            elif parts[0] == 'EDGE_SE3:QUAT':
                raw_edge_lines.append(line.strip())
                fid, tid = int(parts[1]), int(parts[2])
                dx, dy, dz = float(parts[3]), float(parts[4]), float(parts[5])
                dqx, dqy, dqz, dqw = float(parts[6]), float(parts[7]), float(parts[8]), float(parts[9])
                R = quat_to_rot(dqx, dqy, dqz, dqw)
                T = np.eye(4)
                T[:3, :3] = R
                T[:3, 3] = [dx, dy, dz]
                # Parse upper triangle of 6x6 info matrix (21 values, g2o [t,r] ordering)
                info_vals = [float(parts[10 + k]) for k in range(21)]
                Omega_tr = np.zeros((6, 6))
                k = 0
                for i in range(6):
                    for j in range(i, 6):
                        Omega_tr[i, j] = info_vals[k]
                        Omega_tr[j, i] = info_vals[k]
                        k += 1
                # Convert from g2o [t,r] to internal [r,t] ordering
                perm = [3, 4, 5, 0, 1, 2]
                Omega_rt = Omega_tr[np.ix_(perm, perm)]
                edges.append({"from": fid, "to": tid, "measurement": T, "information": Omega_rt})
            elif parts[0] == 'FIX':
                fixed_id = int(parts[1])

    n = max(vertices.keys()) + 1
    poses = [vertices[i] for i in range(n)]
    return poses, edges, fixed_id, raw_edge_lines


def write_g2o_output(filepath, poses, raw_edge_lines, fixed_id):
    """Write optimized poses + original edges to g2o format."""
    with open(filepath, "w") as f:
        for i, pose in enumerate(poses):
            x, y, z = pose[0, 3], pose[1, 3], pose[2, 3]
            qx, qy, qz, qw = rot_to_quat(pose[:3, :3])
            qn = np.sqrt(qx**2 + qy**2 + qz**2 + qw**2)
            qx, qy, qz, qw = qx / qn, qy / qn, qz / qn, qw / qn
            f.write(f"VERTEX_SE3:QUAT {i} {x:.10f} {y:.10f} {z:.10f} "
                    f"{qx:.10f} {qy:.10f} {qz:.10f} {qw:.10f}\n")
        f.write(f"FIX {fixed_id}\n")
        for edge_line in raw_edge_lines:
            f.write(edge_line + "\n")


# ---------------------------------------------------------------------------
# SE(3) / SO(3) primitives
# ---------------------------------------------------------------------------

def skew(v):
    return np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])


def exp_so3(omega):
    theta = np.linalg.norm(omega)
    if theta < 1e-10:
        return np.eye(3) + skew(omega)
    K = skew(omega / theta)
    return np.eye(3) + np.sin(theta) * K + (1 - np.cos(theta)) * (K @ K)


def log_so3(R):
    """Logarithmic map SO(3) -> R^3.  Handles angles near 0 and near pi."""
    cos_angle = np.clip((np.trace(R) - 1) / 2, -1, 1)
    angle = np.arccos(cos_angle)
    if angle < 1e-10:
        return np.array([R[2, 1] - R[1, 2],
                         R[0, 2] - R[2, 0],
                         R[1, 0] - R[0, 1]]) * 0.5
    if np.pi - angle < 1e-6:
        S = R + np.eye(3)
        col_sq = np.array([S[0, 0]**2 + S[1, 0]**2 + S[2, 0]**2,
                           S[0, 1]**2 + S[1, 1]**2 + S[2, 1]**2,
                           S[0, 2]**2 + S[1, 2]**2 + S[2, 2]**2])
        best = int(np.argmax(col_sq))
        v = S[:, best].copy()
        v /= np.linalg.norm(v)
        r = np.array([R[2, 1] - R[1, 2], R[0, 2] - R[2, 0], R[1, 0] - R[0, 1]])
        if np.dot(r, v) < 0:
            v = -v
        return v * angle
    return (angle / (2 * np.sin(angle))) * np.array(
        [R[2, 1] - R[1, 2], R[0, 2] - R[2, 0], R[1, 0] - R[0, 1]])


def exp_se3(xi):
    omega, v = xi[:3], xi[3:]
    theta = np.linalg.norm(omega)
    T = np.eye(4)
    if theta < 1e-10:
        T[:3, :3] = np.eye(3) + skew(omega)
        T[:3, 3] = v
    else:
        K = skew(omega)
        R = np.eye(3) + (np.sin(theta) / theta) * K + \
            ((1 - np.cos(theta)) / theta**2) * (K @ K)
        V = np.eye(3) + ((1 - np.cos(theta)) / theta**2) * K + \
            ((theta - np.sin(theta)) / theta**3) * (K @ K)
        T[:3, :3] = R
        T[:3, 3] = V @ v
    return T


def log_se3(T):
    R, t = T[:3, :3], T[:3, 3]
    omega = log_so3(R)
    theta = np.linalg.norm(omega)
    if theta < 1e-6:
        return np.concatenate([omega, t])
    K = skew(omega)
    half_theta = theta / 2.0
    coeff = 1.0 / theta**2 - np.cos(half_theta) / (2.0 * theta * np.sin(half_theta))
    V_inv = np.eye(3) - 0.5 * K + coeff * (K @ K)
    v = V_inv @ t
    return np.concatenate([omega, v])


def inv_pose(T):
    T_inv = np.eye(4)
    T_inv[:3, :3] = T[:3, :3].T
    T_inv[:3, 3] = -T[:3, :3].T @ T[:3, 3]
    return T_inv


# ---------------------------------------------------------------------------
# Pose graph optimizer — robust GNC with Cauchy kernel + outlier rejection
# ---------------------------------------------------------------------------

def _gauss_newton_iterations(poses, edges, fixed_id, num_poses,
                             max_iter=50, cauchy_c2=None):
    """Run Gauss-Newton iterations on the SE(3) manifold.

    If cauchy_c2 is provided, applies Cauchy robust kernel weighting:
    w = cauchy_c2 / (cauchy_c2 + d^2) where d^2 is squared Mahalanobis distance.
    This downweights edges with large residuals (likely outliers).
    """
    eps = 1e-7
    for iteration in range(max_iter):
        dim = 6 * num_poses
        H = np.zeros((dim, dim))
        b = np.zeros(dim)

        for edge in edges:
            i, j = edge["from"], edge["to"]
            z_ij = edge["measurement"]
            Omega = edge["information"]
            T_i, T_j = poses[i], poses[j]
            T_ij_est = inv_pose(T_i) @ T_j
            e0 = log_se3(inv_pose(z_ij) @ T_ij_est)

            # Cauchy robust weighting
            if cauchy_c2 is not None:
                d2 = float(e0 @ Omega @ e0)
                w = cauchy_c2 / (cauchy_c2 + d2)
                Omega_w = w * Omega
            else:
                Omega_w = Omega

            J_i = np.zeros((6, 6))
            J_j = np.zeros((6, 6))
            for k in range(6):
                delta = np.zeros(6)
                delta[k] = eps
                T_i_p = T_i @ exp_se3(delta)
                e_p = log_se3(inv_pose(z_ij) @ (inv_pose(T_i_p) @ T_j))
                J_i[:, k] = (e_p - e0) / eps
                T_j_p = T_j @ exp_se3(delta)
                e_p = log_se3(inv_pose(z_ij) @ (inv_pose(T_i) @ T_j_p))
                J_j[:, k] = (e_p - e0) / eps

            ii, jj = 6 * i, 6 * j
            H[ii:ii+6, ii:ii+6] += J_i.T @ Omega_w @ J_i
            H[ii:ii+6, jj:jj+6] += J_i.T @ Omega_w @ J_j
            H[jj:jj+6, ii:ii+6] += J_j.T @ Omega_w @ J_i
            H[jj:jj+6, jj:jj+6] += J_j.T @ Omega_w @ J_j
            b[ii:ii+6] += J_i.T @ Omega_w @ e0
            b[jj:jj+6] += J_j.T @ Omega_w @ e0

        fix = 6 * fixed_id
        H[fix:fix+6, fix:fix+6] += 1e10 * np.eye(6)

        try:
            dx = np.linalg.solve(H, -b)
        except np.linalg.LinAlgError:
            break

        for p in range(num_poses):
            poses[p] = poses[p] @ exp_se3(dx[6*p:6*p+6])

        if np.linalg.norm(dx) < 1e-6:
            break
    return poses


def optimize_pose_graph(poses, edges, fixed_id):
    """Robust pose graph optimization with graduated non-convexity (GNC).

    Phase 1: GNC using Cauchy kernel — anneals the scale parameter from
    permissive (c^2=1000, nearly non-robust) to strict (c^2=25, strong
    outlier suppression). This progressively downweights outlier edges
    while maintaining convergence to a good local minimum.

    Outlier detection: After GNC convergence, edges with squared
    Mahalanobis distance exceeding a chi-squared threshold are rejected.

    Phase 2: Re-optimize with only inlier edges using standard
    (non-robust) Gauss-Newton for maximum accuracy.
    """
    num_poses = len(poses)
    poses = [p.copy() for p in poses]

    # Phase 1: Graduated Non-Convexity — anneal Cauchy scale
    for c2 in [1000.0, 100.0, 25.0]:
        poses = _gauss_newton_iterations(
            poses, edges, fixed_id, num_poses,
            max_iter=40, cauchy_c2=c2)

    # Outlier detection via squared Mahalanobis distance
    chi2_threshold = 50.0
    outliers = []
    inlier_edges = []
    for idx, edge in enumerate(edges):
        i, j = edge["from"], edge["to"]
        z_ij = edge["measurement"]
        Omega = edge["information"]
        T_ij_est = inv_pose(poses[i]) @ poses[j]
        e = log_se3(inv_pose(z_ij) @ T_ij_est)
        sq_mahal = float(e @ Omega @ e)
        if sq_mahal > chi2_threshold:
            outliers.append({
                "edge_index": idx,
                "from": edge["from"],
                "to": edge["to"]
            })
        else:
            inlier_edges.append(edge)

    # Phase 2: non-robust re-optimization with inlier edges only
    if outliers:
        poses = _gauss_newton_iterations(
            poses, inlier_edges, fixed_id, num_poses,
            max_iter=50)

    return poses, outliers


# ---------------------------------------------------------------------------
# Gnuplot visualization
# ---------------------------------------------------------------------------

def generate_trajectory_plot(initial_poses, optimized_poses):
    """Generate XY trajectory comparison plot using gnuplot."""
    with open("/app/output/initial_traj.dat", "w") as f:
        for pose in initial_poses:
            f.write(f"{pose[0, 3]:.6f} {pose[1, 3]:.6f}\n")
        f.write(f"{initial_poses[0][0, 3]:.6f} {initial_poses[0][1, 3]:.6f}\n")

    with open("/app/output/optimized_traj.dat", "w") as f:
        for pose in optimized_poses:
            f.write(f"{pose[0, 3]:.6f} {pose[1, 3]:.6f}\n")
        f.write(f"{optimized_poses[0][0, 3]:.6f} {optimized_poses[0][1, 3]:.6f}\n")

    script = (
        "set terminal png size 800,800\n"
        "set output '/app/output/trajectory.png'\n"
        "set title 'Pose Graph Optimization: Initial vs Optimized'\n"
        "set xlabel 'X (m)'\n"
        "set ylabel 'Y (m)'\n"
        "set key outside right\n"
        "set size ratio -1\n"
        "set grid\n"
        "plot '/app/output/initial_traj.dat' using 1:2 with linespoints "
        "pt 7 ps 1.0 lw 1.5 title 'Initial', \\\n"
        "     '/app/output/optimized_traj.dat' using 1:2 with linespoints "
        "pt 5 ps 1.0 lw 1.5 title 'Optimized'\n"
    )
    with open("/app/output/plot.gnuplot", "w") as f:
        f.write(script)

    subprocess.run(["gnuplot", "/app/output/plot.gnuplot"], check=True)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    poses, edges, fixed_id, raw_edge_lines = parse_g2o("/app/data/trajectory.g2o")
    initial_poses = [p.copy() for p in poses]

    optimized_poses, outliers = optimize_pose_graph(poses, edges, fixed_id)

    os.makedirs("/app/output", exist_ok=True)

    # poses.json
    poses_out = [{"id": i, "pose": optimized_poses[i].tolist()}
                 for i in range(len(optimized_poses))]
    with open("/app/output/poses.json", "w") as f:
        json.dump(poses_out, f, indent=2)

    # outliers.json
    with open("/app/output/outliers.json", "w") as f:
        json.dump(outliers, f, indent=2)

    # optimized.g2o
    write_g2o_output("/app/output/optimized.g2o", optimized_poses,
                     raw_edge_lines, fixed_id)

    # trajectory.png via gnuplot
    generate_trajectory_plot(initial_poses, optimized_poses)


if __name__ == "__main__":
    main()
