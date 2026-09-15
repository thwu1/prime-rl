#!/usr/bin/env python3
"""EKF solution for Ackermann-steered vehicle localization."""

import csv
import json
import os

import numpy as np


def normalize_angle(a):
    """Normalize angle to [-pi, pi)."""
    return (a + np.pi) % (2 * np.pi) - np.pi


def main():
    # ---- Load configuration ----
    with open('/app/data/config.json') as f:
        config = json.load(f)

    L = config['vehicle']['wheelbase']
    sensor_offset = np.array(config['vehicle']['sensor_offset'])
    dt = config['dt']
    N = config['num_timesteps']

    sigma_v = config['noise']['process']['sigma_v']
    sigma_delta = config['noise']['process']['sigma_delta']
    sigma_range_base = config['noise']['measurement']['sigma_range_base']
    sigma_range_scale = config['noise']['measurement']['sigma_range_scale']
    sigma_bearing = config['noise']['measurement']['sigma_bearing']

    gate_threshold = config['filter']['mahalanobis_gate']

    # ---- Load landmarks ----
    landmarks = {}
    with open('/app/data/landmarks.csv') as f:
        for row in csv.DictReader(f):
            landmarks[int(row['id'])] = np.array([float(row['x']),
                                                   float(row['y'])])

    # ---- Load controls ----
    controls = {}
    with open('/app/data/controls.csv') as f:
        for row in csv.DictReader(f):
            controls[int(row['timestep'])] = np.array([float(row['v']),
                                                        float(row['delta'])])

    # ---- Load observations, grouped by timestep ----
    observations = {}
    with open('/app/data/observations.csv') as f:
        for row in csv.DictReader(f):
            k = int(row['timestep'])
            observations.setdefault(k, []).append({
                'landmark_id': int(row['landmark_id']),
                'range': float(row['range']),
                'bearing': float(row['bearing']),
            })

    # ---- Initialise EKF ----
    x = np.array(config['filter']['initial_state'], dtype=float)
    P = np.diag(config['filter']['initial_covariance'])

    trajectory = []
    covariances = []
    outliers_detected = 0
    total_observations = 0

    # ---- Main loop ----
    for k in range(N + 1):
        # --- Prediction (k > 0) ---
        if k > 0 and (k - 1) in controls:
            v, delta = controls[k - 1]
            theta = x[2]
            cos_t = np.cos(theta)
            sin_t = np.sin(theta)
            tan_d = np.tan(delta)
            cos_d = np.cos(delta)

            # Ackermann motion model (Euler discretisation)
            x_pred = np.array([
                x[0] + v * cos_t * dt,
                x[1] + v * sin_t * dt,
                normalize_angle(x[2] + (v / L) * tan_d * dt),
            ])

            # Jacobian F = df/dx
            F = np.array([
                [1.0, 0.0, -v * sin_t * dt],
                [0.0, 1.0,  v * cos_t * dt],
                [0.0, 0.0,  1.0],
            ])

            # Jacobian W = df/d[n_v, n_delta]  (noise-input Jacobian)
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

        # --- Update with observations ---
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
                sx = x[0] + sensor_offset[0] * cos_t - sensor_offset[1] * sin_t
                sy = x[1] + sensor_offset[0] * sin_t + sensor_offset[1] * cos_t

                dx = lm[0] - sx
                dy = lm[1] - sy
                q = dx ** 2 + dy ** 2
                sqrt_q = np.sqrt(q)

                if sqrt_q < 1e-6:
                    continue

                # Predicted measurement
                z_pred_range = sqrt_q
                z_pred_bearing = normalize_angle(np.arctan2(dy, dx) - theta)

                # Partials of sensor position w.r.t. theta
                dsx_dt = -sensor_offset[0] * sin_t - sensor_offset[1] * cos_t
                dsy_dt = sensor_offset[0] * cos_t - sensor_offset[1] * sin_t

                # Measurement Jacobian H (2x3)
                H = np.array([
                    [-dx / sqrt_q,
                     -dy / sqrt_q,
                     -(dx * dsx_dt + dy * dsy_dt) / sqrt_q],
                    [dy / q,
                     -dx / q,
                     (dy * dsx_dt - dx * dsy_dt) / q - 1.0],
                ])

                # Heteroscedastic measurement noise
                range_sigma = sigma_range_base + sigma_range_scale * z_pred_range
                R = np.diag([range_sigma ** 2, sigma_bearing ** 2])

                # Innovation
                innovation = np.array([
                    z_range - z_pred_range,
                    normalize_angle(z_bearing - z_pred_bearing),
                ])

                # Innovation covariance
                S = H @ P @ H.T + R
                S_inv = np.linalg.inv(S)

                # Mahalanobis distance gating
                mahal = float(innovation.T @ S_inv @ innovation)
                if mahal > gate_threshold:
                    outliers_detected += 1
                    continue

                # Kalman gain
                K = P @ H.T @ S_inv

                # State update
                x = x + K @ innovation
                x[2] = normalize_angle(x[2])

                # Covariance update (Joseph form)
                I_KH = np.eye(3) - K @ H
                P = I_KH @ P @ I_KH.T + K @ R @ K.T

        # Record state and covariance
        trajectory.append((k, x[0], x[1], x[2]))
        covariances.append((k, P.copy()))

    # ---- Write output ----
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

    print(f"EKF complete: {outliers_detected}/{total_observations} "
          f"outliers detected")
    print(f"Final state: x={x[0]:.4f}  y={x[1]:.4f}  "
          f"theta={x[2]:.4f}")


if __name__ == '__main__':
    main()
