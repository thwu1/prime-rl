"""Quadrotor rigid body dynamics.

Complete the functions below to model first-principles dynamics for a
Crazyflie 2.x quadrotor.

Conventions:
- Quaternion format: [qx, qy, qz, qw] (scalar-last)
- Motor layout (X-configuration, viewed from above):
      Motor 0 (+d, +d, 0) - CW   (spin_dir = +1)
      Motor 1 (-d, +d, 0) - CCW  (spin_dir = -1)
      Motor 2 (-d, -d, 0) - CW   (spin_dir = +1)
      Motor 3 (+d, -d, 0) - CCW  (spin_dir = -1)
  where d = arm_length / sqrt(2)
- Thrust per motor: F_i = k_f * rpm_i^2 (along body +z axis)
- Reaction torque per motor: M_i = k_m * rpm_i^2 (sign per spin direction)
- All quantities in SI units
"""

import numpy as np


def compute_body_wrench(rpms, k_f, k_m, arm_length):
    """Compute total body-frame force and torque produced by four motors.

    Args:
        rpms: (4,) motor speeds in RPM
        k_f: thrust coefficient [N/RPM^2]
        k_m: torque coefficient [N*m/RPM^2]
        arm_length: center-to-motor distance [m]

    Returns:
        force_body: (3,) net force in body frame [N]
        torque_body: (3,) net torque in body frame [N*m]
    """
    raise NotImplementedError("Implement compute_body_wrench")


def quat_to_rotation_matrix(q):
    """Convert quaternion [qx, qy, qz, qw] to 3x3 body-to-world rotation matrix.

    Args:
        q: (4,) quaternion [qx, qy, qz, qw]

    Returns:
        R: (3, 3) rotation matrix (v_world = R @ v_body)
    """
    raise NotImplementedError("Implement quat_to_rotation_matrix")


def quat_multiply(q1, q2):
    """Hamilton product of two quaternions in [qx, qy, qz, qw] convention.

    Args:
        q1: (4,) first quaternion
        q2: (4,) second quaternion

    Returns:
        q: (4,) product quaternion
    """
    raise NotImplementedError("Implement quat_multiply")


def state_derivatives(pos, quat, vel, ang_vel, rpms, params):
    """Compute time derivatives of the full quadrotor state.

    Args:
        pos: (3,) position [m]
        quat: (4,) quaternion [qx, qy, qz, qw]
        vel: (3,) velocity in world frame [m/s]
        ang_vel: (3,) angular velocity in body frame [rad/s]
        rpms: (4,) motor speeds [RPM]
        params: dict with keys: mass, k_f, k_m, arm_length,
                J (3x3), J_inv (3x3), drag (3x3), g

    Returns:
        d_pos: (3,) position derivative
        d_quat: (4,) quaternion derivative
        d_vel: (3,) acceleration in world frame
        d_ang_vel: (3,) angular acceleration in body frame
    """
    raise NotImplementedError("Implement state_derivatives")
