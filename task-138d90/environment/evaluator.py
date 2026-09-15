#!/usr/bin/env python3
"""
3D Object Detection Evaluator — Skeleton

Reads detection predictions and ground truth annotations from Apache Feather
files in /app/data/, evaluates using the protocol in /app/spec.md, and writes
results to /app/results.json.

Five core functions are marked TODO and raise NotImplementedError.
Implement them according to the specification document.
"""


import json
import sys
import tomllib
import numpy as np
import pyarrow.feather as pf
from pathlib import Path

# ============================================================
# Configuration (loaded from /app/config.toml)
# ============================================================

with open('/app/config.toml', 'rb') as _cfg_file:
    CONFIG = tomllib.load(_cfg_file)

AFFINITY_THRESHOLDS_M = CONFIG['evaluation']['affinity_thresholds_m']
TP_THRESHOLD_M = CONFIG['evaluation']['tp_threshold_m']
MAX_RANGE_M = CONFIG['evaluation']['max_range_m']
MAX_NUM_DTS = CONFIG['evaluation']['max_detections_per_category']
NUM_RECALL_SAMPLES = CONFIG['evaluation']['num_recall_samples']
TP_NORMS = CONFIG['evaluation']['tp_norms']
OUTPUT_DECIMALS = CONFIG['output']['decimal_places']


# ============================================================
# Data loading (implemented)
# ============================================================

def load_data(data_dir):
    """Load detections and ground truth from Apache Feather files.

    Returns two lists of dicts, one for detections and one for ground truth.
    Each dict has keys: log_id, timestamp_ns, category, tx, ty, tz,
    length, width, height, yaw, and either 'score' or 'num_interior_pts'.
    """
    dt_table = pf.read_table(data_dir / "detections.feather")
    gt_table = pf.read_table(data_dir / "ground_truth.feather")
    return dt_table.to_pylist(), gt_table.to_pylist()


# ============================================================
# Helper functions (implemented)
# ============================================================

def compute_center_distance(a, b):
    """Euclidean (L2) distance between two 3D object centers."""
    return float(np.sqrt(
        (a['tx'] - b['tx'])**2 +
        (a['ty'] - b['ty'])**2 +
        (a['tz'] - b['tz'])**2
    ))


def compute_scale_error(dt, gt):
    """Compute scale error: 1 - axis-aligned dimension IoU.

    IoU_aligned = prod(min(d_i^dt, d_i^gt) / max(d_i^dt, d_i^gt))
    for dimensions length, width, height.
    """
    dims_dt = np.array([dt['length'], dt['width'], dt['height']])
    dims_gt = np.array([gt['length'], gt['width'], gt['height']])
    iou = float(np.prod(np.minimum(dims_dt, dims_gt) / np.maximum(dims_dt, dims_gt)))
    return 1.0 - iou


# ============================================================
# TODO: Implement the following 5 functions per /app/spec.md
# ============================================================

def filter_by_range(entries, max_range):
    """Filter entries to include only those within max_range of the origin.

    See spec.md Section 3.1 for the distance formula.

    Args:
        entries: List of dicts, each with 'tx', 'ty', 'tz' float fields.
        max_range: Maximum range in meters (exclusive).

    Returns:
        List of entries whose range is strictly less than max_range.
    """
    raise NotImplementedError("Implement per spec Section 3.1")


def greedy_assign(sweep_dts, sweep_gts, threshold):
    """Greedy assignment of detections to ground truth annotations.

    See spec.md Section 3.4 for the assignment protocol.

    Args:
        sweep_dts: List of detection dicts (must include 'score', 'tx', 'ty', 'tz').
        sweep_gts: List of ground truth dicts (must include 'tx', 'ty', 'tz').
        threshold: Maximum center distance for a valid assignment (meters).

    Returns:
        Dict mapping detection index (int) to matched ground truth index (int).
    """
    raise NotImplementedError("Implement per spec Section 3.4")


def compute_average_precision(tp_flags, num_gts):
    """Compute Average Precision with VOC-style interpolation.

    See spec.md Section 3.5 for the full AP computation protocol.

    Args:
        tp_flags: Boolean numpy array — True at position i means detection i
                  (sorted by descending score) is a true positive.
        num_gts: Total number of ground truth annotations for this category.

    Returns:
        Average precision value in [0, 1].
    """
    raise NotImplementedError("Implement per spec Section 3.5")


def compute_orientation_error(yaw_dt, yaw_gt):
    """Compute orientation error between two heading angles.

    See spec.md Section 3.6.3 for the orientation error formula.
    Must handle the circular nature of angles correctly.

    Args:
        yaw_dt: Detection heading angle in radians.
        yaw_gt: Ground truth heading angle in radians.

    Returns:
        Absolute angular error in [0, pi].
    """
    raise NotImplementedError("Implement per spec Section 3.6.3")


def compute_composite_score(ap, ate, ase, aoe):
    """Compute Composite Detection Score (CDS).

    See spec.md Section 3.7 for the CDS formula.
    Uses normalization constants from the module-level TP_NORMS dict.

    Args:
        ap: Average Precision value.
        ate: Average Translation Error.
        ase: Average Scale Error.
        aoe: Average Orientation Error.

    Returns:
        CDS value in [0, 1].
    """
    raise NotImplementedError("Implement per spec Section 3.7")


# ============================================================
# Main evaluation pipeline (implemented)
# ============================================================

def evaluate(data_dir, output_path):
    """Run the full evaluation pipeline.

    For each object category:
      1. Filter by range and category.
      2. For each sweep, perform greedy assignment at multiple thresholds.
      3. Compute AP across thresholds.
      4. Compute true positive error metrics (ATE, ASE, AOE).
      5. Compute Composite Detection Score (CDS).
    """
    dts_all, gts_all = load_data(data_dir)

    # Step 1: Range filtering
    dts_all = filter_by_range(dts_all, MAX_RANGE_M)
    gts_all = filter_by_range(gts_all, MAX_RANGE_M)

    # Discover categories from ground truth
    categories = sorted(set(g['category'] for g in gts_all))

    results = {}

    for category in categories:
        cat_dts = [d for d in dts_all if d['category'] == category]
        cat_gts = [g for g in gts_all if g['category'] == category]

        # Collect unique sweep keys
        sweep_keys = set()
        for d in cat_dts:
            sweep_keys.add((d['log_id'], d['timestamp_ns']))
        for g in cat_gts:
            sweep_keys.add((g['log_id'], g['timestamp_ns']))

        all_entries = []
        num_gts_total = 0

        for sweep_key in sorted(sweep_keys):
            log_id, ts = sweep_key
            sweep_dts = [d for d in cat_dts
                         if d['log_id'] == log_id and d['timestamp_ns'] == ts]
            sweep_gts = [g for g in cat_gts
                         if g['log_id'] == log_id and g['timestamp_ns'] == ts]

            # Limit detections per sweep
            sweep_dts = sorted(sweep_dts, key=lambda x: x['score'],
                               reverse=True)[:MAX_NUM_DTS]

            # Filter GTs with 0 interior points
            sweep_gts = [g for g in sweep_gts
                         if g.get('num_interior_pts', 1) > 0]
            num_gts_total += len(sweep_gts)

            if not sweep_dts:
                continue

            # Assignment at each affinity threshold
            thresh_assignments = {}
            for threshold in AFFINITY_THRESHOLDS_M:
                thresh_assignments[threshold] = greedy_assign(
                    sweep_dts, sweep_gts, threshold)

            # Build per-detection entries
            for dt_idx, dt in enumerate(sweep_dts):
                tp_flags = {t: dt_idx in thresh_assignments[t]
                            for t in AFFINITY_THRESHOLDS_M}

                # Default TP errors (upper bounds for non-TPs)
                ate = TP_NORMS['ATE']
                ase = TP_NORMS['ASE']
                aoe = TP_NORMS['AOE']

                if tp_flags.get(TP_THRESHOLD_M, False):
                    gt_idx = thresh_assignments[TP_THRESHOLD_M][dt_idx]
                    gt = sweep_gts[gt_idx]
                    ate = compute_center_distance(dt, gt)
                    ase = compute_scale_error(dt, gt)
                    aoe = compute_orientation_error(dt['yaw'], gt['yaw'])

                all_entries.append({
                    'score': dt['score'],
                    'tp_flags': tp_flags,
                    'ate': ate,
                    'ase': ase,
                    'aoe': aoe,
                })

        # Sort globally by score descending
        all_entries.sort(key=lambda x: x['score'], reverse=True)

        # Compute AP at each affinity threshold
        aps = []
        for threshold in AFFINITY_THRESHOLDS_M:
            tps = np.array([e['tp_flags'][threshold]
                            for e in all_entries], dtype=bool)
            ap = compute_average_precision(tps, num_gts_total)
            aps.append(ap)

        mean_ap = float(np.mean(aps))

        # Compute mean TP errors
        tp_entries = [e for e in all_entries
                      if e['tp_flags'].get(TP_THRESHOLD_M, False)]
        if tp_entries:
            mean_ate = float(np.mean([e['ate'] for e in tp_entries]))
            mean_ase = float(np.mean([e['ase'] for e in tp_entries]))
            mean_aoe = float(np.mean([e['aoe'] for e in tp_entries]))
        else:
            mean_ate = TP_NORMS['ATE']
            mean_ase = TP_NORMS['ASE']
            mean_aoe = TP_NORMS['AOE']

        cds = compute_composite_score(mean_ap, mean_ate, mean_ase, mean_aoe)

        results[category] = {
            'AP': round(mean_ap, OUTPUT_DECIMALS),
            'ATE': round(mean_ate, OUTPUT_DECIMALS),
            'ASE': round(mean_ase, OUTPUT_DECIMALS),
            'AOE': round(mean_aoe, OUTPUT_DECIMALS),
            'CDS': round(cds, OUTPUT_DECIMALS),
        }

    # Compute average metrics across categories
    avg = {}
    for metric in ['AP', 'ATE', 'ASE', 'AOE', 'CDS']:
        vals = [results[c][metric] for c in categories]
        avg[metric] = round(float(np.mean(vals)), OUTPUT_DECIMALS)
    results['AVERAGE_METRICS'] = avg

    # Write results
    with open(output_path, 'w') as f:
        json.dump(results, f, indent=2)

    return results


if __name__ == '__main__':
    data_dir = Path('/app/data')
    output_path = Path('/app/results.json')
    results = evaluate(data_dir, output_path)
    print("Evaluation complete. Results written to", output_path)
    for cat, metrics in sorted(results.items()):
        print(f"  {cat}: {metrics}")
