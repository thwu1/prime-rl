#!/usr/bin/env python3
"""
Reproducibility Evaluator — Implementation Beta
Alternative evaluation of agent results against stochastic ground truth.

Authors: Research Team B
"""

import json
import math
import os
import sys
import numpy as np
from scipy.stats import t


def load_json(filepath):
    with open(filepath) as f:
        return json.load(f)


def compute_intervals(gt_results):
    """Compute 95% intervals for numeric keys across multiple runs."""
    first = gt_results[0]
    n = len(gt_results)
    intervals = {}

    for key, val in first.items():
        if not isinstance(val, (int, float)):
            continue
        values = [r[key] for r in gt_results]
        mean_val = float(np.mean(values))
        std_val = float(np.std(values, ddof=1))

        if std_val == 0.0:
            intervals[key] = (mean_val, mean_val)
            continue

        # 95th percentile of t-distribution for 95% interval
        t_val = t.ppf(0.95, n - 1)
        margin = t_val * std_val * math.sqrt(1.0 / n)
        intervals[key] = (mean_val - margin, mean_val + margin)

    return intervals


def coerce_value(val):
    """Coerce value to numeric type if possible."""
    if isinstance(val, (int, float)):
        return val
    if isinstance(val, str):
        try:
            return float(val.strip())
        except ValueError:
            return val
    return val


def evaluate_capsule(gt_capsule, reported):
    """Evaluate a single capsule result."""
    gt_results = gt_capsule['results']
    first = gt_results[0]
    intervals = compute_intervals(gt_results)

    correct_written = 0
    correct_vision = 0
    total_written = 0
    total_vision = 0

    for key, gt_val in first.items():
        # Vision question if 'fig' substring appears anywhere in the key
        is_vision = 'fig' in key

        if is_vision:
            total_vision += 1
        else:
            total_written += 1

        if key not in reported:
            continue

        rep_val = coerce_value(reported[key])

        if isinstance(gt_val, (int, float)):
            if isinstance(rep_val, (int, float)):
                lower, upper = intervals[key]
                if lower <= rep_val <= upper:
                    if is_vision:
                        correct_vision += 1
                    else:
                        correct_written += 1
        elif isinstance(gt_val, str):
            # Case-insensitive comparison
            if str(rep_val).lower() == gt_val.lower():
                if is_vision:
                    correct_vision += 1
                else:
                    correct_written += 1
        elif isinstance(gt_val, list):
            if rep_val == gt_val:
                if is_vision:
                    correct_vision += 1
                else:
                    correct_written += 1

    return {
        'capsule_id': gt_capsule['capsule_id'],
        'correct_written': correct_written,
        'correct_vision': correct_vision,
        'total_written': total_written,
        'total_vision': total_vision
    }


def main():
    if len(sys.argv) != 4:
        print("Usage: python evaluator_beta.py <ground_truth.json> <agent_reports_dir> <output_dir>")
        sys.exit(1)

    gt_path = sys.argv[1]
    reports_dir = sys.argv[2]
    output_dir = sys.argv[3]
    os.makedirs(output_dir, exist_ok=True)

    gt_data = load_json(gt_path)

    # Evaluate agents
    all_results = {}
    for filename in sorted(os.listdir(reports_dir)):
        if not filename.endswith('.json'):
            continue
        agent_name = filename.replace('.json', '')
        report = load_json(os.path.join(reports_dir, filename))

        capsule_results = []
        for cr in report['capsule_results']:
            gt_capsule = None
            for g in gt_data:
                if g['capsule_id'] == cr['capsule_id']:
                    gt_capsule = g
                    break
            if gt_capsule is None:
                continue
            result = evaluate_capsule(gt_capsule, cr.get('result_report', {}))
            capsule_results.append(result)

        all_results[agent_name] = capsule_results

    # TODO: Implement aggregate scoring per the paper specification
    # TODO: Implement prediction interval output file
    with open(os.path.join(output_dir, 'evaluation_summary.json'), 'w') as f:
        json.dump(all_results, f, indent=2)

    print("Beta evaluation complete.")


if __name__ == '__main__':
    main()
