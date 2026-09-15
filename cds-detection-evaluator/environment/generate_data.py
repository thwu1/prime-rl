#!/usr/bin/env python3
"""Generate synthetic multi-format scene flow benchmark data.

Creates ground truth annotations in Feather format and predictions from
four models in different formats: Feather, Parquet (non-standard columns),
ZIP-archived Feather, and CSV (ego-motion biased, non-standard columns).
"""

import json
import os
import random
import shutil
import zipfile

import numpy as np
import pandas as pd

NUM_CATEGORIES = 5
CAT_PROBS = [0.48, 0.18, 0.15, 0.11, 0.08]

LOGS = [
    {"id": "log_a001", "timestamps": [315968000, 315968100, 315968200, 315968300, 315968400, 315968500]},
    {"id": "log_a002", "timestamps": [315970000, 315970100, 315970200, 315970300, 315970400]},
    {"id": "log_a003", "timestamps": [315972000, 315972100, 315972200, 315972300]},
]

MODELS = {
    "alpha": {"flow_noise": 0.07, "outlier_rate": 0.015, "seg_error": 0.06},
    "beta":  {"flow_noise": 0.18, "outlier_rate": 0.065, "seg_error": 0.16},
    "gamma": {"flow_noise": 0.30, "outlier_rate": 0.12,  "seg_error": 0.24},
    "delta": {"flow_noise": 0.12, "outlier_rate": 0.04,  "seg_error": 0.10},
}


def generate_ground_truth(n, rng):
    cats = rng.choice(NUM_CATEGORIES, size=n, p=CAT_PROBS).astype(np.uint8)
    fg = cats > 0
    bg = cats == 0
    is_dynamic = np.zeros(n, dtype=bool)
    is_dynamic[fg] = rng.random(fg.sum()) < 0.26
    is_dynamic[bg] = rng.random(bg.sum()) < 0.04
    is_close = rng.random(n) < 0.53
    is_valid = rng.random(n) < 0.91
    gt_flow = rng.normal(0, 0.013, (n, 3))
    dyn_count = is_dynamic.sum()
    if dyn_count > 0:
        gt_flow[is_dynamic] = rng.normal(0, 0.58, (dyn_count, 3))
    return gt_flow.astype(np.float32), cats, is_dynamic, is_close, is_valid


def generate_prediction(gt_flow, is_dynamic, model_cfg, rng):
    n = len(gt_flow)
    noise_scale = np.where(
        is_dynamic, model_cfg["flow_noise"] * 1.8, model_cfg["flow_noise"]
    )
    pred_flow = gt_flow + rng.normal(0, 1, (n, 3)) * noise_scale[:, None]
    bad = rng.random(n) < model_cfg["outlier_rate"]
    bad_count = bad.sum()
    if bad_count > 0:
        pred_flow[bad] = rng.normal(0, 1.5, (bad_count, 3))
    pred_dyn = is_dynamic.copy()
    flip = rng.random(n) < model_cfg["seg_error"]
    pred_dyn[flip] = ~pred_dyn[flip]
    return pred_flow.astype(np.float32), pred_dyn


# Generate ego-motion displacements per sweep (used for delta model's bias)
ego_rng = np.random.RandomState(7777)
ego_displacements = {}
ego_poses_json = {}
for log in LOGS:
    lid = log["id"]
    ego_poses_json[lid] = {}
    for ts in log["timestamps"]:
        disp = ego_rng.uniform(-0.15, 0.15, 3).astype(np.float64)
        ego_displacements[(lid, ts)] = disp
        ego_poses_json[lid][str(ts)] = {
            "ego_displacement_m": [round(float(x), 8) for x in disp]
        }

os.makedirs("/app", exist_ok=True)
with open("/app/ego_poses.json", "w") as f:
    json.dump(ego_poses_json, f, indent=2)

# Phase 1: Generate ground truth with deterministic seed
gt_rng = np.random.RandomState(2024)
size_rng = random.Random(2024)
all_gt = {}

for log in LOGS:
    lid = log["id"]
    os.makedirs(f"/app/ground_truth/{lid}", exist_ok=True)
    for ts in log["timestamps"]:
        n = size_rng.randint(600, 1100)
        gt_flow, cats, is_dyn, is_close, is_valid = generate_ground_truth(n, gt_rng)
        all_gt[(lid, ts)] = (n, gt_flow, cats, is_dyn, is_close, is_valid)
        pd.DataFrame({
            "flow_tx_m": gt_flow[:, 0],
            "flow_ty_m": gt_flow[:, 1],
            "flow_tz_m": gt_flow[:, 2],
            "category_indices": cats,
            "is_dynamic": is_dyn,
            "is_close": is_close,
            "is_valid": is_valid,
        }).to_feather(f"/app/ground_truth/{lid}/{ts}.feather")

# Phase 2: Generate predictions for each model with independent seeds
for model_idx, (model_name, model_cfg) in enumerate(MODELS.items()):
    pred_rng = np.random.RandomState(5000 + model_idx * 131)
    for (lid, ts), (n, gt_flow, cats, is_dyn, is_close, is_valid) in sorted(all_gt.items()):
        pred_flow, pred_dyn = generate_prediction(gt_flow, is_dyn, model_cfg, pred_rng)

        if model_name == "alpha":
            d = f"/app/submissions/alpha/{lid}"
            os.makedirs(d, exist_ok=True)
            pd.DataFrame({
                "flow_tx_m": pred_flow[:, 0],
                "flow_ty_m": pred_flow[:, 1],
                "flow_tz_m": pred_flow[:, 2],
                "is_dynamic": pred_dyn,
            }).to_feather(f"{d}/{ts}.feather")

        elif model_name == "beta":
            d = f"/app/submissions/beta/{lid}"
            os.makedirs(d, exist_ok=True)
            pd.DataFrame({
                "pred_x": pred_flow[:, 0],
                "pred_y": pred_flow[:, 1],
                "pred_z": pred_flow[:, 2],
                "dynamic_flag": pred_dyn,
            }).to_parquet(f"{d}/{ts}.parquet")

        elif model_name == "gamma":
            d = f"/tmp/gamma_staging/{lid}"
            os.makedirs(d, exist_ok=True)
            pd.DataFrame({
                "flow_tx_m": pred_flow[:, 0],
                "flow_ty_m": pred_flow[:, 1],
                "flow_tz_m": pred_flow[:, 2],
                "is_dynamic": pred_dyn,
            }).to_feather(f"{d}/{ts}.feather")

        elif model_name == "delta":
            d = f"/app/submissions/delta/{lid}"
            os.makedirs(d, exist_ok=True)
            ego_disp = ego_displacements[(lid, ts)]
            biased_flow = pred_flow + ego_disp[np.newaxis, :].astype(np.float32)
            pd.DataFrame({
                "dx": biased_flow[:, 0],
                "dy": biased_flow[:, 1],
                "dz": biased_flow[:, 2],
                "dynamic": pred_dyn.astype(int),
            }).to_csv(f"{d}/{ts}.csv", index=False)

# Create ZIP archive for gamma
os.makedirs("/app/submissions", exist_ok=True)
with zipfile.ZipFile("/app/submissions/gamma.zip", "w", zipfile.ZIP_DEFLATED) as zf:
    for root, dirs, files in os.walk("/tmp/gamma_staging"):
        for f in sorted(files):
            full = os.path.join(root, f)
            arc = os.path.relpath(full, "/tmp/gamma_staging")
            zf.write(full, arc)
shutil.rmtree("/tmp/gamma_staging")

total_sweeps = sum(len(log["timestamps"]) for log in LOGS)
total_points = sum(v[0] for v in all_gt.values())
print(f"Generated {total_sweeps} sweeps, {total_points} points, 4 model submissions")
