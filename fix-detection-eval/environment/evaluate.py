#!/usr/bin/env python3
"""3D Object Detection Evaluation Pipeline.

Computes Composite Detection Score (CDS) metrics for 3D object detection.

Reads:  /app/data/ground_truth.json, /app/data/detections.json
Writes: /app/results.json
"""

import json
import numpy as np
from collections import defaultdict
from scipy.spatial.distance import cdist

# ============================================================================
# Configuration
# ============================================================================
AFFINITY_THRESHOLDS_M = (0.5, 1.0, 2.0, 4.0)
TP_THRESHOLD_M = 2.0
MAX_RANGE_M = 150.0
MAX_NUM_DTS_PER_CATEGORY = 100
NUM_RECALL_SAMPLES = 101
MAX_SCALE_ERROR = 1.0
MAX_YAW_RAD_ERROR = np.pi
NUM_DECIMALS = 3
EPS = 1e-10


# ============================================================================
# Geometry Utilities
# ============================================================================
def quat_to_yaw(qw, qx, qy, qz):
    """Convert quaternion (scalar-first) to yaw angle (rotation about z-axis)."""
    siny_cosp = 2.0 * (qw * qz + qx * qy)
    cosy_cosp = 1.0 - 2.0 * (qy * qy + qz * qz)
    return np.arctan2(siny_cosp, cosy_cosp)


def iou_3d_axis_aligned(dims_a, dims_b):
    """Compute axis-aligned 3D IoU between two sets of dimensions (l, w, h).

    Assumes boxes centered at the same point and axis-aligned.
    dims_a, dims_b: (N, 3) arrays of [length, width, height].
    """
    min_dims = np.minimum(dims_a, dims_b)
    intersection = np.prod(min_dims, axis=-1)
    vol_a = np.prod(dims_a, axis=-1)
    vol_b = np.prod(dims_b, axis=-1)
    iou = intersection / (np.maximum(vol_a, vol_b) + EPS)
    return iou


def orientation_error(yaws_dt, yaws_gt):
    """Compute orientation error between predicted and ground truth yaw angles.

    Returns per-element orientation error.
    """
    return yaws_dt - yaws_gt


# ============================================================================
# Evaluation Core
# ============================================================================
def compute_affinity_matrix(dts_xyz, gts_xyz):
    """Compute center-distance affinity (negative Euclidean distance)."""
    if len(dts_xyz) == 0 or len(gts_xyz) == 0:
        return np.zeros((len(dts_xyz), len(gts_xyz)))
    return -cdist(dts_xyz, gts_xyz)


def assign_detections(dts, gts):
    """Assign detections to GT using greedy center-distance matching.

    Args:
        dts: (N, 10) [tx, ty, tz, l, w, h, qw, qx, qy, qz]
        gts: (M, 10) [tx, ty, tz, l, w, h, qw, qx, qy, qz]

    Returns:
        dts_results: (N, T+3) TP flags per threshold + ATE, ASE, AOE
        gts_results: (M, T+3) match flags per threshold + errors
    """
    N, M = len(dts), len(gts)
    T = len(AFFINITY_THRESHOLDS_M)

    dts_results = np.zeros((N, T + 3))
    dts_results[:, T:] = [TP_THRESHOLD_M, MAX_SCALE_ERROR, MAX_YAW_RAD_ERROR]
    gts_results = np.zeros((M, T + 3))

    if N == 0 or M == 0:
        return dts_results, gts_results

    affinity_matrix = compute_affinity_matrix(dts[:, :3], gts[:, :3])

    # For each detection, find best matching GT
    best_gt_per_dt = affinity_matrix.argmax(axis=1)
    best_affinity_per_dt = np.array(
        [affinity_matrix[i, best_gt_per_dt[i]] for i in range(N)]
    )

    # Greedy: first detection (highest score) wins each GT
    unique_gts, first_dt_indices = np.unique(best_gt_per_dt, return_index=True)

    for t_idx, threshold_m in enumerate(AFFINITY_THRESHOLDS_M):
        is_tp = best_affinity_per_dt[first_dt_indices] > -threshold_m

        dts_results[first_dt_indices[is_tp], t_idx] = 1.0
        gts_results[unique_gts[is_tp], t_idx] = 1.0

        if threshold_m != TP_THRESHOLD_M:
            continue
        if not np.any(is_tp):
            continue

        tp_dt_idx = first_dt_indices[is_tp]
        tp_gt_idx = unique_gts[is_tp]

        tp_dts = dts[tp_dt_idx]
        tp_gts = gts[tp_gt_idx]

        # ATE
        ate = np.linalg.norm(tp_dts[:, :3] - tp_gts[:, :3], axis=1)

        # ASE
        ase = 1.0 - iou_3d_axis_aligned(tp_dts[:, 3:6], tp_gts[:, 3:6])

        # AOE
        dt_yaws = np.array(
            [quat_to_yaw(*tp_dts[i, 6:10]) for i in range(len(tp_dts))]
        )
        gt_yaws = np.array(
            [quat_to_yaw(*tp_gts[i, 6:10]) for i in range(len(tp_gts))]
        )
        aoe = orientation_error(dt_yaws, gt_yaws)

        dts_results[tp_dt_idx, T:] = np.stack([ate, ase, aoe], axis=1)

    return dts_results, gts_results


def compute_average_precision(tp_flags, recall_interpolated, num_gts):
    """Compute AP using interpolated precision-recall curve."""
    if len(tp_flags) == 0 or num_gts == 0:
        return 0.0

    cum_tp = np.cumsum(tp_flags).astype(float)
    cum_fp = np.cumsum(~tp_flags).astype(float)

    precision = cum_tp / (cum_tp + cum_fp + EPS)
    recall = cum_tp / num_gts

    precision_at_recall = np.interp(recall_interpolated, recall, precision, right=0)
    return float(np.mean(precision_at_recall))


# ============================================================================
# Main Pipeline
# ============================================================================
def evaluate(detections_data, ground_truth_data):
    """Run the full CDS evaluation pipeline."""
    categories = sorted(set(g["category"] for g in ground_truth_data))
    recall_interpolated = np.linspace(0, 1, NUM_RECALL_SAMPLES, endpoint=True)
    T = len(AFFINITY_THRESHOLDS_M)

    det_groups = defaultdict(list)
    gt_groups = defaultdict(list)

    for d in detections_data:
        det_groups[(d["log_id"], d["timestamp_ns"], d["category"])].append(d)
    for g in ground_truth_data:
        gt_groups[(g["log_id"], g["timestamp_ns"], g["category"])].append(g)

    all_keys = set(det_groups.keys()) | set(gt_groups.keys())

    cat_dts = defaultdict(list)
    cat_n_gts = defaultdict(int)

    for key in sorted(all_keys):
        log_id, ts, cat = key

        dts_raw = det_groups.get(key, [])
        gts_raw = gt_groups.get(key, [])

        if dts_raw:
            dts_arr = np.array(
                [
                    [
                        d["tx_m"], d["ty_m"], d["tz_m"],
                        d["length_m"], d["width_m"], d["height_m"],
                        d["qw"], d["qx"], d["qy"], d["qz"],
                        d["score"],
                    ]
                    for d in dts_raw
                ]
            )
        else:
            dts_arr = np.zeros((0, 11))

        if gts_raw:
            gts_arr = np.array(
                [
                    [
                        g["tx_m"], g["ty_m"], g["tz_m"],
                        g["length_m"], g["width_m"], g["height_m"],
                        g["qw"], g["qx"], g["qy"], g["qz"],
                        g["num_interior_pts"],
                    ]
                    for g in gts_raw
                ]
            )
        else:
            gts_arr = np.zeros((0, 11))

        # Filter detections: range + cap per sweep
        if len(dts_arr) > 0:
            dts_range = np.linalg.norm(dts_arr[:, :3], axis=1)
            range_mask = dts_range < MAX_RANGE_M
            cum_valid = np.cumsum(range_mask)
            cap_mask = cum_valid <= MAX_NUM_DTS_PER_CATEGORY
            dts_arr = dts_arr[range_mask & cap_mask]

        # Filter GTs: range only
        if len(gts_arr) > 0:
            gts_range = np.linalg.norm(gts_arr[:, :3], axis=1)
            gts_mask = gts_range < MAX_RANGE_M
            gts_arr = gts_arr[gts_mask]

        # Sort detections by score
        if len(dts_arr) > 0:
            sort_idx = np.argsort(dts_arr[:, -1])
            dts_arr = dts_arr[sort_idx]

        # Assignment
        dts_metrics, gts_metrics = assign_detections(
            dts_arr[:, :10] if len(dts_arr) > 0 else np.zeros((0, 10)),
            gts_arr[:, :10] if len(gts_arr) > 0 else np.zeros((0, 10)),
        )

        for i in range(len(dts_arr)):
            cat_dts[cat].append((dts_arr[i, -1], dts_metrics[i]))

        cat_n_gts[cat] += len(gts_arr)

    # Per-category summary
    results = {}
    for cat in categories:
        entries = cat_dts.get(cat, [])
        num_gts = cat_n_gts.get(cat, 0)

        if num_gts == 0:
            results[cat] = {
                "AP": 0.0,
                "ATE": float(TP_THRESHOLD_M),
                "ASE": float(MAX_SCALE_ERROR),
                "AOE": float(MAX_YAW_RAD_ERROR),
                "CDS": 0.0,
            }
            continue

        entries.sort(key=lambda x: -x[0])

        aps = []
        for t_idx in range(T):
            tp_flags = np.array([e[1][t_idx] > 0 for e in entries], dtype=bool)
            ap = compute_average_precision(tp_flags, recall_interpolated, num_gts)
            aps.append(ap)

        mean_ap = float(np.mean(aps))

        middle_idx = T // 2
        is_tp = np.array([e[1][middle_idx] > 0 for e in entries], dtype=bool)

        tp_errors = np.array([TP_THRESHOLD_M, MAX_SCALE_ERROR, MAX_YAW_RAD_ERROR])
        if np.any(is_tp):
            tp_vals = np.array([e[1][T:] for e, flag in zip(entries, is_tp) if flag])
            tp_errors = tp_vals.mean(axis=0)

        ate, ase, aoe = tp_errors

        tp_scores = 1.0 - np.array([ate, ase, aoe]) / np.array(
            [TP_THRESHOLD_M, MAX_SCALE_ERROR, MAX_YAW_RAD_ERROR]
        )
        cds = mean_ap * np.sum(tp_scores)

        results[cat] = {
            "AP": round(mean_ap, NUM_DECIMALS),
            "ATE": round(float(ate), NUM_DECIMALS),
            "ASE": round(float(ase), NUM_DECIMALS),
            "AOE": round(float(aoe), NUM_DECIMALS),
            "CDS": round(float(cds), NUM_DECIMALS),
        }

    mean_metrics = {}
    for metric in ["AP", "ATE", "ASE", "AOE", "CDS"]:
        vals = [results[cat][metric] for cat in categories]
        mean_metrics[metric] = round(float(np.mean(vals)), NUM_DECIMALS)
    results["AVERAGE_METRICS"] = mean_metrics

    return results


def main():
    with open("/app/data/ground_truth.json") as f:
        gt_data = json.load(f)
    with open("/app/data/detections.json") as f:
        det_data = json.load(f)

    results = evaluate(det_data, gt_data)

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print("Evaluation complete. Results written to /app/results.json")


if __name__ == "__main__":
    main()
