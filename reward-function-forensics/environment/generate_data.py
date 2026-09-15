#!/usr/bin/env python3
"""Generate trajectory data and training history database for the reward forensics task.

Uses CORRECT implementations to generate reference data.
This file is used only during Docker build and is NOT present
in the final container image (multi-stage build).
"""

import numpy as np
import os
import sqlite3


def create_training_history_db(db_path):
    """Create SQLite database with historical training experiment data."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE training_runs (
            run_id INTEGER PRIMARY KEY,
            run_name TEXT NOT NULL,
            reward_version TEXT NOT NULL,
            w_tracking_lin_vel REAL NOT NULL,
            w_tracking_ang_vel REAL NOT NULL,
            w_lin_vel_z REAL NOT NULL,
            w_ang_vel_xy REAL NOT NULL,
            w_orientation REAL NOT NULL,
            w_action_rate REAL NOT NULL,
            w_torques REAL NOT NULL,
            w_joint_limits REAL NOT NULL,
            w_feet_air_time REAL NOT NULL,
            w_feet_clearance REAL NOT NULL,
            avg_episode_return REAL NOT NULL,
            convergence_episodes INTEGER NOT NULL,
            gait_quality_score REAL NOT NULL,
            sim_to_real_transfer_score REAL NOT NULL,
            notes TEXT
        )
    """)

    # 20 historical training experiments with varying configurations
    # Columns: run_id, run_name, reward_version,
    #   w_tracking_lin_vel, w_tracking_ang_vel, w_lin_vel_z, w_ang_vel_xy,
    #   w_orientation, w_action_rate, w_torques, w_joint_limits,
    #   w_feet_air_time, w_feet_clearance,
    #   avg_episode_return, convergence_episodes,
    #   gait_quality_score, sim_to_real_transfer_score, notes
    runs = [
        (1, "baseline_v1", "v0.1",
         1.0, 0.5, -0.5, -0.03, -2.0, -0.01, -0.0002, -0.5, 0.1, -2.0,
         45.2, 5000, 0.42, 0.35,
         "initial baseline with conservative weights"),
        (2, "high_tracking", "v0.2",
         3.0, 1.5, -0.3, -0.02, -1.5, -0.005, -0.0001, -0.3, 0.05, -1.0,
         62.1, 8000, 0.55, 0.28,
         "aggressive velocity tracking, poor sim2real"),
        (3, "conservative", "v0.2",
         0.8, 0.4, -1.0, -0.08, -4.0, -0.02, -0.0005, -1.5, 0.08, -3.0,
         38.5, 6000, 0.38, 0.41,
         "heavy penalties, too conservative"),
        (4, "balanced_v1", "v0.3",
         1.2, 0.6, -0.7, -0.04, -2.5, -0.012, -0.00025, -0.8, 0.11, -2.2,
         55.0, 4500, 0.58, 0.52,
         "first balanced attempt"),
        (5, "vel_emphasis", "v0.4",
         2.0, 1.0, -0.6, -0.04, -2.8, -0.013, -0.00035, -0.9, 0.15, -2.3,
         70.3, 3500, 0.65, 0.48,
         "velocity emphasis with moderate penalties"),
        (6, "smooth_v1", "v0.4",
         1.3, 0.65, -0.75, -0.045, -2.7, -0.013, -0.00028, -0.85, 0.11, -2.1,
         48.7, 4200, 0.60, 0.61,
         "smoothness focused"),
        (7, "penalty_heavy", "v0.5",
         1.1, 0.55, -0.9, -0.06, -3.2, -0.018, -0.0004, -1.2, 0.09, -2.8,
         42.0, 5500, 0.45, 0.55,
         "heavy orientation and clearance penalties"),
        (8, "tuned_v2", "v0.6",
         1.6, 0.8, -0.85, -0.055, -3.1, -0.016, -0.00032, -1.05, 0.13, -2.6,
         85.3, 2800, 0.82, 0.72,
         "well-tuned, high return variant"),
        (9, "mixed_v1", "v0.6",
         1.8, 0.9, -0.65, -0.04, -2.6, -0.011, -0.00022, -0.75, 0.14, -2.0,
         67.8, 3800, 0.68, 0.58,
         "mixed approach"),
        (10, "careful_v1", "v0.7",
         1.15, 0.58, -0.82, -0.05, -2.9, -0.014, -0.0003, -0.95, 0.10, -2.35,
         51.2, 4800, 0.62, 0.63,
         "careful parameter selection"),
        (11, "refined_v1", "v0.8",
         1.7, 0.85, -0.78, -0.052, -3.05, -0.015, -0.00031, -1.02, 0.125, -2.55,
         73.5, 3200, 0.71, 0.69,
         "refined from tuned_v2"),
        (12, "sim2real_v1", "v0.8",
         1.35, 0.7, -0.88, -0.058, -3.3, -0.017, -0.00038, -1.15, 0.11, -2.7,
         59.4, 4000, 0.66, 0.75,
         "sim2real focused penalties"),
        (13, "robust_v1", "v0.9",
         1.05, 0.52, -0.95, -0.065, -3.5, -0.019, -0.00045, -1.3, 0.085, -2.9,
         44.1, 5200, 0.40, 0.71,
         "robustness focused, too heavy penalties"),
        (14, "production_v1", "v1.0",
         1.48, 0.73, -0.78, -0.048, -2.95, -0.014, -0.00028, -0.98, 0.115, -2.45,
         78.2, 3000, 0.85, 0.81,
         "production candidate with best gait quality"),
        (15, "fast_v1", "v1.0",
         2.2, 1.1, -0.55, -0.035, -2.3, -0.009, -0.00018, -0.65, 0.16, -1.8,
         88.1, 2500, 0.69, 0.55,
         "fast learning but poor transfer"),
        (16, "transfer_v1", "v1.1",
         1.4, 0.68, -0.83, -0.053, -3.0, -0.015, -0.0003, -1.0, 0.12, -2.4,
         64.3, 3600, 0.72, 0.77,
         "good sim2real transfer"),
        (17, "hybrid_v1", "v1.1",
         1.55, 0.78, -0.82, -0.053, -3.15, -0.016, -0.00033, -1.08, 0.13, -2.55,
         82.0, 2900, 0.73, 0.60,
         "hybrid approach"),
        (18, "safety_v1", "v1.2",
         1.25, 0.62, -0.92, -0.062, -3.4, -0.018, -0.00042, -1.25, 0.095, -2.85,
         56.8, 4600, 0.52, 0.83,
         "safety-focused with high transfer"),
        (19, "optimized_v1", "v1.2",
         2.1, 1.05, -0.6, -0.038, -2.4, -0.01, -0.0002, -0.7, 0.155, -1.9,
         92.7, 2200, 0.78, 0.65,
         "highest return achieved"),
        (20, "sim2real_v2", "v1.3",
         1.42, 0.72, -0.86, -0.055, -3.2, -0.016, -0.00034, -1.1, 0.11, -2.65,
         71.4, 3400, 0.76, 0.88,
         "best sim2real transfer"),
    ]

    cursor.executemany("""
        INSERT INTO training_runs VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
        )
    """, runs)

    conn.commit()
    conn.close()
    print(f"Created training history database with {len(runs)} experiments")


def main():
    np.random.seed(42)

    N = 500
    SIGMA = 0.25
    DT = 0.02
    SWING_HEIGHT = 0.08

    TRUE_WEIGHTS = {
        'tracking_lin_vel': 1.5,
        'tracking_ang_vel': 0.75,
        'lin_vel_z': -0.8,
        'ang_vel_xy': -0.05,
        'orientation': -3.0,
        'action_rate': -0.015,
        'torques': -0.0003,
        'joint_limits': -1.0,
        'feet_air_time': 0.12,
        'feet_clearance': -2.5,
    }

    # --- Correct helper functions ---

    def _sigmoids_correct(x, value_at_1, sigmoid):
        if sigmoid == "gaussian":
            scale = np.sqrt(-2 * np.log(value_at_1))
            return np.exp(-0.5 * (x * scale) ** 2)
        elif sigmoid == "hyperbolic":
            scale = np.arccosh(1 / value_at_1)
            return 1 / np.cosh(x * scale)
        elif sigmoid == "long_tail":
            scale = np.sqrt(1 / value_at_1 - 1)
            return 1 / ((x * scale) ** 2 + 1)
        elif sigmoid == "reciprocal":
            scale = 1 / value_at_1 - 1
            return 1 / (np.abs(x) * scale + 1)
        elif sigmoid == "cosine":
            scale = np.arccos(2 * value_at_1 - 1) / np.pi
            scaled_x = x * scale
            return np.where(np.abs(scaled_x) < 1, (1 + np.cos(np.pi * scaled_x)) / 2, 0.0)
        elif sigmoid == "linear":
            scale = 1 - value_at_1
            scaled_x = x * scale
            return np.where(np.abs(scaled_x) < 1, 1 - scaled_x, 0.0)
        elif sigmoid == "quadratic":
            scale = np.sqrt(1 - value_at_1)
            scaled_x = x * scale
            return np.where(np.abs(scaled_x) < 1, 1 - scaled_x**2, 0.0)
        elif sigmoid == "tanh_squared":
            scale = np.arctanh(np.sqrt(1 - value_at_1))
            return 1 - np.tanh(x * scale) ** 2
        raise ValueError(f"Unknown sigmoid: {sigmoid}")

    def tolerance_correct(x, bounds=(0.0, 0.0), margin=0.0, sigmoid="gaussian",
                          value_at_margin=0.1):
        lower, upper = bounds
        in_bounds = (lower <= x) & (x <= upper)
        if margin == 0:
            return np.where(in_bounds, 1.0, 0.0)
        d = np.where(x < lower, lower - x, x - upper) / margin
        return np.where(in_bounds, 1.0, _sigmoids_correct(d, value_at_margin, sigmoid))

    def cubic_bezier_correct(y_start, y_end, x):
        y_diff = y_end - y_start
        bezier = x**3 + 3 * (x**2 * (1 - x))
        return y_start + y_diff * bezier

    def get_rz_correct(phi, swing_height=0.08):
        x = (phi + np.pi) / (2 * np.pi)
        stance = cubic_bezier_correct(0, swing_height, 2 * x)
        swing = cubic_bezier_correct(swing_height, 0, 2 * x - 1)
        return np.where(x <= 0.5, stance, swing)

    # --- Generate trajectory data ---

    joint_ranges = np.array([
        [-0.8, 0.8], [-1.0, 3.5], [-2.7, -0.9],
        [-0.8, 0.8], [-1.0, 3.5], [-2.7, -0.9],
        [-0.8, 0.8], [-1.0, 3.5], [-2.7, -0.9],
        [-0.8, 0.8], [-1.0, 3.5], [-2.7, -0.9],
    ])
    soft_factor = 0.95
    centers = (joint_ranges[:, 0] + joint_ranges[:, 1]) / 2
    half_ranges = (joint_ranges[:, 1] - joint_ranges[:, 0]) / 2
    soft_lowers = centers - soft_factor * half_ranges
    soft_uppers = centers + soft_factor * half_ranges
    default_pose = np.array([
        0.0, 0.9, -1.8, 0.0, 0.9, -1.8,
        0.0, 0.9, -1.8, 0.0, 0.9, -1.8,
    ])

    # Commands
    commands = np.column_stack([
        np.random.uniform(-1.5, 1.5, N),
        np.random.uniform(-0.8, 0.8, N),
        np.random.uniform(-1.2, 1.2, N),
    ])
    zero_mask = np.random.random(N) < 0.05
    commands[zero_mask] = 0.0

    # Velocities (close to commands with noise)
    local_vel = np.column_stack([
        commands[:, 0] + np.random.normal(0, 0.2, N),
        commands[:, 1] + np.random.normal(0, 0.15, N),
        np.random.normal(0, 0.05, N),
    ])
    ang_vel = np.column_stack([
        np.random.normal(0, 0.2, N),
        np.random.normal(0, 0.2, N),
        commands[:, 2] + np.random.normal(0, 0.2, N),
    ])
    global_linvel = local_vel + np.random.normal(0, 0.03, (N, 3))
    global_angvel = ang_vel + np.random.normal(0, 0.03, (N, 3))

    # Torso up-vector (mostly upright)
    up_vector = np.column_stack([
        np.random.normal(0, 0.04, N),
        np.random.normal(0, 0.04, N),
        np.ones(N) * 0.99 + np.random.normal(0, 0.005, N),
    ])
    norms = np.linalg.norm(up_vector, axis=1, keepdims=True)
    up_vector = up_vector / norms

    # Joint positions (close to default, some exceeding soft limits)
    joint_pos = np.tile(default_pose, (N, 1)) + np.random.normal(0, 0.08, (N, 12))
    for i in range(N):
        if np.random.random() < 0.12:
            j = np.random.randint(12)
            if np.random.random() < 0.5:
                joint_pos[i, j] = soft_lowers[j] - np.random.uniform(0.01, 0.06)
            else:
                joint_pos[i, j] = soft_uppers[j] + np.random.uniform(0.01, 0.06)

    # Actions
    actions = np.random.normal(0, 0.25, (N, 12))
    prev_actions = np.roll(actions, 1, axis=0)
    prev_actions[0] = np.zeros(12)

    # Actuator forces and joint velocities
    actuator_force = np.random.normal(0, 4.0, (N, 12))
    joint_vel = np.random.normal(0, 0.8, (N, 12))

    # Foot data
    foot_vel = np.random.normal(0, 0.25, (N, 4, 3))
    contact = (np.random.random((N, 4)) > 0.4).astype(float)

    # Air time accumulation
    air_time = np.zeros((N, 4))
    for t in range(1, N):
        for f in range(4):
            if contact[t, f] == 0:
                air_time[t, f] = air_time[t - 1, f] + DT
            else:
                air_time[t, f] = 0.0

    # First contact flags
    first_contact = np.zeros((N, 4))
    for t in range(1, N):
        for f in range(4):
            if contact[t, f] > 0 and air_time[t - 1, f] > 0:
                first_contact[t, f] = 1.0

    # Foot heights
    foot_z = np.abs(np.random.normal(0, 0.06, (N, 4)))
    foot_z = foot_z * (1 - contact) + 0.002 * contact

    # Gait phases (trot gait pattern)
    base_phase = np.array([0, np.pi, np.pi, 0])
    gait_freq = 2.0
    gait_phase = np.array([
        np.mod(base_phase + 2 * np.pi * gait_freq * t * DT + np.pi, 2 * np.pi) - np.pi
        for t in range(N)
    ])

    # --- Compute correct rewards ---
    total_rewards = np.zeros(N)

    for t in range(N):
        cmd = commands[t]
        cmd_norm = np.linalg.norm(cmd)

        # tracking_lin_vel: exp(-squared_L2_error / sigma)
        lin_err = np.sum((cmd[:2] - local_vel[t, :2]) ** 2)
        r_tracking_lin = np.exp(-lin_err / SIGMA)

        # tracking_ang_vel
        ang_err = (cmd[2] - ang_vel[t, 2]) ** 2
        r_tracking_ang = np.exp(-ang_err / SIGMA)

        # lin_vel_z
        r_lin_z = global_linvel[t, 2] ** 2

        # ang_vel_xy
        r_ang_xy = np.sum(global_angvel[t, :2] ** 2)

        # orientation
        r_orient = np.sum(up_vector[t, :2] ** 2)

        # action_rate
        r_action = np.sum((actions[t] - prev_actions[t]) ** 2)

        # torques
        r_torques = np.sqrt(np.sum(actuator_force[t] ** 2)) + np.sum(np.abs(actuator_force[t]))

        # joint_limits (uses correct tolerance with gaussian sigmoid)
        violations = 0.0
        for j in range(12):
            tol_val = tolerance_correct(
                joint_pos[t, j],
                bounds=(soft_lowers[j], soft_uppers[j]),
                margin=0.1,
                sigmoid="gaussian",
                value_at_margin=0.1,
            )
            violations += 1.0 - tol_val
        r_joint_limits = violations

        # feet_air_time
        r_air = np.sum((air_time[t] - 0.1) * first_contact[t])
        r_air *= float(cmd_norm > 0.01)

        # feet_clearance (uses correct gait bezier)
        target_z = np.array([
            get_rz_correct(gait_phase[t, f], SWING_HEIGHT) for f in range(4)
        ])
        vel_xy = foot_vel[t, :, :2]
        vel_norm = np.sqrt(np.linalg.norm(vel_xy, axis=-1))
        delta = np.abs(foot_z[t] - target_z)
        r_clearance = np.sum(delta * vel_norm)

        # Total reward
        weighted = (
            TRUE_WEIGHTS['tracking_lin_vel'] * r_tracking_lin
            + TRUE_WEIGHTS['tracking_ang_vel'] * r_tracking_ang
            + TRUE_WEIGHTS['lin_vel_z'] * r_lin_z
            + TRUE_WEIGHTS['ang_vel_xy'] * r_ang_xy
            + TRUE_WEIGHTS['orientation'] * r_orient
            + TRUE_WEIGHTS['action_rate'] * r_action
            + TRUE_WEIGHTS['torques'] * r_torques
            + TRUE_WEIGHTS['joint_limits'] * r_joint_limits
            + TRUE_WEIGHTS['feet_air_time'] * r_air
            + TRUE_WEIGHTS['feet_clearance'] * r_clearance
        )
        total_rewards[t] = np.clip(weighted * DT, 0.0, 10000.0)

    # Save trajectory data
    os.makedirs('/app/data', exist_ok=True)

    np.savez(
        '/app/data/trajectory.npz',
        commands=commands,
        local_vel=local_vel,
        ang_vel=ang_vel,
        global_linvel=global_linvel,
        global_angvel=global_angvel,
        up_vector=up_vector,
        joint_pos=joint_pos,
        default_pose=default_pose,
        actions=actions,
        prev_actions=prev_actions,
        actuator_force=actuator_force,
        joint_vel=joint_vel,
        foot_vel=foot_vel,
        contact=contact,
        first_contact=first_contact,
        air_time=air_time,
        foot_z=foot_z,
        gait_phase=gait_phase,
        soft_lowers=soft_lowers,
        soft_uppers=soft_uppers,
    )

    np.save('/app/data/reference_rewards.npy', total_rewards)

    n_pos = np.sum(total_rewards > 0)
    print(f"Generated {N} timesteps of trajectory data")
    print(f"Positive rewards: {n_pos}/{N} ({100*n_pos/N:.1f}%)")
    print(f"Zero-clipped rewards: {N - n_pos}/{N}")
    if n_pos > 0:
        print(f"Mean positive reward: {np.mean(total_rewards[total_rewards > 0]):.6f}")

    # Create training history database
    create_training_history_db('/app/data/training_history.db')


if __name__ == '__main__':
    main()
