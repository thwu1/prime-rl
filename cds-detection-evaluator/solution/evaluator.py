#!/usr/bin/env python3
"""Scene flow benchmark evaluation pipeline using DuckDB.

Reads ground truth and predictions from four models in different formats,
computes scene flow metrics, stores results in DuckDB, and produces a
ranked leaderboard with Composite Scene Flow Scores derived from CDS methodology.
"""

import json
import math
import os
import zipfile
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

# Constants derived from reference evaluation code
SWEEP_PAIR_TIME_DELTA = 0.1
ACCURACY_STRICT_THRESH = 0.05
ACCURACY_RELAX_THRESH = 0.10
EPS = 1e-10
CATEGORY_MAP = {"Background": [0], "Foreground": [1, 2, 3, 4]}
EXCLUDE = ("Background", "Dynamic")
FLOW_COLS = ["flow_tx_m", "flow_ty_m", "flow_tz_m"]
GROUPS_3WAY = ["Foreground/Dynamic", "Foreground/Static", "Background/Static"]

# CDS-derived normalization constants (from detection eval reference)
# ATE threshold = 2.0m for translation-type errors -> EPE threshold = 2.0
# AOE threshold = pi for orientation-type errors -> Angle Error threshold = pi
EPE_NORM_THRESHOLD = 2.0
ANGLE_NORM_THRESHOLD = math.pi

GT_DIR = Path("/app/ground_truth")
SUB_DIR = Path("/app/submissions")
DB_PATH = "/app/benchmark.duckdb"
OUTPUT_PATH = "/app/leaderboard.json"
EGO_POSES_PATH = "/app/ego_poses.json"


def load_ego_poses():
    """Load ego-motion displacement data."""
    with open(EGO_POSES_PATH) as f:
        return json.load(f)


def load_predictions(model_name, anno_rel, ego_poses=None):
    """Load predictions for a model, handling format conversion and ego-motion compensation."""
    if model_name == "alpha":
        return pd.read_feather(SUB_DIR / "alpha" / anno_rel)
    elif model_name == "beta":
        parts = anno_rel.parts
        pq_name = parts[1].replace(".feather", ".parquet")
        df = pd.read_parquet(SUB_DIR / "beta" / parts[0] / pq_name)
        return df.rename(columns={
            "pred_x": "flow_tx_m",
            "pred_y": "flow_ty_m",
            "pred_z": "flow_tz_m",
            "dynamic_flag": "is_dynamic",
        })
    elif model_name == "gamma":
        with zipfile.ZipFile(SUB_DIR / "gamma.zip") as zf:
            return pd.read_feather(zf.open(anno_rel.as_posix()))
    elif model_name == "delta":
        parts = anno_rel.parts
        csv_name = parts[1].replace(".feather", ".csv")
        df = pd.read_csv(SUB_DIR / "delta" / parts[0] / csv_name)
        df = df.rename(columns={
            "dx": "flow_tx_m",
            "dy": "flow_ty_m",
            "dz": "flow_tz_m",
            "dynamic": "is_dynamic",
        })
        df["is_dynamic"] = df["is_dynamic"].astype(bool)
        # Apply ego-motion compensation: subtract ego displacement
        # Delta's predictions are in the global frame; ground truth is ego-frame
        log_id = parts[0]
        ts_str = parts[1].replace(".feather", "")
        ego_disp = ego_poses[log_id][ts_str]["ego_displacement_m"]
        df["flow_tx_m"] -= ego_disp[0]
        df["flow_ty_m"] -= ego_disp[1]
        df["flow_tz_m"] -= ego_disp[2]
        return df


def compute_point_metrics(gt_flow, pred_flow):
    """Compute per-point scene flow metrics."""
    epe = np.linalg.norm(pred_flow - gt_flow, axis=-1)

    gt_mag = np.linalg.norm(gt_flow, axis=-1)
    rel_err = epe / (gt_mag + EPS)
    acc_strict = ((epe < ACCURACY_STRICT_THRESH) | (rel_err < ACCURACY_STRICT_THRESH)).astype(float)
    acc_relax = ((epe < ACCURACY_RELAX_THRESH) | (rel_err < ACCURACY_RELAX_THRESH)).astype(float)

    gt_4d = np.concatenate([gt_flow, np.full((len(gt_flow), 1), SWEEP_PAIR_TIME_DELTA)], axis=1)
    pred_4d = np.concatenate([pred_flow, np.full((len(pred_flow), 1), SWEEP_PAIR_TIME_DELTA)], axis=1)
    gt_unit = gt_4d / np.linalg.norm(gt_4d, axis=-1, keepdims=True)
    pred_unit = pred_4d / np.linalg.norm(pred_4d, axis=-1, keepdims=True)
    dot = np.sum(gt_unit * pred_unit, axis=1)
    angle_err = np.arccos(np.clip(dot, -1.0, 1.0))

    return epe, acc_strict, acc_relax, angle_err


def main():
    ego_poses = load_ego_poses()

    # Initialize DuckDB
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    conn = duckdb.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE point_metrics (
            model TEXT,
            log_id TEXT,
            timestamp_ns BIGINT,
            class_name TEXT,
            motion TEXT,
            is_close BOOLEAN,
            epe DOUBLE,
            accuracy_strict DOUBLE,
            accuracy_relaxed DOUBLE,
            angle_error DOUBLE,
            pred_dynamic BOOLEAN,
            gt_dynamic BOOLEAN
        )
    """)

    anno_files = sorted(GT_DIR.rglob("*.feather"))

    for model_name in ["alpha", "beta", "gamma", "delta"]:
        print(f"Processing model: {model_name}")
        for anno_file in anno_files:
            rel = anno_file.relative_to(GT_DIR)
            log_id = rel.parts[0]
            ts = int(rel.stem)

            gt = pd.read_feather(anno_file)
            pred = load_predictions(model_name, rel, ego_poses)

            valid = gt["is_valid"].to_numpy().astype(bool)

            gt_flow = gt[FLOW_COLS].to_numpy().astype(np.float64)[valid]
            pred_flow = pred[FLOW_COLS].to_numpy().astype(np.float64)[valid]
            cats = gt["category_indices"].to_numpy().astype(int)[valid]
            gt_dyn = gt["is_dynamic"].to_numpy().astype(bool)[valid]
            pred_dyn = pred["is_dynamic"].to_numpy().astype(bool)[valid]
            is_close = gt["is_close"].to_numpy().astype(bool)[valid]

            epe, acc_s, acc_r, angle = compute_point_metrics(gt_flow, pred_flow)

            class_names = np.where(np.isin(cats, [0]), "Background", "Foreground")
            motion_labels = np.where(gt_dyn, "Dynamic", "Static")

            n_valid = len(epe)
            df = pd.DataFrame({
                "model": [model_name] * n_valid,
                "log_id": [log_id] * n_valid,
                "timestamp_ns": np.int64(ts),
                "class_name": class_names,
                "motion": motion_labels,
                "is_close": is_close,
                "epe": epe,
                "accuracy_strict": acc_s,
                "accuracy_relaxed": acc_r,
                "angle_error": angle,
                "pred_dynamic": pred_dyn,
                "gt_dynamic": gt_dyn,
            })
            conn.execute("INSERT INTO point_metrics SELECT * FROM df")

    # Aggregate per-subset using SQL
    subset_df = conn.execute("""
        SELECT model, class_name, motion,
               CASE WHEN is_close THEN 'Close' ELSE 'Far' END AS distance,
               AVG(epe) AS mean_epe,
               AVG(accuracy_strict) AS mean_acc_s,
               AVG(accuracy_relaxed) AS mean_acc_r,
               AVG(angle_error) AS mean_angle
        FROM point_metrics
        WHERE NOT (class_name = 'Background' AND motion = 'Dynamic')
        GROUP BY model, class_name, motion, distance
    """).fetchdf()

    # Aggregate per-class/motion using SQL
    cm_df = conn.execute("""
        SELECT model, class_name, motion,
               AVG(epe) AS mean_epe,
               AVG(accuracy_strict) AS mean_acc_s,
               AVG(accuracy_relaxed) AS mean_acc_r,
               AVG(angle_error) AS mean_angle
        FROM point_metrics
        WHERE NOT (class_name = 'Background' AND motion = 'Dynamic')
        GROUP BY model, class_name, motion
    """).fetchdf()

    # Dynamic IoU per model using SQL
    iou_df = conn.execute("""
        SELECT model,
               SUM(CASE WHEN pred_dynamic AND gt_dynamic THEN 1 ELSE 0 END) AS tp,
               SUM(CASE WHEN pred_dynamic AND NOT gt_dynamic THEN 1 ELSE 0 END) AS fp,
               SUM(CASE WHEN NOT pred_dynamic AND gt_dynamic THEN 1 ELSE 0 END) AS fn
        FROM point_metrics
        GROUP BY model
    """).fetchdf()

    conn.close()

    # Build leaderboard
    models = {}
    for model_name in ["alpha", "beta", "gamma", "delta"]:
        # Per-subset
        per_subset = {}
        sub = subset_df[subset_df["model"] == model_name]
        for _, row in sub.iterrows():
            key = f"{row['class_name']}/{row['motion']}/{row['distance']}"
            per_subset[key] = {
                "EPE": round(float(row["mean_epe"]), 6),
                "Accuracy Strict": round(float(row["mean_acc_s"]), 6),
                "Accuracy Relaxed": round(float(row["mean_acc_r"]), 6),
                "Angle Error": round(float(row["mean_angle"]), 6),
            }

        # Per-class/motion
        per_cm = {}
        cm = cm_df[cm_df["model"] == model_name]
        for _, row in cm.iterrows():
            key = f"{row['class_name']}/{row['motion']}"
            per_cm[key] = {
                "EPE": round(float(row["mean_epe"]), 6),
                "Accuracy Strict": round(float(row["mean_acc_s"]), 6),
                "Accuracy Relaxed": round(float(row["mean_acc_r"]), 6),
                "Angle Error": round(float(row["mean_angle"]), 6),
            }

        # Dynamic IoU
        iou_row = iou_df[iou_df["model"] == model_name].iloc[0]
        tp = float(iou_row["tp"])
        fp = float(iou_row["fp"])
        fn = float(iou_row["fn"])
        dynamic_iou = tp / (tp + fp + fn) if (tp + fp + fn) > 0 else 0.0

        # 3-way averages
        epe_3way = float(np.mean([per_cm[g]["EPE"] for g in GROUPS_3WAY]))
        acc_s_3way = float(np.mean([per_cm[g]["Accuracy Strict"] for g in GROUPS_3WAY]))
        acc_r_3way = float(np.mean([per_cm[g]["Accuracy Relaxed"] for g in GROUPS_3WAY]))
        angle_3way = float(np.mean([per_cm[g]["Angle Error"] for g in GROUPS_3WAY]))

        # CSFS — derived from CDS methodology:
        # quality_term = Dynamic IoU (analogous to mAP in detection)
        # EPE score: max(0, 1 - EPE_3way / 2.0) — translation error normalization
        # Accuracy score: mean(strict, relaxed) — already [0,1], combined into one component
        # Angle score: max(0, 1 - angle_3way / pi) — orientation error normalization
        # CSFS = quality_term * mean(epe_score, accuracy_score, angle_score)
        epe_score = max(0.0, 1.0 - epe_3way / EPE_NORM_THRESHOLD)
        acc_score = (acc_s_3way + acc_r_3way) / 2.0
        angle_score = max(0.0, 1.0 - angle_3way / ANGLE_NORM_THRESHOLD)
        csfs = dynamic_iou * (epe_score + acc_score + angle_score) / 3.0

        models[model_name] = {
            "csfs": round(csfs, 6),
            "dynamic_iou": round(dynamic_iou, 6),
            "epe_3way": round(epe_3way, 6),
            "accuracy_strict_3way": round(acc_s_3way, 6),
            "accuracy_relaxed_3way": round(acc_r_3way, 6),
            "angle_error_3way": round(angle_3way, 6),
            "per_subset": per_subset,
            "per_class_motion": per_cm,
        }

    # Rank by CSFS descending
    ranked = sorted(models.items(), key=lambda x: x[1]["csfs"], reverse=True)
    leaderboard = {"ranking": []}
    for rank, (name, data) in enumerate(ranked, 1):
        entry = {"rank": rank, "model": name}
        entry.update(data)
        leaderboard["ranking"].append(entry)

    with open(OUTPUT_PATH, "w") as f:
        json.dump(leaderboard, f, indent=2)

    print(f"Leaderboard written to {OUTPUT_PATH}")
    for entry in leaderboard["ranking"]:
        print(f"  #{entry['rank']} {entry['model']}: CSFS={entry['csfs']:.6f}")


if __name__ == "__main__":
    main()
