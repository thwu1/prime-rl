#!/usr/bin/env python3
"""3D Object Detection Evaluator.

Reads detection predictions and ground truth annotations from Apache
Feather files, evaluates using the configured protocol, and writes
per-category metrics to a JSON results file.
"""


import json
import numpy as np
import pyarrow.feather as pf
from pathlib import Path

from pipeline.config import load_config
from pipeline.preprocessing import filter_by_range, filter_zero_interior
from pipeline.assignment import greedy_assign, compute_center_distance
from pipeline.metrics import (compute_average_precision,
                               compute_orientation_error,
                               compute_scale_error,
                               compute_composite_score)


def load_data(data_dir):
    """Load detections and ground truth from Apache Feather files."""
    dt_table = pf.read_table(str(data_dir / "detections.feather"))
    gt_table = pf.read_table(str(data_dir / "ground_truth.feather"))
    return dt_table.to_pylist(), gt_table.to_pylist()


def evaluate(config, data_dir, output_path):
    """Run the full evaluation pipeline.

    For each object category:
      1. Filter by range and category.
      2. For each sweep, perform greedy assignment at multiple thresholds.
      3. Compute AP across thresholds.
      4. Compute true positive error metrics (ATE, ASE, AOE).
      5. Compute Composite Detection Score (CDS).
    """
    eval_cfg = config['evaluation']

    affinity_thresholds = eval_cfg['affinity_thresholds_m']
    tp_threshold = eval_cfg['tp_threshold_m']
    max_range = eval_cfg['max_range_m']
    max_dts = eval_cfg['max_detections_per_category']
    tp_norms = eval_cfg['tp_norms']
    num_recall = eval_cfg.get('num_recall_samples', 101)
    decimals = config['output']['decimal_places']

    dts_all, gts_all = load_data(data_dir)

    # Range filtering
    dts_all = filter_by_range(dts_all, max_range)
    gts_all = filter_by_range(gts_all, max_range)

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
                               reverse=True)[:max_dts]

            # Filter GTs with zero interior points
            sweep_gts = filter_zero_interior(sweep_gts)
            num_gts_total += len(sweep_gts)

            if not sweep_dts:
                continue

            # Assignment at each affinity threshold
            thresh_assignments = {}
            for threshold in affinity_thresholds:
                thresh_assignments[threshold] = greedy_assign(
                    sweep_dts, sweep_gts, threshold)

            # Build per-detection entries
            for dt_idx, dt in enumerate(sweep_dts):
                tp_flags = {t: dt_idx in thresh_assignments[t]
                            for t in affinity_thresholds}

                # Default TP errors (upper bounds for non-TPs)
                ate = tp_norms['ATE']
                ase = tp_norms['ASE']
                aoe = tp_norms['AOE']

                if tp_flags.get(tp_threshold, False):
                    gt_idx = thresh_assignments[tp_threshold][dt_idx]
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
        for threshold in affinity_thresholds:
            tps = np.array([e['tp_flags'][threshold]
                            for e in all_entries], dtype=bool)
            ap = compute_average_precision(tps, num_gts_total, num_recall)
            aps.append(ap)

        mean_ap = float(np.mean(aps))

        # Compute mean TP errors
        tp_entries = [e for e in all_entries
                      if e['tp_flags'].get(tp_threshold, False)]
        if tp_entries:
            mean_ate = float(np.mean([e['ate'] for e in tp_entries]))
            mean_ase = float(np.mean([e['ase'] for e in tp_entries]))
            mean_aoe = float(np.mean([e['aoe'] for e in tp_entries]))
        else:
            mean_ate = tp_norms['ATE']
            mean_ase = tp_norms['ASE']
            mean_aoe = tp_norms['AOE']

        cds = compute_composite_score(mean_ap, mean_ate, mean_ase, mean_aoe,
                                       tp_norms)

        results[category] = {
            'AP': round(mean_ap, decimals),
            'ATE': round(mean_ate, decimals),
            'ASE': round(mean_ase, decimals),
            'AOE': round(mean_aoe, decimals),
            'CDS': round(cds, decimals),
        }

    # Compute average metrics across categories
    avg = {}
    for metric in ['AP', 'ATE', 'ASE', 'AOE', 'CDS']:
        vals = [results[c][metric] for c in categories]
        avg[metric] = round(float(np.mean(vals)), decimals)
    results['AVERAGE_METRICS'] = avg

    with open(output_path, 'w') as f:
        json.dump(results, f, indent=2)

    return results


if __name__ == '__main__':
    config = load_config()
    data_dir = Path('/app/data')
    output_path = Path('/app/results.json')
    results = evaluate(config, data_dir, output_path)
    print("Evaluation complete. Results written to", output_path)
    for cat, metrics in sorted(results.items()):
        print(f"  {cat}: {metrics}")
