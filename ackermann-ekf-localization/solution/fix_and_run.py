#!/usr/bin/env python3
"""Complete solution: per-landmark fault detection + robust EKF."""

import sqlite3
import json
import csv
import os
import math

import numpy as np


def normalize_angle(a):
    """Normalize angle to [-pi, pi)."""
    return (a + np.pi) % (2 * np.pi) - np.pi


def load_data():
    """Load config, landmarks, controls, observations, and ground truth."""
    with open('/app/config.json') as f:
        config = json.load(f)

    conn = sqlite3.connect('/app/sensor_data.db')
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

    c.execute('SELECT timestep, x, y, theta FROM ground_truth ORDER BY timestep')
    gt_rows = c.fetchall()
    ground_truth = np.array([[r[1], r[2], r[3]] for r in gt_rows])

    conn.close()
    return config, landmarks, controls, observations, ground_truth


def run_ekf(config, landmarks, controls, observations, exclude_lm=None):
    """Run EKF, optionally excluding certain landmarks.

    Returns trajectory array (N+1 x 3), list of covariance matrices,
    outlier/total counts, per-landmark innovation dict, and residual list.
    """
    if exclude_lm is None:
        exclude_lm = set()

    L = config['vehicle']['wheelbase']
    offset = np.array(config['vehicle']['sensor_offset'])
    dt = config['dt']
    N = config['num_timesteps']

    sigma_v = config['noise']['process']['sigma_v']
    sigma_delta = config['noise']['process']['sigma_delta']
    sigma_range_base = config['noise']['measurement']['sigma_range_base']
    sigma_range_scale = config['noise']['measurement']['sigma_range_scale']
    sigma_bearing = config['noise']['measurement']['sigma_bearing']
    gate = config['filter']['mahalanobis_gate']

    x = np.array(config['filter']['initial_state'], dtype=float)
    P = np.diag(config['filter']['initial_covariance'])

    trajectory = np.zeros((N + 1, 3))
    covariances = []
    per_lm_innovations = {}
    residuals = []
    outliers = 0
    total = 0

    for k in range(N + 1):
        # ---- Prediction ----
        if k > 0 and (k - 1) in controls:
            v, delta = controls[k - 1]
            theta = x[2]
            ct, st = np.cos(theta), np.sin(theta)
            td, cd = np.tan(delta), np.cos(delta)

            x = np.array([
                x[0] + v * ct * dt,
                x[1] + v * st * dt,
                normalize_angle(x[2] + (v / L) * td * dt)
            ])

            F = np.array([
                [1.0, 0.0, -v * st * dt],
                [0.0, 1.0,  v * ct * dt],
                [0.0, 0.0,  1.0]
            ])

            W = np.array([
                [ct * dt, 0.0],
                [st * dt, 0.0],
                [(1.0 / L) * td * dt, (v / L) * (1.0 / cd ** 2) * dt]
            ])

            Q = W @ np.diag([sigma_v ** 2, sigma_delta ** 2]) @ W.T
            P = F @ P @ F.T + Q

        # ---- Measurement update ----
        if k in observations:
            for obs in observations[k]:
                lm_id = obs['landmark_id']
                if lm_id in exclude_lm or lm_id not in landmarks:
                    continue

                total += 1
                lm = landmarks[lm_id]
                theta = x[2]
                ct, st = np.cos(theta), np.sin(theta)

                # Sensor position in world frame (correct rotation)
                sx = x[0] + offset[0] * ct - offset[1] * st
                sy = x[1] + offset[0] * st + offset[1] * ct

                dx, dy = lm[0] - sx, lm[1] - sy
                q = dx ** 2 + dy ** 2
                sq = np.sqrt(q)
                if sq < 1e-6:
                    continue

                z_pred = np.array([
                    sq,
                    normalize_angle(np.arctan2(dy, dx) - theta)
                ])

                dsx = -offset[0] * st - offset[1] * ct
                dsy = offset[0] * ct - offset[1] * st

                H = np.array([
                    [-dx / sq, -dy / sq, -(dx * dsx + dy * dsy) / sq],
                    [dy / q, -dx / q, (dy * dsx - dx * dsy) / q - 1.0]
                ])

                rs = sigma_range_base + sigma_range_scale * z_pred[0]
                R = np.diag([rs ** 2, sigma_bearing ** 2])

                innov = np.array([
                    obs['range'] - z_pred[0],
                    normalize_angle(obs['bearing'] - z_pred[1])
                ])

                S = H @ P @ H.T + R
                Si = np.linalg.inv(S)
                mahal = float(innov @ Si @ innov)

                # Record per-landmark innovations for analysis
                per_lm_innovations.setdefault(lm_id, []).append(
                    (innov[0], innov[1], mahal)
                )

                if mahal > gate:
                    outliers += 1
                    residuals.append((k, lm_id, innov[0], innov[1], mahal, 0))
                    continue

                residuals.append((k, lm_id, innov[0], innov[1], mahal, 1))

                K = P @ H.T @ Si
                x = x + K @ innov
                x[2] = normalize_angle(x[2])

                I_KH = np.eye(3) - K @ H
                P = I_KH @ P @ I_KH.T + K @ R @ K.T

        trajectory[k] = x
        covariances.append(P.copy())

    return trajectory, covariances, outliers, total, per_lm_innovations, residuals


def detect_compromised(per_lm_innovations):
    """Identify compromised landmarks via per-landmark innovation statistics.

    For each landmark, compute the mean range innovation and test H₀: μ=0
    using a t-test (normal approximation for large n).
    """
    compromised = {}

    for lm_id, innovations in per_lm_innovations.items():
        if len(innovations) < 10:
            continue

        range_innov = np.array([i[0] for i in innovations])
        n = len(range_innov)
        mean_ri = float(np.mean(range_innov))
        std_ri = float(np.std(range_innov, ddof=1))

        if std_ri < 1e-10:
            continue

        se = std_ri / np.sqrt(n)
        t_stat = mean_ri / se

        # Two-sided p-value using normal approximation (valid for n>30)
        p_value = 2.0 * (1.0 - 0.5 * (1.0 + math.erf(abs(t_stat) / math.sqrt(2.0))))

        # Flag as compromised if statistically significant AND practically meaningful
        if p_value < 0.01 and abs(mean_ri) > 0.15:
            compromised[lm_id] = {
                'mean_range_innovation': round(mean_ri, 6),
                'num_observations': n,
                'p_value': float(max(p_value, 1e-300))
            }

    return compromised


def compute_rmse(traj, gt, start=50):
    """Compute position and heading RMSE from timestep 'start' onward."""
    pos_err = np.sqrt(
        (traj[start:, 0] - gt[start:, 0]) ** 2 +
        (traj[start:, 1] - gt[start:, 1]) ** 2
    )
    pos_rmse = float(np.sqrt(np.mean(pos_err ** 2)))
    head_err = normalize_angle(traj[start:, 2] - gt[start:, 2])
    head_rmse = float(np.sqrt(np.mean(head_err ** 2)))
    return pos_rmse, head_rmse


def main():
    config, landmarks, controls, observations, ground_truth = load_data()

    # ---- Phase 1: Run baseline EKF with all landmarks ----
    print("Phase 1: Running baseline EKF (all landmarks)...")
    baseline_traj, _, _, _, baseline_innov, _ = run_ekf(
        config, landmarks, controls, observations
    )

    # ---- Phase 2: Evaluate per-landmark innovation statistics ----
    print("Phase 2: Evaluating per-landmark integrity...")
    compromised = detect_compromised(baseline_innov)
    exclude_set = set(compromised.keys())
    print(f"  Compromised landmarks detected: {sorted(exclude_set)}")
    for lm_id, ev in sorted(compromised.items()):
        print(f"    Landmark {lm_id}: mean_range_innov={ev['mean_range_innovation']:.4f}m, "
              f"n={ev['num_observations']}, p={ev['p_value']:.2e}")

    # ---- Phase 3: Run robust EKF excluding compromised landmarks ----
    print("Phase 3: Running robust EKF (excluding compromised)...")
    robust_traj, robust_cov, outliers, total, _, residuals = run_ekf(
        config, landmarks, controls, observations, exclude_lm=exclude_set
    )

    # ---- Phase 4: Compute comparison metrics ----
    print("Phase 4: Computing comparison metrics...")
    bl_pos, bl_head = compute_rmse(baseline_traj, ground_truth)
    rb_pos, rb_head = compute_rmse(robust_traj, ground_truth)
    print(f"  Baseline: pos_rmse={bl_pos:.4f}m, head_rmse={bl_head:.4f}rad")
    print(f"  Robust:   pos_rmse={rb_pos:.4f}m, head_rmse={rb_head:.4f}rad")
    print(f"  Position improvement: {(1 - rb_pos / bl_pos) * 100:.1f}%")

    # ---- Phase 5: Write all outputs ----
    print("Phase 5: Writing outputs...")
    os.makedirs('/app/output', exist_ok=True)

    # trajectory.csv (robust filter)
    with open('/app/output/trajectory.csv', 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['timestep', 'x', 'y', 'theta'])
        for k in range(501):
            w.writerow([k, f'{robust_traj[k, 0]:.6f}',
                        f'{robust_traj[k, 1]:.6f}',
                        f'{robust_traj[k, 2]:.6f}'])

    # baseline_trajectory.csv (for gnuplot comparison)
    with open('/app/output/baseline_trajectory.csv', 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['timestep', 'x', 'y', 'theta'])
        for k in range(501):
            w.writerow([k, f'{baseline_traj[k, 0]:.6f}',
                        f'{baseline_traj[k, 1]:.6f}',
                        f'{baseline_traj[k, 2]:.6f}'])

    # covariance.csv
    with open('/app/output/covariance.csv', 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['timestep', 'P00', 'P01', 'P02', 'P11', 'P12', 'P22'])
        for k in range(501):
            P = robust_cov[k]
            w.writerow([k,
                        f'{P[0, 0]:.8f}', f'{P[0, 1]:.8f}',
                        f'{P[0, 2]:.8f}', f'{P[1, 1]:.8f}',
                        f'{P[1, 2]:.8f}', f'{P[2, 2]:.8f}'])

    # diagnosis.json
    with open('/app/output/diagnosis.json', 'w') as f:
        json.dump({
            'compromised_landmarks': sorted(compromised.keys()),
            'evidence': {str(k): v for k, v in compromised.items()}
        }, f, indent=2)

    # comparison.json
    with open('/app/output/comparison.json', 'w') as f:
        json.dump({
            'baseline_position_rmse': bl_pos,
            'robust_position_rmse': rb_pos,
            'baseline_heading_rmse': bl_head,
            'robust_heading_rmse': rb_head
        }, f, indent=2)

    # stats.json
    with open('/app/output/stats.json', 'w') as f:
        json.dump({
            'outliers_detected': outliers,
            'total_observations': total
        }, f, indent=2)

    # filter_residuals table in SQLite
    conn = sqlite3.connect('/app/sensor_data.db')
    c = conn.cursor()
    c.execute('DROP TABLE IF EXISTS filter_residuals')
    c.execute('''CREATE TABLE filter_residuals (
        timestep INTEGER,
        landmark_id INTEGER,
        range_residual REAL,
        bearing_residual REAL,
        mahalanobis REAL,
        accepted INTEGER
    )''')
    for r in residuals:
        c.execute('INSERT INTO filter_residuals VALUES (?, ?, ?, ?, ?, ?)',
                  (r[0], r[1], float(r[2]), float(r[3]), float(r[4]), r[5]))
    conn.commit()
    conn.close()

    print("Done.")


if __name__ == '__main__':
    main()
