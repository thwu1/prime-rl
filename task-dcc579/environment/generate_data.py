"""Deterministic sensor data generator for robot localization task.

Generates a figure-eight trajectory with noisy odometry, GPS, and
range-to-landmark measurements. Uses only Python stdlib.
"""
import math
import random
import csv
import json
import os


def generate_dataset(seed, output_dir):
    random.seed(seed)
    os.makedirs(output_dir, exist_ok=True)

    dt = 0.1
    T = 60.0
    n_steps = int(T / dt)

    # Lissajous figure-eight trajectory
    A = 12.0
    B = 8.0
    T1 = 30.0
    w1 = 2.0 * math.pi / T1
    w2 = 2.0 * w1

    landmarks = [
        [10.0, 10.0],
        [-10.0, 10.0],
        [-10.0, -10.0],
        [10.0, -10.0],
        [0.0, 15.0],
        [0.0, -15.0],
    ]

    # Ground truth from analytic derivatives
    gt_x, gt_y, gt_theta, gt_v = [], [], [], []
    for i in range(n_steps + 1):
        t = i * dt
        x = A * math.sin(w1 * t)
        y = B * math.sin(w2 * t)
        dx = A * w1 * math.cos(w1 * t)
        dy = B * w2 * math.cos(w2 * t)
        gt_x.append(x)
        gt_y.append(y)
        gt_theta.append(math.atan2(dy, dx))
        gt_v.append(math.sqrt(dx * dx + dy * dy))

    gt_omega = []
    for i in range(n_steps):
        dth = gt_theta[i + 1] - gt_theta[i]
        while dth > math.pi:
            dth -= 2.0 * math.pi
        while dth < -math.pi:
            dth += 2.0 * math.pi
        gt_omega.append(dth / dt)
    gt_omega.append(0.0)

    # Noise config
    sigma_v = 0.20
    sigma_omega = 0.12
    bias_v_rate = 0.002
    bias_omega_rate = 0.001

    sigma_gps = 3.0
    gps_outlier_rate = 0.15
    gps_out_lo, gps_out_hi = 15.0, 45.0
    gps_period = 10

    sigma_range = 0.5
    range_outlier_rate = 0.10
    rng_out_lo, rng_out_hi = 10.0, 30.0
    range_period = 5
    max_range = 25.0

    # --- Odometry ---
    bv, bw = 0.0, 0.0
    odom_rows = []
    for i in range(n_steps):
        bv += random.gauss(0, bias_v_rate)
        bw += random.gauss(0, bias_omega_rate)
        odom_rows.append((
            i * dt,
            gt_v[i] + bv + random.gauss(0, sigma_v),
            gt_omega[i] + bw + random.gauss(0, sigma_omega),
        ))

    # --- GPS ---
    gps_rows = []
    n_gps_out = 0
    for i in range(0, n_steps, gps_period):
        t = i * dt
        if random.random() < gps_outlier_rate:
            ang = random.uniform(0, 2.0 * math.pi)
            mag = random.uniform(gps_out_lo, gps_out_hi)
            gps_rows.append((t, gt_x[i] + mag * math.cos(ang),
                             gt_y[i] + mag * math.sin(ang)))
            n_gps_out += 1
        else:
            gps_rows.append((t,
                             gt_x[i] + random.gauss(0, sigma_gps),
                             gt_y[i] + random.gauss(0, sigma_gps)))

    # --- Range to landmarks ---
    range_rows = []
    n_rng_out = 0
    for i in range(0, n_steps, range_period):
        t = i * dt
        for lid, lm in enumerate(landmarks):
            tr = math.sqrt((gt_x[i] - lm[0]) ** 2 + (gt_y[i] - lm[1]) ** 2)
            if tr > max_range:
                continue
            if random.random() < range_outlier_rate:
                rm = tr + random.uniform(rng_out_lo, rng_out_hi)
                n_rng_out += 1
            else:
                rm = tr + random.gauss(0, sigma_range)
            range_rows.append((t, lid, max(0.1, rm)))

    # Write files
    with open(os.path.join(output_dir, "odometry.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["time", "v_measured", "omega_measured"])
        for r in odom_rows:
            w.writerow([f"{r[0]:.2f}", f"{r[1]:.6f}", f"{r[2]:.6f}"])

    with open(os.path.join(output_dir, "gps.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["time", "x_measured", "y_measured"])
        for r in gps_rows:
            w.writerow([f"{r[0]:.2f}", f"{r[1]:.6f}", f"{r[2]:.6f}"])

    with open(os.path.join(output_dir, "range_measurements.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["time", "landmark_id", "range_measured"])
        for r in range_rows:
            w.writerow([f"{r[0]:.2f}", int(r[1]), f"{r[2]:.6f}"])

    with open(os.path.join(output_dir, "landmarks.json"), "w") as f:
        json.dump(landmarks, f, indent=2)

    config = {
        "dt": dt,
        "duration": T,
        "n_steps": n_steps,
        "n_landmarks": len(landmarks),
        "odometry_rate_hz": 10,
        "gps_rate_hz": 1,
        "range_rate_hz": 2,
        "max_sensing_range": max_range,
        "odometry_noise": {"sigma_v": sigma_v, "sigma_omega": sigma_omega},
        "gps_noise": {"sigma_xy": sigma_gps},
        "range_noise": {"sigma_range": sigma_range},
    }
    with open(os.path.join(output_dir, "sensor_config.json"), "w") as f:
        json.dump(config, f, indent=2)

    return {
        "x": gt_x[:n_steps],
        "y": gt_y[:n_steps],
        "theta": gt_theta[:n_steps],
        "n_gps_outliers": n_gps_out,
        "n_gps_total": len(gps_rows),
        "n_range_outliers": n_rng_out,
        "n_range_total": len(range_rows),
    }


if __name__ == "__main__":
    import sys
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 42
    out = sys.argv[2] if len(sys.argv) > 2 else "/app/data"
    gt = generate_dataset(seed, out)
    print(f"Generated {len(gt['x'])} steps, "
          f"GPS outliers {gt['n_gps_outliers']}/{gt['n_gps_total']}, "
          f"Range outliers {gt['n_range_outliers']}/{gt['n_range_total']}")
