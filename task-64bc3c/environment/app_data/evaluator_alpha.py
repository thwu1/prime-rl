#!/usr/bin/env python3
"""
Reproducibility Evaluator — Implementation Alpha
Evaluates agent-reported results against ground truth from multiple stochastic runs.

Authors: Research Team A
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


def compute_prediction_intervals(gt_results):
    """Compute 95% prediction intervals for numeric keys."""
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
            # Apply small tolerance band for floating-point comparison stability
            intervals[key] = (mean_val - 0.001, mean_val + 0.001)
            continue

        # Two-sided 95% interval: use 0.975 quantile
        t_val = t.ppf(0.975, n - 1)
        margin = t_val * std_val * math.sqrt(1.0 + 1.0 / n)
        intervals[key] = (mean_val - margin, mean_val + margin)

    return intervals


def coerce_value(val):
    """Coerce reported value to numeric if possible."""
    if isinstance(val, (int, float)):
        return val
    if isinstance(val, str):
        cleaned = val.strip()
        if cleaned.endswith('%'):
            cleaned = cleaned[:-1]
        try:
            return float(cleaned)
        except ValueError:
            return val
    return val


def evaluate_capsule(gt_capsule, reported):
    """Evaluate a single capsule's reported results against ground truth."""
    gt_results = gt_capsule['results']
    first = gt_results[0]
    intervals = compute_prediction_intervals(gt_results)

    correct_written = 0
    correct_vision = 0
    total_written = 0
    total_vision = 0

    for key, gt_val in first.items():
        # Vision questions start with 'fig' prefix
        is_vision = key.startswith('fig')

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
            # Exact string match
            if str(rep_val) == gt_val:
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
        print("Usage: python evaluator_alpha.py <ground_truth.json> <agent_reports_dir> <output_dir>")
        sys.exit(1)

    gt_path = sys.argv[1]
    reports_dir = sys.argv[2]
    output_dir = sys.argv[3]
    os.makedirs(output_dir, exist_ok=True)

    gt_data = load_json(gt_path)

    # Compute and write prediction intervals
    all_intervals = {}
    for capsule in gt_data:
        cid = capsule['capsule_id']
        intervals = compute_prediction_intervals(capsule['results'])
        all_intervals[cid] = {k: [v[0], v[1]] for k, v in intervals.items()}

    with open(os.path.join(output_dir, 'prediction_intervals.json'), 'w') as f:
        json.dump(all_intervals, f, indent=2)

    # Evaluate each agent
    agents = {}
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

        # Compute aggregate scores
        correct_tasks = sum(
            1 for r in capsule_results
            if r['correct_written'] == r['total_written']
            and r['correct_vision'] == r['total_vision']
        )
        correct_written_tasks = sum(
            1 for r in capsule_results
            if r['total_written'] > 0
            and r['correct_written'] == r['total_written']
        )
        correct_vision_tasks = sum(
            1 for r in capsule_results
            if r['total_vision'] > 0
            and r['correct_vision'] == r['total_vision']
        )
        total_written_tasks = sum(
            1 for r in capsule_results if r['total_written'] > 0
        )
        total_vision_tasks = sum(
            1 for r in capsule_results if r['total_vision'] > 0
        )

        agents[agent_name] = {
            'capsule_results': capsule_results,
            'summary': {
                'correct_tasks': correct_tasks,
                'total_tasks': len(capsule_results),
                'correct_questions': sum(r['correct_written'] + r['correct_vision'] for r in capsule_results),
                'total_questions': sum(r['total_written'] + r['total_vision'] for r in capsule_results),
                'correct_written_tasks': correct_written_tasks,
                'total_written_tasks': total_written_tasks,
                'correct_vision_tasks': correct_vision_tasks,
                'total_vision_tasks': total_vision_tasks,
                'correct_written_questions': sum(r['correct_written'] for r in capsule_results),
                'total_written_questions': sum(r['total_written'] for r in capsule_results),
                'correct_vision_questions': sum(r['correct_vision'] for r in capsule_results),
                'total_vision_questions': sum(r['total_vision'] for r in capsule_results),
            }
        }

    with open(os.path.join(output_dir, 'evaluation_summary.json'), 'w') as f:
        json.dump({'agents': agents}, f, indent=2)

    print("Alpha evaluation complete.")


if __name__ == '__main__':
    main()
