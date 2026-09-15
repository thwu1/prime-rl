#!/usr/bin/env python3
"""Generate deterministic EKF-SLAM scenario data.

Creates a synthetic 2D environment with point landmarks and a robot
following a predefined trajectory. Produces noisy odometry and
range-bearing observations.

"""

import numpy as np
import pickle
import os


def normalize_angle(angle):
    return (angle + np.pi) % (2 * np.pi) - np.pi


def generate_scenario():
    np.random.seed(42)

    # Ground truth landmark positions (spread around the trajectory)
    landmarks = np.array([
        [4.0, 3.0],
        [4.0, -3.0],
        [10.0, 3.0],
        [10.0, -2.0],
        [7.0, 7.0],
        [-2.0, 5.0],
        [2.0, 9.0],
        [-3.0, -2.0],
    ])

    n_landmarks = len(landmarks)
    dt = 0.1
    n_steps = 400
    max_range = 6.0

    # Noise parameters
    sigma_v = 0.05
    sigma_omega = 0.02
    sigma_range = 0.15
    sigma_bearing = 0.03

    # Control inputs: robot drives roughly a rectangular loop
    # Each cycle: 80 steps straight + 20 steps turning ~90 degrees
    controls = np.zeros((n_steps, 2))
    for t in range(n_steps):
        phase = t % 100
        if phase < 80:
            controls[t] = [1.0, 0.0]       # straight at 1.0 m/s
        else:
            controls[t] = [0.3, np.pi / 4]  # turn left at pi/4 rad/s

    # Generate ground truth trajectory
    true_poses = np.zeros((n_steps + 1, 3))
    for t in range(n_steps):
        v, omega = controls[t]
        x, y, theta = true_poses[t]
        true_poses[t + 1, 0] = x + v * dt * np.cos(theta)
        true_poses[t + 1, 1] = y + v * dt * np.sin(theta)
        true_poses[t + 1, 2] = normalize_angle(theta + omega * dt)

    # Generate noisy odometry (what the robot reports)
    noisy_controls = controls.copy()
    noisy_controls[:, 0] += np.random.randn(n_steps) * sigma_v
    noisy_controls[:, 1] += np.random.randn(n_steps) * sigma_omega

    # Generate range-bearing observations at each timestep
    observations = []
    for t in range(n_steps + 1):
        x, y, theta = true_poses[t]
        obs_t = []
        for j in range(n_landmarks):
            dx = landmarks[j, 0] - x
            dy = landmarks[j, 1] - y
            r = np.sqrt(dx**2 + dy**2)
            if r <= max_range:
                bearing = normalize_angle(np.arctan2(dy, dx) - theta)
                noisy_r = r + np.random.randn() * sigma_range
                noisy_bearing = normalize_angle(
                    bearing + np.random.randn() * sigma_bearing
                )
                if noisy_r > 0:
                    obs_t.append((j, noisy_r, noisy_bearing))
        observations.append(obs_t)

    scenario = {
        'landmarks': landmarks,
        'true_poses': true_poses,
        'controls': noisy_controls,
        'observations': observations,
        'dt': dt,
        'n_landmarks': n_landmarks,
        'max_range': max_range,
        'sigma_v': sigma_v,
        'sigma_omega': sigma_omega,
        'sigma_range': sigma_range,
        'sigma_bearing': sigma_bearing,
    }

    os.makedirs('/app', exist_ok=True)
    with open('/app/scenario.pkl', 'wb') as f:
        pickle.dump(scenario, f)

    print(f"Scenario: {n_steps} steps, {n_landmarks} landmarks, dt={dt}")
    print(f"Start: {true_poses[0, :2]}, End: {true_poses[-1, :2]}")
    print(f"Noise: sigma_v={sigma_v}, sigma_omega={sigma_omega}, "
          f"sigma_r={sigma_range}, sigma_phi={sigma_bearing}")


if __name__ == '__main__':
    generate_scenario()
