#!/usr/bin/env python3
"""Generate training and test data for the quadrotor sysid task.

This script runs during Docker build to create flight recordings and test inputs.
It is deleted after execution to prevent leaking true parameter values.
"""

import numpy as np
import os

# ---- True physical parameters (unknown to the agent) ----
TRUE_MASS = 0.027
TRUE_KF = 3.16e-10
TRUE_KM = 7.94e-12
ARM_LENGTH = 0.0397
J = np.diag([1.4e-5, 1.4e-5, 2.17e-5])
J_INV = np.linalg.inv(J)
DRAG = np.diag([9.1785e-7, 9.1785e-7, 10.311e-7])
G = 9.81
DT = 0.002

PARAMS = {
    'mass': TRUE_MASS,
    'k_f': TRUE_KF,
    'k_m': TRUE_KM,
    'arm_length': ARM_LENGTH,
    'J': J,
    'J_inv': J_INV,
    'drag': DRAG,
    'g': G,
}


# ---- Reference dynamics implementation ----

def compute_body_wrench(rpms, k_f, k_m, arm_length):
    d = arm_length / np.sqrt(2.0)
    thrusts = k_f * rpms ** 2
    moments = k_m * rpms ** 2
    fz = np.sum(thrusts)
    tau_x = d * (thrusts[0] + thrusts[1] - thrusts[2] - thrusts[3])
    tau_y = d * (-thrusts[0] + thrusts[1] + thrusts[2] - thrusts[3])
    tau_z = moments[0] - moments[1] + moments[2] - moments[3]
    return np.array([0.0, 0.0, fz]), np.array([tau_x, tau_y, tau_z])


def quat_to_rotation_matrix(q):
    x, y, z, w = q
    return np.array([
        [1 - 2*(y*y + z*z), 2*(x*y - z*w),     2*(x*z + y*w)],
        [2*(x*y + z*w),     1 - 2*(x*x + z*z), 2*(y*z - x*w)],
        [2*(x*z - y*w),     2*(y*z + x*w),     1 - 2*(x*x + y*y)]
    ])


def quat_multiply(q1, q2):
    x1, y1, z1, w1 = q1
    x2, y2, z2, w2 = q2
    return np.array([
        w1*x2 + x1*w2 + y1*z2 - z1*y2,
        w1*y2 - x1*z2 + y1*w2 + z1*x2,
        w1*z2 + x1*y2 - y1*x2 + z1*w2,
        w1*w2 - x1*x2 - y1*y2 - z1*z2,
    ])


def state_derivatives(pos, quat, vel, ang_vel, rpms, params):
    F_body, tau_body = compute_body_wrench(
        rpms, params['k_f'], params['k_m'], params['arm_length']
    )
    R = quat_to_rotation_matrix(quat)
    mass = params['mass']
    F_world = R @ F_body + np.array([0.0, 0.0, -mass * params['g']]) - params['drag'] @ vel
    d_pos = vel.copy()
    omega_quat = np.array([ang_vel[0], ang_vel[1], ang_vel[2], 0.0])
    d_quat = 0.5 * quat_multiply(quat, omega_quat)
    d_vel = F_world / mass
    d_ang_vel = params['J_inv'] @ (tau_body - np.cross(ang_vel, params['J'] @ ang_vel))
    return d_pos, d_quat, d_vel, d_ang_vel


def rk4_step(pos, quat, vel, ang_vel, rpms, params, dt):
    def f(p, q, v, w):
        return state_derivatives(p, q, v, w, rpms, params)

    k1 = f(pos, quat, vel, ang_vel)

    p2 = pos + 0.5 * dt * k1[0]
    q2 = quat + 0.5 * dt * k1[1]
    q2 = q2 / np.linalg.norm(q2)
    v2 = vel + 0.5 * dt * k1[2]
    w2 = ang_vel + 0.5 * dt * k1[3]
    k2 = f(p2, q2, v2, w2)

    p3 = pos + 0.5 * dt * k2[0]
    q3 = quat + 0.5 * dt * k2[1]
    q3 = q3 / np.linalg.norm(q3)
    v3 = vel + 0.5 * dt * k2[2]
    w3 = ang_vel + 0.5 * dt * k2[3]
    k3 = f(p3, q3, v3, w3)

    p4 = pos + dt * k3[0]
    q4 = quat + dt * k3[1]
    q4 = q4 / np.linalg.norm(q4)
    v4 = vel + dt * k3[2]
    w4 = ang_vel + dt * k3[3]
    k4 = f(p4, q4, v4, w4)

    new_pos = pos + (dt / 6.0) * (k1[0] + 2*k2[0] + 2*k3[0] + k4[0])
    new_quat = quat + (dt / 6.0) * (k1[1] + 2*k2[1] + 2*k3[1] + k4[1])
    new_quat = new_quat / np.linalg.norm(new_quat)
    new_vel = vel + (dt / 6.0) * (k1[2] + 2*k2[2] + 2*k3[2] + k4[2])
    new_ang_vel = ang_vel + (dt / 6.0) * (k1[3] + 2*k2[3] + 2*k3[3] + k4[3])

    return new_pos, new_quat, new_vel, new_ang_vel


def simulate(initial_state, rpm_sequence, params, dt):
    T = len(rpm_sequence)
    positions = np.zeros((T + 1, 3))
    quaternions = np.zeros((T + 1, 4))
    velocities = np.zeros((T + 1, 3))
    angular_velocities = np.zeros((T + 1, 3))

    pos = initial_state['pos'].copy()
    quat = initial_state['quat'].copy()
    vel = initial_state['vel'].copy()
    ang_vel = initial_state['ang_vel'].copy()

    positions[0] = pos
    quaternions[0] = quat
    velocities[0] = vel
    angular_velocities[0] = ang_vel

    for t in range(T):
        pos, quat, vel, ang_vel = rk4_step(
            pos, quat, vel, ang_vel, rpm_sequence[t], params, dt
        )
        positions[t + 1] = pos
        quaternions[t + 1] = quat
        velocities[t + 1] = vel
        angular_velocities[t + 1] = ang_vel

    return {
        'positions': positions,
        'quaternions': quaternions,
        'velocities': velocities,
        'angular_velocities': angular_velocities,
    }


# ---- Data generation ----

def add_noise_and_save(path, traj, rpms, rng, T):
    noise_pos = rng.normal(0, 5e-5, traj['positions'].shape)
    noise_vel = rng.normal(0, 5e-4, traj['velocities'].shape)
    noise_angvel = rng.normal(0, 5e-4, traj['angular_velocities'].shape)
    np.savez(
        path,
        times=np.arange(T + 1) * DT,
        positions=traj['positions'] + noise_pos,
        quaternions=traj['quaternions'],  # no quaternion noise
        velocities=traj['velocities'] + noise_vel,
        angular_velocities=traj['angular_velocities'] + noise_angvel,
        rotor_rpms=rpms,
    )
    print(f"  Saved {path}: {T} steps, final pos = {traj['positions'][-1]}")


def main():
    os.makedirs('/app/data', exist_ok=True)
    rng = np.random.default_rng(42)
    hover_rpm = np.sqrt(TRUE_MASS * G / (4 * TRUE_KF))
    print(f"Hover RPM: {hover_rpm:.2f}")

    identity_quat = np.array([0.0, 0.0, 0.0, 1.0])
    hover_start = {
        'pos': np.array([0.0, 0.0, 1.0]),
        'quat': identity_quat.copy(),
        'vel': np.zeros(3),
        'ang_vel': np.zeros(3),
    }

    # Training 1: Hover (2 seconds, 1000 steps)
    T1 = 1000
    rpms1 = np.full((T1, 4), hover_rpm)
    traj1 = simulate(hover_start, rpms1, PARAMS, DT)
    add_noise_and_save('/app/data/training_hover.npz', traj1, rpms1, rng, T1)

    # Training 2: Vertical step response (1 second, 500 steps)
    T2 = 500
    rpms2 = np.full((T2, 4), hover_rpm)
    rpms2[:250, :] = hover_rpm * 1.05  # +5% thrust for first 0.5s
    traj2 = simulate(hover_start, rpms2, PARAMS, DT)
    add_noise_and_save('/app/data/training_vstep.npz', traj2, rpms2, rng, T2)

    # Training 3: Roll perturbation (1 second, 500 steps)
    T3 = 500
    rpms3 = np.full((T3, 4), hover_rpm)
    rpms3[:100, 0] += 200  # Motor 0 (+d, +d)
    rpms3[:100, 1] += 200  # Motor 1 (-d, +d)
    rpms3[:100, 2] -= 200  # Motor 2 (-d, -d)
    rpms3[:100, 3] -= 200  # Motor 3 (+d, -d)
    traj3 = simulate(hover_start, rpms3, PARAMS, DT)
    add_noise_and_save('/app/data/training_roll.npz', traj3, rpms3, rng, T3)

    # Training 4: Yaw perturbation (1 second, 500 steps)
    T4 = 500
    rpms4 = np.full((T4, 4), hover_rpm)
    rpms4[:100, 0] += 500  # CW motors up
    rpms4[:100, 2] += 500
    rpms4[:100, 1] -= 500  # CCW motors down
    rpms4[:100, 3] -= 500
    traj4 = simulate(hover_start, rpms4, PARAMS, DT)
    add_noise_and_save('/app/data/training_yaw.npz', traj4, rpms4, rng, T4)

    # ---- Test scenarios ----
    T_test = 500

    # Scenario 1: Above-hover thrust from low altitude
    s1_rpms = np.full((T_test, 4), 15000.0)
    s1_state = {
        'pos': np.array([0.0, 0.0, 0.5]),
        'quat': identity_quat.copy(),
        'vel': np.zeros(3),
        'ang_vel': np.zeros(3),
    }

    # Scenario 2: Tilted start (15 deg pitch) with hover RPMs
    pitch_angle = 15 * np.pi / 180
    s2_rpms = np.full((T_test, 4), hover_rpm)
    s2_state = {
        'pos': np.array([1.0, 0.0, 1.0]),
        'quat': np.array([0.0, np.sin(pitch_angle / 2), 0.0, np.cos(pitch_angle / 2)]),
        'vel': np.zeros(3),
        'ang_vel': np.zeros(3),
    }

    # Scenario 3: Forward velocity with oscillating RPMs
    t_arr = np.arange(T_test) * DT
    s3_rpms = np.column_stack([
        hover_rpm + 1000 * np.sin(2 * np.pi * 2 * t_arr),
        hover_rpm + 1000 * np.sin(2 * np.pi * 2 * t_arr + np.pi / 2),
        hover_rpm + 1000 * np.sin(2 * np.pi * 2 * t_arr + np.pi),
        hover_rpm + 1000 * np.sin(2 * np.pi * 2 * t_arr + 3 * np.pi / 2),
    ])
    s3_state = {
        'pos': np.array([0.0, 0.0, 2.0]),
        'quat': identity_quat.copy(),
        'vel': np.array([0.5, 0.0, 0.0]),
        'ang_vel': np.zeros(3),
    }

    np.savez(
        '/app/data/test_inputs.npz',
        scenario_1_pos0=s1_state['pos'],
        scenario_1_quat0=s1_state['quat'],
        scenario_1_vel0=s1_state['vel'],
        scenario_1_angvel0=s1_state['ang_vel'],
        scenario_1_rpms=s1_rpms,
        scenario_2_pos0=s2_state['pos'],
        scenario_2_quat0=s2_state['quat'],
        scenario_2_vel0=s2_state['vel'],
        scenario_2_angvel0=s2_state['ang_vel'],
        scenario_2_rpms=s2_rpms,
        scenario_3_pos0=s3_state['pos'],
        scenario_3_quat0=s3_state['quat'],
        scenario_3_vel0=s3_state['vel'],
        scenario_3_angvel0=s3_state['ang_vel'],
        scenario_3_rpms=s3_rpms,
    )
    print("  Saved test_inputs.npz")
    print("Data generation complete.")


if __name__ == '__main__':
    main()
