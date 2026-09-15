"""Quadrotor rigid body dynamics — complete implementation."""

import numpy as np


def compute_body_wrench(rpms, k_f, k_m, arm_length):
    """Compute body-frame force and torque from motor RPMs.

    X-configuration mixing matrix with motors at (+-d, +-d, 0).
    """
    d = arm_length / np.sqrt(2.0)
    rpms = np.asarray(rpms, dtype=np.float64)
    rpm_sq = rpms ** 2
    thrusts = k_f * rpm_sq
    moments = k_m * rpm_sq

    fz = np.sum(thrusts)
    tau_x = d * (thrusts[0] + thrusts[1] - thrusts[2] - thrusts[3])
    tau_y = d * (-thrusts[0] + thrusts[1] + thrusts[2] - thrusts[3])
    # Reaction torques: CW motors (0,2) give +z, CCW motors (1,3) give -z
    tau_z = moments[0] - moments[1] + moments[2] - moments[3]

    force_body = np.array([0.0, 0.0, fz])
    torque_body = np.array([tau_x, tau_y, tau_z])
    return force_body, torque_body


def quat_to_rotation_matrix(q):
    """Convert quaternion [qx, qy, qz, qw] to 3x3 rotation matrix (body-to-world)."""
    q = np.asarray(q, dtype=np.float64)
    x, y, z, w = q
    return np.array([
        [1 - 2*(y*y + z*z), 2*(x*y - z*w),     2*(x*z + y*w)],
        [2*(x*y + z*w),     1 - 2*(x*x + z*z), 2*(y*z - x*w)],
        [2*(x*z - y*w),     2*(y*z + x*w),     1 - 2*(x*x + y*y)]
    ])


def quat_multiply(q1, q2):
    """Hamilton quaternion product q1 * q2 in [qx, qy, qz, qw] convention."""
    q1 = np.asarray(q1, dtype=np.float64)
    q2 = np.asarray(q2, dtype=np.float64)
    x1, y1, z1, w1 = q1
    x2, y2, z2, w2 = q2
    return np.array([
        w1*x2 + x1*w2 + y1*z2 - z1*y2,
        w1*y2 - x1*z2 + y1*w2 + z1*x2,
        w1*z2 + x1*y2 - y1*x2 + z1*w2,
        w1*w2 - x1*x2 - y1*y2 - z1*z2,
    ])


def state_derivatives(pos, quat, vel, ang_vel, rpms, params):
    """Compute full state derivatives for the quadrotor."""
    pos = np.asarray(pos, dtype=np.float64)
    quat = np.asarray(quat, dtype=np.float64)
    vel = np.asarray(vel, dtype=np.float64)
    ang_vel = np.asarray(ang_vel, dtype=np.float64)
    rpms = np.asarray(rpms, dtype=np.float64)

    mass = params['mass']
    k_f = params['k_f']
    k_m = params['k_m']
    arm_length = params['arm_length']
    J = params['J']
    J_inv = params['J_inv']
    drag = params['drag']
    g = params['g']

    # Body-frame forces and torques
    F_body, tau_body = compute_body_wrench(rpms, k_f, k_m, arm_length)

    # Rotation from body to world
    R = quat_to_rotation_matrix(quat)

    # World-frame net force: thrust + gravity + drag
    F_world = R @ F_body + np.array([0.0, 0.0, -mass * g]) - drag @ vel

    # Position derivative = velocity
    d_pos = vel.copy()

    # Quaternion derivative: d(q)/dt = 0.5 * q (*) [omega_body, 0]
    omega_quat = np.array([ang_vel[0], ang_vel[1], ang_vel[2], 0.0])
    d_quat = 0.5 * quat_multiply(quat, omega_quat)

    # Translational acceleration
    d_vel = F_world / mass

    # Angular acceleration: Euler's equation
    d_ang_vel = J_inv @ (tau_body - np.cross(ang_vel, J @ ang_vel))

    return d_pos, d_quat, d_vel, d_ang_vel
