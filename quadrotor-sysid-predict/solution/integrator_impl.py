"""RK4 numerical integrator with quaternion normalization — complete implementation."""

import numpy as np
from dynamics import state_derivatives


def rk4_step(pos, quat, vel, ang_vel, rpms, params, dt):
    """Single RK4 integration step with quaternion renormalization at each sub-step."""
    pos = np.asarray(pos, dtype=np.float64)
    quat = np.asarray(quat, dtype=np.float64)
    vel = np.asarray(vel, dtype=np.float64)
    ang_vel = np.asarray(ang_vel, dtype=np.float64)
    rpms = np.asarray(rpms, dtype=np.float64)

    def f(p, q, v, w):
        return state_derivatives(p, q, v, w, rpms, params)

    # k1
    k1_p, k1_q, k1_v, k1_w = f(pos, quat, vel, ang_vel)

    # k2 (midpoint using k1)
    p2 = pos + 0.5 * dt * k1_p
    q2 = quat + 0.5 * dt * k1_q
    q2 = q2 / np.linalg.norm(q2)
    v2 = vel + 0.5 * dt * k1_v
    w2 = ang_vel + 0.5 * dt * k1_w
    k2_p, k2_q, k2_v, k2_w = f(p2, q2, v2, w2)

    # k3 (midpoint using k2)
    p3 = pos + 0.5 * dt * k2_p
    q3 = quat + 0.5 * dt * k2_q
    q3 = q3 / np.linalg.norm(q3)
    v3 = vel + 0.5 * dt * k2_v
    w3 = ang_vel + 0.5 * dt * k2_w
    k3_p, k3_q, k3_v, k3_w = f(p3, q3, v3, w3)

    # k4 (endpoint using k3)
    p4 = pos + dt * k3_p
    q4 = quat + dt * k3_q
    q4 = q4 / np.linalg.norm(q4)
    v4 = vel + dt * k3_v
    w4 = ang_vel + dt * k3_w
    k4_p, k4_q, k4_v, k4_w = f(p4, q4, v4, w4)

    # Weighted combination
    new_pos = pos + (dt / 6.0) * (k1_p + 2*k2_p + 2*k3_p + k4_p)
    new_quat = quat + (dt / 6.0) * (k1_q + 2*k2_q + 2*k3_q + k4_q)
    new_quat = new_quat / np.linalg.norm(new_quat)
    new_vel = vel + (dt / 6.0) * (k1_v + 2*k2_v + 2*k3_v + k4_v)
    new_ang_vel = ang_vel + (dt / 6.0) * (k1_w + 2*k2_w + 2*k3_w + k4_w)

    return new_pos, new_quat, new_vel, new_ang_vel


def simulate(initial_state, rpm_sequence, params, dt):
    """Simulate a full trajectory by repeatedly applying rk4_step."""
    T = len(rpm_sequence)
    positions = np.zeros((T + 1, 3))
    quaternions = np.zeros((T + 1, 4))
    velocities = np.zeros((T + 1, 3))
    angular_velocities = np.zeros((T + 1, 3))

    pos = np.asarray(initial_state['pos'], dtype=np.float64).copy()
    quat = np.asarray(initial_state['quat'], dtype=np.float64).copy()
    vel_state = np.asarray(initial_state['vel'], dtype=np.float64).copy()
    ang_vel = np.asarray(initial_state['ang_vel'], dtype=np.float64).copy()

    positions[0] = pos
    quaternions[0] = quat
    velocities[0] = vel_state
    angular_velocities[0] = ang_vel

    for t in range(T):
        pos, quat, vel_state, ang_vel = rk4_step(
            pos, quat, vel_state, ang_vel, rpm_sequence[t], params, dt
        )
        positions[t + 1] = pos
        quaternions[t + 1] = quat
        velocities[t + 1] = vel_state
        angular_velocities[t + 1] = ang_vel

    return {
        'positions': positions,
        'quaternions': quaternions,
        'velocities': velocities,
        'angular_velocities': angular_velocities,
    }
