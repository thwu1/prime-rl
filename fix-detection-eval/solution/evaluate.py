#!/usr/bin/env python3
"""Argoverse 2 Scene Flow Evaluation Pipeline."""

import json
import os
from collections import defaultdict

import numpy as np
import pandas as pd

EPS = 1e-10
EXCLUDED = ("Background", "Dynamic")
METRIC_NAMES = ["EPE", "Accuracy Strict", "Accuracy Relax", "Angle Error"]


def compute_flow_metrics(pred, gt, strict_th, relax_th, time_delta):
    """Compute all four av2 scene flow metrics for a point subset."""
    diff = pred - gt
    diff_norm = np.linalg.norm(diff, axis=-1)
    gt_norm = np.linalg.norm(gt, axis=-1)
    rel_err = diff_norm / (gt_norm + EPS)

    epe = float(diff_norm.mean())

    acc_strict = float(
        np.logical_or(diff_norm < strict_th, rel_err < strict_th)
        .astype(np.float64)
        .mean()
    )
    acc_relax = float(
        np.logical_or(diff_norm < relax_th, rel_err < relax_th)
        .astype(np.float64)
        .mean()
    )

    # 4D space-time angle error
    pred_4d = np.pad(pred, ((0, 0), (0, 1)), constant_values=time_delta)
    gt_4d = np.pad(gt, ((0, 0), (0, 1)), constant_values=time_delta)
    unit_pred = pred_4d / np.linalg.norm(pred_4d, axis=-1, keepdims=True)
    unit_gt = gt_4d / np.linalg.norm(gt_4d, axis=-1, keepdims=True)
    dot = np.clip(np.einsum("ij,ij->i", unit_pred, unit_gt), -1.0, 1.0)
    angle_err = float(np.arccos(dot).mean())

    return {
        "EPE": epe,
        "Accuracy Strict": acc_strict,
        "Accuracy Relax": acc_relax,
        "Angle Error": angle_err,
    }


def main():
    with open("/app/config.json") as f:
        cfg = json.load(f)

    time_delta = cfg["sweep_pair_time_delta"]
    strict_th = cfg["accuracy_strict_threshold"]
    relax_th = cfg["accuracy_relax_threshold"]
    fg_cats = cfg["foreground_categories"]
    bg_cats = cfg["background_categories"]
    ann_dir = cfg["annotations_dir"]
    pred_dir = cfg["predictions_dir"]
    out_path = cfg["output_path"]

    class_map = {"Foreground": fg_cats, "Background": bg_cats}

    subset_records = defaultdict(list)
    global_tp, global_fp, global_fn = 0, 0, 0

    ann_files = sorted(f for f in os.listdir(ann_dir) if f.endswith(".npz"))

    for ann_file in ann_files:
        scene_id = ann_file[:-4]

        gt = np.load(os.path.join(ann_dir, ann_file))
        gt_flow = gt["flow"]
        gt_dynamic = gt["is_dynamic"]
        cat_indices = gt["category_indices"]
        is_close = gt["is_close"]
        is_valid = gt["is_valid"]

        pred_df = pd.read_feather(os.path.join(pred_dir, f"{scene_id}.feather"))
        pred_flow = np.stack(
            [
                pred_df["flow_tx_m"].values.astype(np.float64),
                pred_df["flow_ty_m"].values.astype(np.float64),
                pred_df["flow_tz_m"].values.astype(np.float64),
            ],
            axis=1,
        )
        pred_dynamic = pred_df["is_dynamic"].values.astype(bool)

        valid = is_valid.astype(bool)
        gt_flow_v = gt_flow[valid].astype(np.float64)
        pred_flow_v = pred_flow[valid]
        gt_dyn_v = gt_dynamic[valid].astype(bool)
        pred_dyn_v = pred_dynamic[valid]
        cat_v = cat_indices[valid]
        close_v = is_close[valid].astype(bool)

        global_tp += int(np.logical_and(pred_dyn_v, gt_dyn_v).sum())
        global_fp += int(np.logical_and(pred_dyn_v, ~gt_dyn_v).sum())
        global_fn += int(np.logical_and(~pred_dyn_v, gt_dyn_v).sum())

        for cls_name, cats in class_map.items():
            cls_mask = np.isin(cat_v, cats)
            for mot_name, mot_flag in [("Dynamic", True), ("Static", False)]:
                mot_mask = gt_dyn_v == mot_flag
                for dist_name, dist_flag in [("Close", True), ("Far", False)]:
                    dist_mask = close_v == dist_flag
                    mask = cls_mask & mot_mask & dist_mask
                    count = int(mask.sum())

                    record = {"count": count}
                    if count > 0:
                        metrics = compute_flow_metrics(
                            pred_flow_v[mask],
                            gt_flow_v[mask],
                            strict_th,
                            relax_th,
                            time_delta,
                        )
                        record.update(metrics)

                    subset_records[(cls_name, mot_name, dist_name)].append(record)

    output_metrics = {}

    for (cls, mot, dist), scene_recs in subset_records.items():
        if (cls, mot) == EXCLUDED:
            continue
        total = sum(r["count"] for r in scene_recs)
        for m in METRIC_NAMES:
            key = f"{m}/{cls}/{mot}/{dist}"
            if total > 0:
                wsum = sum(r[m] * r["count"] for r in scene_recs if r["count"] > 0)
                output_metrics[key] = round(wsum / total, 6)
            else:
                output_metrics[key] = None

    for cls_name in class_map:
        for mot in ["Dynamic", "Static"]:
            if (cls_name, mot) == EXCLUDED:
                continue
            close_recs = subset_records.get((cls_name, mot, "Close"), [])
            far_recs = subset_records.get((cls_name, mot, "Far"), [])
            all_recs = close_recs + far_recs
            total = sum(r["count"] for r in all_recs)
            for m in METRIC_NAMES:
                key = f"{m}/{cls_name}/{mot}"
                if total > 0:
                    wsum = sum(r[m] * r["count"] for r in all_recs if r["count"] > 0)
                    output_metrics[key] = round(wsum / total, 6)
                else:
                    output_metrics[key] = None

    epe_3way = sum(
        output_metrics.get(f"EPE/{c}", 0) or 0
        for c in ["Foreground/Dynamic", "Foreground/Static", "Background/Static"]
    ) / 3.0

    dynamic_iou = global_tp / (global_tp + global_fp + global_fn + EPS)

    results = {
        "metrics": output_metrics,
        "EPE_3Way": round(epe_3way, 6),
        "Dynamic_IoU": round(dynamic_iou, 6),
    }

    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)

    print(f"Evaluation complete. Results written to {out_path}")


if __name__ == "__main__":
    main()
