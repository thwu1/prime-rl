#!/usr/bin/env python3
"""Generate synthetic 3D detection data in Apache Feather format.

Creates /app/data/detections.feather and /app/data/ground_truth.feather
with realistic autonomous driving detection data including edge cases
for range filtering, angle wrapping, and score-ordered assignment.
"""


import os
import numpy as np
import pyarrow as pa
import pyarrow.feather as pf

np.random.seed(42)

CATEGORIES = {
    "REGULAR_VEHICLE": {"l": (4.0, 5.5), "w": (1.8, 2.2), "h": (1.4, 1.8)},
    "PEDESTRIAN": {"l": (0.4, 0.8), "w": (0.4, 0.8), "h": (1.5, 1.9)},
    "BICYCLE": {"l": (1.5, 2.0), "w": (0.4, 0.7), "h": (1.0, 1.5)},
    "BUS": {"l": (10.0, 14.0), "w": (2.5, 3.0), "h": (3.0, 4.0)},
    "MOTORCYCLIST": {"l": (1.8, 2.5), "w": (0.6, 1.0), "h": (1.4, 1.8)},
}
LOG_IDS = ["log_001", "log_002", "log_003"]
TIMESTAMPS = [100000000, 200000000, 300000000]


def make_collectors():
    gt = {k: [] for k in [
        'log_id', 'timestamp_ns', 'category',
        'tx', 'ty', 'tz', 'length', 'width', 'height', 'yaw',
        'num_interior_pts']}
    dt = {k: [] for k in [
        'log_id', 'timestamp_ns', 'category',
        'tx', 'ty', 'tz', 'length', 'width', 'height', 'yaw',
        'score']}
    return gt, dt


def add_gt(col, lid, ts, cat, tx, ty, tz, l, w, h, yaw, nip):
    col['log_id'].append(lid)
    col['timestamp_ns'].append(int(ts))
    col['category'].append(cat)
    col['tx'].append(round(float(tx), 4))
    col['ty'].append(round(float(ty), 4))
    col['tz'].append(round(float(tz), 4))
    col['length'].append(round(float(l), 4))
    col['width'].append(round(float(w), 4))
    col['height'].append(round(float(h), 4))
    col['yaw'].append(round(float(yaw), 4))
    col['num_interior_pts'].append(int(nip))


def add_dt(col, lid, ts, cat, tx, ty, tz, l, w, h, yaw, score):
    col['log_id'].append(lid)
    col['timestamp_ns'].append(int(ts))
    col['category'].append(cat)
    col['tx'].append(round(float(tx), 4))
    col['ty'].append(round(float(ty), 4))
    col['tz'].append(round(float(tz), 4))
    col['length'].append(round(float(l), 4))
    col['width'].append(round(float(w), 4))
    col['height'].append(round(float(h), 4))
    col['yaw'].append(round(float(yaw), 4))
    col['score'].append(round(float(score), 4))


def generate():
    gt_col, dt_col = make_collectors()

    # --- Base data: random detections with noisy matches to GT ---
    for lid in LOG_IDS:
        for ts in TIMESTAMPS:
            for cat_name, params in CATEGORIES.items():
                n_gt = np.random.randint(4, 8)
                gts_local = []

                for _ in range(n_gt):
                    tx = np.random.uniform(-80, 80)
                    ty = np.random.uniform(-80, 80)
                    tz = np.random.uniform(-0.5, 1.5)
                    l = np.random.uniform(*params['l'])
                    w = np.random.uniform(*params['w'])
                    h = np.random.uniform(*params['h'])
                    yaw = np.random.uniform(-np.pi, np.pi)
                    nip = np.random.randint(5, 300)
                    add_gt(gt_col, lid, ts, cat_name, tx, ty, tz, l, w, h, yaw, nip)
                    gts_local.append({
                        'tx': tx, 'ty': ty, 'tz': tz,
                        'l': l, 'w': w, 'h': h, 'yaw': yaw})

                n_dt = np.random.randint(6, 13)
                for i in range(n_dt):
                    if i < len(gts_local) and np.random.random() > 0.15:
                        ref = gts_local[i % len(gts_local)]
                        noise = np.random.normal(0, 0.7, 3)
                        noise[2] *= 0.3
                        add_dt(dt_col, lid, ts, cat_name,
                               ref['tx'] + noise[0],
                               ref['ty'] + noise[1],
                               ref['tz'] + noise[2],
                               ref['l'] * np.random.uniform(0.8, 1.2),
                               ref['w'] * np.random.uniform(0.8, 1.2),
                               ref['h'] * np.random.uniform(0.85, 1.15),
                               ref['yaw'] + np.random.normal(0, 0.2),
                               np.random.uniform(0.2, 0.98))
                    else:
                        add_dt(dt_col, lid, ts, cat_name,
                               np.random.uniform(-120, 120),
                               np.random.uniform(-120, 120),
                               np.random.uniform(-0.5, 1.5),
                               np.random.uniform(*params['l']),
                               np.random.uniform(*params['w']),
                               np.random.uniform(*params['h']),
                               np.random.uniform(-np.pi, np.pi),
                               np.random.uniform(0.05, 0.5))

    # --- Edge case 1: Range boundary (L-inf < 150 but L2 >= 150) ---
    for i in range(6):
        offset = 107.0 + i * 2.0
        add_gt(gt_col, "log_001", 100000000, "REGULAR_VEHICLE",
               offset, offset, 0.5, 4.5, 2.0, 1.6, 0.5, 100)
        add_dt(dt_col, "log_001", 100000000, "REGULAR_VEHICLE",
               offset + np.random.normal(0, 0.3),
               offset + np.random.normal(0, 0.3),
               0.5 + np.random.normal(0, 0.1),
               4.6, 1.9, 1.65, 0.55,
               np.random.uniform(0.6, 0.9))

    # --- Edge case 2: Angle wrapping near ±π ---
    for i in range(8):
        gt_yaw = np.pi - 0.05 + np.random.uniform(-0.08, 0.08)
        dt_yaw = -np.pi + 0.05 + np.random.uniform(-0.08, 0.08)
        add_gt(gt_col, "log_002", 200000000, "PEDESTRIAN",
               15.0 + i * 8.0, 5.0 + i * 3.0, 0.0,
               0.6, 0.6, 1.7, gt_yaw, 50)
        add_dt(dt_col, "log_002", 200000000, "PEDESTRIAN",
               15.0 + i * 8.0 + np.random.normal(0, 0.15),
               5.0 + i * 3.0 + np.random.normal(0, 0.15),
               np.random.normal(0, 0.08),
               0.62, 0.58, 1.72, dt_yaw,
               np.random.uniform(0.55, 0.92))

    # --- Edge case 3: Score ordering in greedy assignment ---
    for i in range(5):
        gt_tx = 20.0 + i * 15.0
        gt_ty = 10.0 + i * 5.0
        gt_yaw = np.random.uniform(-1, 1)
        add_gt(gt_col, "log_001", 200000000, "BICYCLE",
               gt_tx, gt_ty, 0.3, 1.8, 0.5, 1.2, gt_yaw, 30)
        add_dt(dt_col, "log_001", 200000000, "BICYCLE",
               gt_tx + np.random.normal(0, 0.1),
               gt_ty + np.random.normal(0, 0.1),
               0.3 + np.random.normal(0, 0.05),
               1.75, 0.52, 1.18,
               gt_yaw + np.random.normal(0, 0.05),
               np.random.uniform(0.85, 0.98))
        add_dt(dt_col, "log_001", 200000000, "BICYCLE",
               gt_tx + np.random.normal(0, 0.15),
               gt_ty + np.random.normal(0, 0.15),
               0.3 + np.random.normal(0, 0.05),
               1.82, 0.48, 1.22,
               gt_yaw + np.random.normal(0, 0.08),
               np.random.uniform(0.1, 0.3))

    # --- Edge case 4: GTs with zero interior points (must be excluded) ---
    for i in range(4):
        add_gt(gt_col, "log_003", 300000000, "BUS",
               50.0 + i * 10.0, 30.0, 0.5,
               12.0, 2.8, 3.5, 0.0, 0)

    # --- Edge case 5: Very distant false positives ---
    for i in range(3):
        add_dt(dt_col, "log_003", 100000000, "MOTORCYCLIST",
               105.0 + i * 3.0, 105.0 + i * 3.0, 1.0,
               2.0, 0.8, 1.6, 0.0,
               np.random.uniform(0.7, 0.95))

    # Save as Feather
    os.makedirs('/app/data', exist_ok=True)

    dt_table = pa.table(dt_col)
    gt_table = pa.table(gt_col)

    pf.write_feather(dt_table, '/app/data/detections.feather')
    pf.write_feather(gt_table, '/app/data/ground_truth.feather')

    n_dt = len(dt_col['log_id'])
    n_gt = len(gt_col['log_id'])
    print(f"Generated {n_dt} detections, {n_gt} ground truth entries")
    print("Saved to /app/data/detections.feather and ground_truth.feather")


if __name__ == '__main__':
    generate()
