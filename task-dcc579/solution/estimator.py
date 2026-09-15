"""Robust 3-state EKF localization with covariance-bounded outlier rejection.

Extended Kalman Filter [x, y, theta] fusing odometry, GPS, and range-to-landmark
measurements. Uses chi-squared Mahalanobis gating, covariance capping to prevent
outlier acceptance from large uncertainty, and adaptive recovery from filter divergence.

Usage:  python3 estimator.py <data_dir> <output_csv>
"""

import csv
import json
import math
import os
import sys

import numpy as np


def load_data(data_dir):
    odom = []
    with open(os.path.join(data_dir, "odometry.csv")) as f:
        for row in csv.DictReader(f):
            odom.append(
                (float(row["time"]),
                 float(row["v_measured"]),
                 float(row["omega_measured"]))
            )

    gps = []
    with open(os.path.join(data_dir, "gps.csv")) as f:
        for row in csv.DictReader(f):
            gps.append(
                (float(row["time"]),
                 float(row["x_measured"]),
                 float(row["y_measured"]))
            )

    with open(os.path.join(data_dir, "landmarks.json")) as f:
        landmarks = json.load(f)

    ranges = []
    with open(os.path.join(data_dir, "range_measurements.csv")) as f:
        for row in csv.DictReader(f):
            ranges.append(
                (float(row["time"]),
                 int(row["landmark_id"]),
                 float(row["range_measured"]))
            )

    with open(os.path.join(data_dir, "sensor_config.json")) as f:
        cfg = json.load(f)

    return odom, gps, landmarks, ranges, cfg


def run_ekf(data_dir, output_path):
    odom, gps_list, landmarks, range_list, cfg = load_data(data_dir)

    dt = cfg["dt"]
    sv = cfg["odometry_noise"]["sigma_v"]
    sw = cfg["odometry_noise"]["sigma_omega"]
    sg = cfg["gps_noise"]["sigma_xy"]
    sr = cfg["range_noise"]["sigma_range"]

    N = 3  # [x, y, theta]

    # Covariance caps prevent outlier acceptance from large uncertainty
    MAX_POS_COV = 3.5
    MAX_THETA_COV = 1.2

    x = np.zeros(N)
    P = np.diag([min(sg ** 2, MAX_POS_COV),
                 min(sg ** 2, MAX_POS_COV),
                 min(math.pi ** 2, MAX_THETA_COV)])

    R_gps = np.diag([sg ** 2, sg ** 2])

    # Chi-squared thresholds (99% confidence)
    CHI2_2 = 9.210   # 2 DOF -- GPS
    CHI2_1 = 6.635   # 1 DOF -- range

    # Index measurements by rounded time
    gps_map = {}
    for t, xm, ym in gps_list:
        gps_map[round(t, 1)] = (xm, ym)

    rng_map = {}
    for t, lid, rm in range_list:
        key = round(t, 1)
        rng_map.setdefault(key, []).append((lid, rm))

    I_N = np.eye(N)
    traj = []
    gps_reject_streak = 0
    rng_reject_streak = 0

    for t_raw, v_meas, w_meas in odom:
        tk = round(t_raw, 1)

        # Divergence recovery: inflate P when too many measurements rejected
        lost = gps_reject_streak >= 2 or rng_reject_streak >= 2
        if lost and tk in gps_map:
            P = np.diag([MAX_POS_COV, MAX_POS_COV, MAX_THETA_COV])

        # --- GPS update ---
        if tk in gps_map:
            xg, yg = gps_map[tk]
            z = np.array([xg, yg])
            H = np.zeros((2, N))
            H[0, 0] = 1.0
            H[1, 1] = 1.0
            innov = z - H @ x
            S = H @ P @ H.T + R_gps
            Si = np.linalg.inv(S)
            d2 = float(innov @ Si @ innov)
            if d2 < CHI2_2:
                K = P @ H.T @ Si
                x = x + K @ innov
                IKH = I_N - K @ H
                P = IKH @ P @ IKH.T + K @ R_gps @ K.T
                P = 0.5 * (P + P.T)
                gps_reject_streak = 0
            else:
                gps_reject_streak += 1

        # --- Range updates ---
        if tk in rng_map:
            n_accepted = 0
            n_total = len(rng_map[tk])
            for lid, rm in rng_map[tk]:
                lm = landmarks[lid]
                dx = x[0] - lm[0]
                dy = x[1] - lm[1]
                rp = math.sqrt(dx * dx + dy * dy)
                if rp < 1e-3:
                    continue

                H = np.zeros((1, N))
                H[0, 0] = dx / rp
                H[0, 1] = dy / rp
                innov_r = np.array([rm - rp])
                S_r = H @ P @ H.T + np.array([[sr ** 2]])
                s_val = S_r[0, 0]
                d2 = float(innov_r[0] ** 2 / s_val)
                if d2 < CHI2_1:
                    K = (P @ H.T) / s_val
                    x = x + (K @ innov_r).flatten()
                    IKH = I_N - K @ H
                    P = IKH @ P @ IKH.T + K @ np.array([[sr ** 2]]) @ K.T
                    P = 0.5 * (P + P.T)
                    n_accepted += 1

            # Track range rejection rate for divergence detection
            if n_total >= 3 and n_accepted <= 1:
                rng_reject_streak += 1
            else:
                rng_reject_streak = 0

        # Record state after measurement update
        traj.append((tk, x[0], x[1], x[2]))

        # --- Prediction ---
        v = v_meas
        w = w_meas
        th = x[2]
        cth, sth = math.cos(th), math.sin(th)

        x_pred = np.array([
            x[0] + v * cth * dt,
            x[1] + v * sth * dt,
            x[2] + w * dt,
        ])

        F = np.eye(N)
        F[0, 2] = -v * sth * dt
        F[1, 2] = v * cth * dt

        # Process noise inflated to account for unmodeled odometry bias drift
        Q = np.diag([
            (sv * dt) ** 2 + 0.05 ** 2,
            (sv * dt) ** 2 + 0.05 ** 2,
            (sw * dt) ** 2 + 0.02 ** 2,
        ])

        P = F @ P @ F.T + Q
        P = 0.5 * (P + P.T)

        # Cap covariance to prevent unbounded growth
        for i in range(N):
            cap = MAX_POS_COV if i < 2 else MAX_THETA_COV
            if P[i, i] > cap:
                scale = math.sqrt(cap / P[i, i])
                P[i, :] *= scale
                P[:, i] *= scale
                P[i, i] = cap

        x = x_pred
        x[2] = (x[2] + math.pi) % (2.0 * math.pi) - math.pi

    # Write output
    out_dir = os.path.dirname(os.path.abspath(output_path))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(output_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["time", "x", "y", "theta"])
        for r in traj:
            w.writerow([f"{r[0]:.2f}", f"{r[1]:.6f}", f"{r[2]:.6f}", f"{r[3]:.6f}"])


if __name__ == "__main__":
    d = sys.argv[1] if len(sys.argv) > 1 else "/app/data"
    o = sys.argv[2] if len(sys.argv) > 2 else "/app/output/estimated_trajectory.csv"
    run_ekf(d, o)
