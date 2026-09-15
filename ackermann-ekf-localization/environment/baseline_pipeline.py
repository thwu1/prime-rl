#!/usr/bin/env python3
"""Baseline vehicle localization pipeline — correct EKF with standard
Mahalanobis gating but no per-landmark fault detection."""

import sqlite3
import json
import csv
import os
import sys

try:
    import numpy as np
except ImportError:
    print("ERROR: numpy is required. Install with: pip3 install numpy")
    sys.exit(1)


def normalize_angle(a):
    """Normalize angle to [-pi, pi)."""
    return (a + np.pi) % (2 * np.pi) - np.pi


def load_config(path='/app/config.json'):
    with open(path) as f:
        return json.load(f)


def load_from_db(db_path='/app/sensor_data.db'):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    c.execute('SELECT id, x, y FROM landmarks')
    landmarks = {row[0]: np.array([row[1], row[2]]) for row in c.fetchall()}

    c.execute('SELECT timestep, velocity, steering_angle FROM controls ORDER BY timestep')
    controls = {row[0]: np.array([row[1], row[2]]) for row in c.fetchall()}

    c.execute('SELECT timestep, landmark_id, range_m, bearing_rad FROM observations ORDER BY timestep')
    observations = {}
    for row in c.fetchall():
        k = row[0]
        observations.setdefault(k, []).append({
            'landmark_id': row[1],
            'range': row[2],
            'bearing': row[3],
        })

    conn.close()
    return landmarks, controls, observations


def run_filter(config, landmarks, controls, observations):
    L = config['vehicle']['wheelbase']
    offset = np.array(config['vehicle']['sensor_offset'])
    dt = config['dt']
    N = config['num_timesteps']

    sigma_v = config['noise']['process']['sigma_v']
    sigma_delta = config['noise']['process']['sigma_delta']
    sigma_range_base = config['noise']['measurement']['sigma_range_base']
    sigma_range_scale = config['noise']['measurement']['sigma_range_scale']
    sigma_bearing = config['noise']['measurement']['sigma_bearing']
    gate_threshold = config['filter']['mahalanobis_gate']

    x = np.array(config['filter']['initial_state'], dtype=float)
    P = np.diag(config['filter']['initial_covariance'])

    trajectory = []
    covariances = []
    outliers_detected = 0
    total_observations = 0

    for k in range(N + 1):
        # ---- Prediction step ----
        if k > 0 and (k - 1) in controls:
            v, delta = controls[k - 1]
            theta = x[2]
            cos_t = np.cos(theta)
            sin_t = np.sin(theta)
            tan_d = np.tan(delta)
            cos_d = np.cos(delta)

            x_pred = np.array([
                x[0] + v * cos_t * dt,
                x[1] + v * sin_t * dt,
                normalize_angle(x[2] + (v / L) * tan_d * dt),
            ])

            F = np.array([
                [1.0, 0.0, -v * sin_t * dt],
                [0.0, 1.0,  v * cos_t * dt],
                [0.0, 0.0,  1.0],
            ])

            W = np.array([
                [cos_t * dt, 0.0],
                [sin_t * dt, 0.0],
                [(1.0 / L) * tan_d * dt,
                 (v / L) * (1.0 / cos_d ** 2) * dt],
            ])

            Q_ctrl = np.diag([sigma_v ** 2, sigma_delta ** 2])
            Q = W @ Q_ctrl @ W.T

            P = F @ P @ F.T + Q
            x = x_pred

        # ---- Measurement update step ----
        if k in observations:
            for obs in observations[k]:
                total_observations += 1
                lm_id = obs['landmark_id']
                z_range = obs['range']
                z_bearing = obs['bearing']

                if lm_id not in landmarks:
                    continue

                lm = landmarks[lm_id]
                theta = x[2]
                cos_t = np.cos(theta)
                sin_t = np.sin(theta)

                # Sensor position in world frame
                sx = x[0] + offset[0] * cos_t - offset[1] * sin_t
                sy = x[1] + offset[0] * sin_t + offset[1] * cos_t

                dx = lm[0] - sx
                dy = lm[1] - sy
                q = dx ** 2 + dy ** 2
                sqrt_q = np.sqrt(q)

                if sqrt_q < 1e-6:
                    continue

                z_pred_range = sqrt_q
                z_pred_bearing = normalize_angle(np.arctan2(dy, dx) - theta)

                dsx_dt = -offset[0] * sin_t - offset[1] * cos_t
                dsy_dt = offset[0] * cos_t - offset[1] * sin_t

                H = np.array([
                    [-dx / sqrt_q,
                     -dy / sqrt_q,
                     -(dx * dsx_dt + dy * dsy_dt) / sqrt_q],
                    [dy / q,
                     -dx / q,
                     (dy * dsx_dt - dx * dsy_dt) / q - 1.0],
                ])

                range_sigma = sigma_range_base + sigma_range_scale * z_pred_range
                R = np.diag([range_sigma ** 2, sigma_bearing ** 2])

                innovation = np.array([
                    z_range - z_pred_range,
                    normalize_angle(z_bearing - z_pred_bearing),
                ])

                S = H @ P @ H.T + R
                S_inv = np.linalg.inv(S)

                mahal = float(innovation.T @ S_inv @ innovation)
                if mahal > gate_threshold:
                    outliers_detected += 1
                    continue

                K = P @ H.T @ S_inv
                x = x + K @ innovation
                x[2] = normalize_angle(x[2])

                I_KH = np.eye(3) - K @ H
                P = I_KH @ P @ I_KH.T + K @ R @ K.T

        trajectory.append((k, x[0], x[1], x[2]))
        covariances.append((k, P.copy()))

    return trajectory, covariances, outliers_detected, total_observations


def write_output(trajectory, covariances, outliers_detected, total_observations):
    os.makedirs('/app/output', exist_ok=True)

    with open('/app/output/trajectory.csv', 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['timestep', 'x', 'y', 'theta'])
        for row in trajectory:
            w.writerow([row[0], f'{row[1]:.6f}', f'{row[2]:.6f}',
                        f'{row[3]:.6f}'])

    with open('/app/output/covariance.csv', 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['timestep', 'P00', 'P01', 'P02', 'P11', 'P12', 'P22'])
        for k, Pk in covariances:
            w.writerow([k,
                        f'{Pk[0, 0]:.8f}', f'{Pk[0, 1]:.8f}',
                        f'{Pk[0, 2]:.8f}', f'{Pk[1, 1]:.8f}',
                        f'{Pk[1, 2]:.8f}', f'{Pk[2, 2]:.8f}'])

    with open('/app/output/stats.json', 'w') as f:
        json.dump({
            'outliers_detected': outliers_detected,
            'total_observations': total_observations,
        }, f, indent=2)


def main():
    config = load_config()
    landmarks, controls, observations = load_from_db()

    trajectory, covariances, outliers, total = run_filter(
        config, landmarks, controls, observations
    )
    write_output(trajectory, covariances, outliers, total)

    print(f"Pipeline complete: {outliers}/{total} outliers detected")
    final = trajectory[-1]
    print(f"Final state: x={final[1]:.4f}  y={final[2]:.4f}  theta={final[3]:.4f}")


if __name__ == '__main__':
    main()
