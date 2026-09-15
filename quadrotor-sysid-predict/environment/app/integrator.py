"""Numerical integration for quadrotor dynamics.

Implement integration of the equations of motion defined in dynamics.py.
"""

import numpy as np


def rk4_step(pos, quat, vel, ang_vel, rpms, params, dt):
    """Single fourth-order Runge-Kutta integration step for the quadrotor state.

    Args:
        pos: (3,) position [m]
        quat: (4,) quaternion [qx, qy, qz, qw] (unit norm)
        vel: (3,) velocity [m/s]
        ang_vel: (3,) angular velocity [rad/s]
        rpms: (4,) motor speeds [RPM] (constant during this step)
        params: dict of physical parameters (see dynamics.state_derivatives)
        dt: float, timestep [s]

    Returns:
        new_pos: (3,) updated position
        new_quat: (4,) updated quaternion (unit norm)
        new_vel: (3,) updated velocity
        new_ang_vel: (3,) updated angular velocity
    """
    raise NotImplementedError("Implement rk4_step")


def simulate(initial_state, rpm_sequence, params, dt):
    """Simulate a trajectory given initial state and a sequence of motor commands.

    Args:
        initial_state: dict with keys pos (3,), quat (4,), vel (3,), ang_vel (3,)
        rpm_sequence: (T, 4) motor speeds over time [RPM]
        params: dict of physical parameters
        dt: float, timestep [s]

    Returns:
        dict with keys:
            positions: (T+1, 3)
            quaternions: (T+1, 4)
            velocities: (T+1, 3)
            angular_velocities: (T+1, 3)
    """
    raise NotImplementedError("Implement simulate")
