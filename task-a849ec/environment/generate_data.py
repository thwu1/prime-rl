#!/usr/bin/env python3
"""Generate synthetic SLAM trajectory data for evaluation testing.
This script is run at Docker build time to populate /app/data/."""
import numpy as np
import os


def rotation_matrix_from_axis_angle(axis, angle):
    axis = axis / np.linalg.norm(axis)
    K = np.array([[0, -axis[2], axis[1]],
                  [axis[2], 0, -axis[0]],
                  [-axis[1], axis[0], 0]])
    return np.eye(3) + np.sin(angle) * K + (1 - np.cos(angle)) * (K @ K)


def rotmat_to_quaternion(R):
    """Rotation matrix to quaternion [qx, qy, qz, qw]."""
    tr = np.trace(R)
    if tr > 0:
        s = 0.5 / np.sqrt(tr + 1.0)
        w = 0.25 / s
        x = (R[2, 1] - R[1, 2]) * s
        y = (R[0, 2] - R[2, 0]) * s
        z = (R[1, 0] - R[0, 1]) * s
    elif R[0, 0] > R[1, 1] and R[0, 0] > R[2, 2]:
        s = 2.0 * np.sqrt(1.0 + R[0, 0] - R[1, 1] - R[2, 2])
        w = (R[2, 1] - R[1, 2]) / s
        x = 0.25 * s
        y = (R[0, 1] + R[1, 0]) / s
        z = (R[0, 2] + R[2, 0]) / s
    elif R[1, 1] > R[2, 2]:
        s = 2.0 * np.sqrt(1.0 + R[1, 1] - R[0, 0] - R[2, 2])
        w = (R[0, 2] - R[2, 0]) / s
        x = (R[0, 1] + R[1, 0]) / s
        y = 0.25 * s
        z = (R[1, 2] + R[2, 1]) / s
    else:
        s = 2.0 * np.sqrt(1.0 + R[2, 2] - R[0, 0] - R[1, 1])
        w = (R[1, 0] - R[0, 1]) / s
        x = (R[0, 2] + R[2, 0]) / s
        y = (R[1, 2] + R[2, 1]) / s
        z = 0.25 * s
    return np.array([x, y, z, w])


def generate_trajectory(N=150):
    t = np.linspace(0, 4 * np.pi, N)
    positions = np.zeros((N, 3))
    positions[:, 0] = 5.0 * np.sin(t)
    positions[:, 1] = 2.5 * np.sin(2 * t)
    positions[:, 2] = 0.3 * np.sin(3 * t) + 1.0
    rotations = []
    for i in range(N):
        if i < N - 1:
            fwd = positions[i + 1] - positions[i]
        else:
            fwd = positions[i] - positions[i - 1]
        fwd = fwd / (np.linalg.norm(fwd) + 1e-10)
        up = np.array([0, 0, 1.0])
        right = np.cross(fwd, up)
        rn = np.linalg.norm(right)
        if rn < 1e-6:
            right = np.array([1, 0, 0.0])
        else:
            right = right / rn
        up = np.cross(right, fwd)
        up = up / np.linalg.norm(up)
        R = np.column_stack([right, up, fwd])
        if np.linalg.det(R) < 0:
            R[:, 0] = -R[:, 0]
        rotations.append(R)
    return positions, rotations


def write_kitti(positions, rotations, filepath):
    with open(filepath, 'w') as f:
        for i in range(len(positions)):
            R, t = rotations[i], positions[i]
            vals = [R[0, 0], R[0, 1], R[0, 2], t[0],
                    R[1, 0], R[1, 1], R[1, 2], t[1],
                    R[2, 0], R[2, 1], R[2, 2], t[2]]
            f.write(' '.join(f'{v:.10f}' for v in vals) + '\n')


def write_tum(positions, rotations, timestamps, filepath):
    with open(filepath, 'w') as f:
        f.write('# ground truth trajectory\n')
        f.write('# timestamp tx ty tz qx qy qz qw\n')
        f.write('#\n')
        for i in range(len(positions)):
            q = rotmat_to_quaternion(rotations[i])
            vals = [timestamps[i], positions[i][0], positions[i][1], positions[i][2],
                    q[0], q[1], q[2], q[3]]
            f.write(' '.join(f'{v:.6f}' for v in vals) + '\n')


def write_euroc(positions, rotations, timestamps_ns, filepath):
    with open(filepath, 'w') as f:
        f.write('#timestamp [ns],p_RS_R_x [m],p_RS_R_y [m],p_RS_R_z [m],q_RS_w [],q_RS_x [],q_RS_y [],q_RS_z [],v_RS_R_x [m s^-1],v_RS_R_y [m s^-1],v_RS_R_z [m s^-1],b_w_RS_S_x [rad s^-1],b_w_RS_S_y [rad s^-1],b_w_RS_S_z [rad s^-1],b_a_RS_S_x [m s^-2],b_a_RS_S_y [m s^-2],b_a_RS_S_z [m s^-2]\n')
        for i in range(len(positions)):
            q = rotmat_to_quaternion(rotations[i])
            ts = int(timestamps_ns[i])
            # EuRoC quaternion order: qw, qx, qy, qz (scalar-first)
            f.write(f'{ts},{positions[i][0]:.10f},{positions[i][1]:.10f},{positions[i][2]:.10f},{q[3]:.10f},{q[0]:.10f},{q[1]:.10f},{q[2]:.10f},0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0\n')


def main():
    os.makedirs('/app/data', exist_ok=True)
    N = 150
    positions, rotations = generate_trajectory(N)

    # === KITTI ===
    np.random.seed(42)
    R_k = rotation_matrix_from_axis_angle(np.array([0.1, 0.3, 0.2]), 0.15)
    t_k = np.array([0.5, -0.3, 0.2])
    est_pos_k = (R_k @ positions.T).T + t_k
    est_pos_k += np.random.normal(0, 0.03, est_pos_k.shape)
    est_rot_k = [R_k @ R for R in rotations]
    write_kitti(positions, rotations, '/app/data/kitti_gt.txt')
    write_kitti(est_pos_k, est_rot_k, '/app/data/kitti_est.txt')

    # === TUM ===
    np.random.seed(123)
    R_t = rotation_matrix_from_axis_angle(np.array([0.0, 1.0, 0.0]), 0.25)
    t_t = np.array([-1.0, 0.5, 0.8])
    ts_gt = np.arange(N, dtype=float) * 0.033 + 1000.0
    ts_est = ts_gt + np.random.uniform(-0.005, 0.005, N)
    est_pos_t = (R_t @ positions.T).T + t_t
    est_pos_t += np.random.normal(0, 0.04, est_pos_t.shape)
    est_rot_t = [R_t @ R for R in rotations]
    write_tum(positions, rotations, ts_gt, '/app/data/tum_gt.txt')
    write_tum(est_pos_t, est_rot_t, ts_est, '/app/data/tum_est.txt')

    # === EuRoC ===
    np.random.seed(456)
    scale_e = 1.35
    R_e = rotation_matrix_from_axis_angle(np.array([0.5, 0.5, 0.0]), 0.3)
    t_e = np.array([2.0, -1.0, 0.5])
    ts_ns = (np.arange(N, dtype=float) * 50000000 + 1403636580838555648).astype(np.int64)
    ts_est_e = ts_ns.astype(float) * 1e-9 + np.random.uniform(-0.01, 0.01, N)
    est_pos_e = scale_e * (R_e @ positions.T).T + t_e
    est_pos_e += np.random.normal(0, 0.05, est_pos_e.shape)
    est_rot_e = [R_e @ R for R in rotations]
    write_euroc(positions, rotations, ts_ns, '/app/data/euroc_gt.csv')
    write_tum(est_pos_e, est_rot_e, ts_est_e, '/app/data/euroc_est.txt')

    # === TUM with outliers (for RANSAC testing) ===
    # Deterministically corrupt every 10th pose with a large offset
    est_pos_outlier = est_pos_t.copy()
    outlier_indices = list(range(0, N, 10))  # 15 outliers
    for idx in outlier_indices:
        est_pos_outlier[idx] += np.array([5.0, -3.0, 4.0])
    write_tum(est_pos_outlier, est_rot_t, ts_est, '/app/data/tum_outliers_est.txt')

    print("Data generation complete.")


if __name__ == '__main__':
    main()
