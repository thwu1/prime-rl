"""Generate synthetic quadrotor flight data for system identification."""

import numpy as np
import json
import os

# Ground truth parameters (to be identified by the agent)
MASS = 0.027
KF = 3.16e-10
KT = 7.94e-12

# Known parameters
ARM_LENGTH = 0.0397
IXX = 1.4e-5
IYY = 1.4e-5
IZZ = 2.17e-5
G = 9.81

DT = 1.0 / 500
N_STEPS = 1000


def quat_multiply(q1, q2):
    """Hamilton quaternion multiplication, scalar-last [x, y, z, w]."""
    x1, y1, z1, w1 = q1
    x2, y2, z2, w2 = q2
    return np.array([
        w1*x2 + x1*w2 + y1*z2 - z1*y2,
        w1*y2 - x1*z2 + y1*w2 + z1*x2,
        w1*z2 + x1*y2 - y1*x2 + z1*w2,
        w1*w2 - x1*x2 - y1*y2 - z1*z2,
    ])


def quat_to_rotmat(q):
    """Convert scalar-last quaternion [x,y,z,w] to 3x3 rotation matrix."""
    x, y, z, w = q
    return np.array([
        [1 - 2*(y*y + z*z), 2*(x*y - z*w), 2*(x*z + y*w)],
        [2*(x*y + z*w), 1 - 2*(x*x + z*z), 2*(y*z - x*w)],
        [2*(x*z - y*w), 2*(y*z + x*w), 1 - 2*(x*x + y*y)],
    ])


def dynamics_step(pos, vel, quat, ang_vel, rpms):
    """Single forward Euler integration step."""
    rpm_sq = rpms ** 2
    f = KF * rpm_sq

    F_total = np.sum(f)
    tau_x = ARM_LENGTH * (f[3] - f[1])
    tau_y = ARM_LENGTH * (f[0] - f[2])
    tau_z = KT * (-rpm_sq[0] + rpm_sq[1] - rpm_sq[2] + rpm_sq[3])

    R = quat_to_rotmat(quat)
    acc = R @ np.array([0.0, 0.0, F_total]) / MASS + np.array([0.0, 0.0, -G])

    J_diag = np.array([IXX, IYY, IZZ])
    J_inv_diag = 1.0 / J_diag
    tau = np.array([tau_x, tau_y, tau_z])
    J_omega = J_diag * ang_vel
    ang_acc = J_inv_diag * (tau - np.cross(ang_vel, J_omega))

    omega_q = np.array([ang_vel[0], ang_vel[1], ang_vel[2], 0.0])
    q_dot = 0.5 * quat_multiply(quat, omega_q)

    pos_new = pos + vel * DT
    vel_new = vel + acc * DT
    ang_vel_new = ang_vel + ang_acc * DT
    quat_new = quat + q_dot * DT
    quat_new = quat_new / np.linalg.norm(quat_new)

    return pos_new, vel_new, quat_new, ang_vel_new


def main():
    rpm_hover = np.sqrt(MASS * G / (4 * KF))
    t = np.arange(N_STEPS) * DT

    # Multi-frequency excitation to make all parameters identifiable
    collective = 1200 * np.sin(2 * np.pi * 2.0 * t)
    roll_cmd = 800 * np.sin(2 * np.pi * 3.0 * t)
    pitch_cmd = 700 * np.sin(2 * np.pi * 4.5 * t)
    yaw_cmd = 1000 * np.sin(2 * np.pi * 1.5 * t)

    # Plus-configuration mixing of perturbations into motor commands
    motor_rpms = np.zeros((N_STEPS, 4))
    motor_rpms[:, 0] = rpm_hover + collective + pitch_cmd - yaw_cmd
    motor_rpms[:, 1] = rpm_hover + collective - roll_cmd + yaw_cmd
    motor_rpms[:, 2] = rpm_hover + collective - pitch_cmd - yaw_cmd
    motor_rpms[:, 3] = rpm_hover + collective + roll_cmd + yaw_cmd

    # Simulate trajectory
    pos = np.array([0.0, 0.0, 0.5])
    vel = np.zeros(3)
    quat = np.array([0.0, 0.0, 0.0, 1.0])
    ang_vel = np.zeros(3)

    positions = np.zeros((N_STEPS + 1, 3))
    velocities = np.zeros((N_STEPS + 1, 3))
    quaternions = np.zeros((N_STEPS + 1, 4))
    angular_velocities = np.zeros((N_STEPS + 1, 3))

    positions[0] = pos
    velocities[0] = vel
    quaternions[0] = quat
    angular_velocities[0] = ang_vel

    for i in range(N_STEPS):
        pos, vel, quat, ang_vel = dynamics_step(
            pos, vel, quat, ang_vel, motor_rpms[i]
        )
        positions[i + 1] = pos
        velocities[i + 1] = vel
        quaternions[i + 1] = quat
        angular_velocities[i + 1] = ang_vel

    os.makedirs("/app/data", exist_ok=True)
    np.savez(
        "/app/data/flight_data.npz",
        timestamps=np.arange(N_STEPS + 1) * DT,
        positions=positions,
        quaternions=quaternions,
        velocities=velocities,
        angular_velocities=angular_velocities,
        motor_rpms=motor_rpms,
    )
    print(f"Generated flight data: {N_STEPS} steps, hover RPM={rpm_hover:.1f}")
    print(f"Position range: z=[{positions[:,2].min():.4f}, {positions[:,2].max():.4f}]")


if __name__ == "__main__":
    main()
