#!/usr/bin/env python3
"""
Reproducibility Evaluation Pipeline
Evaluates agent-reported results against ground truth from multiple stochastic runs.

"""

import json
import math
import os
import sys
from scipy.stats import t
import numpy as np


def load_ground_truth(filepath):
    with open(filepath) as f:
        return json.load(f)


def load_agent_report(filepath):
    with open(filepath) as f:
        return json.load(f)


def compute_prediction_intervals(gt_results):
    """Compute 95% prediction intervals for numeric keys across multiple runs."""
    keys = list(gt_results[0].keys())
    numeric_keys = [k for k in keys if isinstance(gt_results[0][k], (int, float))]

    n = len(gt_results)
    intervals = {}

    for key in numeric_keys:
        values = [r[key] for r in gt_results]
        mean_val = float(np.mean(values))
        std_val = float(np.std(values, ddof=1))

        if std_val == 0.0:
            intervals[key] = (mean_val, mean_val)
            continue

        # Compute the critical t-value for 95% prediction interval
        t_val = t.ppf(0.95, n - 1)

        # Compute the prediction interval margin
        margin = t_val * std_val * math.sqrt(1.0 / n)

        intervals[key] = (mean_val - margin, mean_val + margin)

    return intervals


def coerce_value(val):
    """Try to coerce a reported value to a numeric type."""
    if isinstance(val, (int, float)):
        return val
    if isinstance(val, str):
        try:
            return float(val)
        except ValueError:
            return val
    return val


def classify_keys(keys, first_result):
    """Classify keys into numeric, string, list types and vision/written categories."""
    numeric_keys = []
    string_keys = []
    list_keys = []

    for key in keys:
        val = first_result[key]
        if isinstance(val, (int, float)):
            numeric_keys.append(key)
        elif isinstance(val, str):
            string_keys.append(key)
        elif isinstance(val, list):
            list_keys.append(key)

    written_numeric = [k for k in numeric_keys if not k.startswith('fig')]
    vision_numeric = [k for k in numeric_keys if k.startswith('fig')]
    written_string = [k for k in string_keys if not k.startswith('fig')]
    vision_string = [k for k in string_keys if k.startswith('fig')]
    written_list = [k for k in list_keys if not k.startswith('fig')]
    vision_list = [k for k in list_keys if k.startswith('fig')]

    return {
        'written': {'numeric': written_numeric, 'string': written_string, 'list': written_list},
        'vision': {'numeric': vision_numeric, 'string': vision_string, 'list': vision_list}
    }


def evaluate_capsule(gt_capsule, reported):
    """Evaluate a single capsule's reported results against ground truth."""
    gt_results = gt_capsule['results']
    first = gt_results[0]
    keys = list(first.keys())

    classification = classify_keys(keys, first)
    intervals = compute_prediction_intervals(gt_results)

    correct_written = 0
    correct_vision = 0
    total_written = (len(classification['written']['numeric'])
                     + len(classification['written']['string'])
                     + len(classification['written']['list']))
    total_vision = (len(classification['vision']['numeric'])
                    + len(classification['vision']['string'])
                    + len(classification['vision']['list']))

    for key in keys:
        if key not in reported:
            continue

        reported_val = coerce_value(reported[key])
        gt_val = first[key]
        is_vision = key.startswith('fig')

        if isinstance(gt_val, (int, float)):
            if isinstance(reported_val, (int, float)):
                lower, upper = intervals[key]
                if lower <= reported_val <= upper:
                    if is_vision:
                        correct_vision += 1
                    else:
                        correct_written += 1
        elif isinstance(gt_val, str):
            if str(reported_val) == gt_val:
                if is_vision:
                    correct_vision += 1
                else:
                    correct_written += 1
        elif isinstance(gt_val, list):
            if reported_val == gt_val:
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


def evaluate_agent(gt_data, agent_report):
    """Evaluate all capsules for an agent."""
    results = []
    for capsule_result in agent_report['capsule_results']:
        capsule_id = capsule_result['capsule_id']
        reported = capsule_result.get('result_report', {})

        gt_capsule = None
        for gt in gt_data:
            if gt['capsule_id'] == capsule_id:
                gt_capsule = gt
                break

        if gt_capsule is None:
            continue

        result = evaluate_capsule(gt_capsule, reported)
        results.append(result)

    return results


def main():
    """Main entry point.
    Usage: python evaluator.py <ground_truth.json> <agent_reports_dir> <output_dir>
    """
    if len(sys.argv) != 4:
        print("Usage: python evaluator.py <ground_truth.json> <agent_reports_dir> <output_dir>")
        sys.exit(1)

    gt_path = sys.argv[1]
    reports_dir = sys.argv[2]
    output_dir = sys.argv[3]

    os.makedirs(output_dir, exist_ok=True)

    gt_data = load_ground_truth(gt_path)

    all_results = {}
    for filename in sorted(os.listdir(reports_dir)):
        if not filename.endswith('.json'):
            continue
        agent_name = filename.replace('.json', '')
        report = load_agent_report(os.path.join(reports_dir, filename))
        all_results[agent_name] = evaluate_agent(gt_data, report)

    # TODO: Implement aggregate scoring per the specification
    # TODO: Implement prediction interval output per the specification
    with open(os.path.join(output_dir, 'evaluation_summary.json'), 'w') as f:
        json.dump(all_results, f, indent=2)


if __name__ == '__main__':
    main()
