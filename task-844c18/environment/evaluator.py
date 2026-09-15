#!/usr/bin/env python3
"""Reproducibility evaluator — compares agent submissions against ground truth
using statistical tolerance intervals for stochastic experimental results."""

import argparse
import json
import math
import os

import numpy as np
from scipy.stats import norm


def evaluate_capsule(gt_capsule, reported_result):
    """Evaluate reported results against ground truth for one capsule."""
    gt_results = gt_capsule["results"]
    gt_first = gt_results[0]
    n = len(gt_results)

    z = norm.ppf(0.975)

    correct_written = 0
    correct_vision = 0
    total_written = 0
    total_vision = 0

    for key, gt_value in gt_first.items():
        is_vision = key.startswith("fig_")
        if is_vision:
            total_vision += 1
        else:
            total_written += 1

        if key not in reported_result:
            continue

        reported_value = reported_result[key]

        if isinstance(gt_value, (int, float)):
            values = [r[key] for r in gt_results]
            mean = np.mean(values)
            std = np.std(values)
            margin = z * std / math.sqrt(n)
            lower = mean - margin
            upper = mean + margin

            try:
                val = float(reported_value)
                if lower <= val <= upper:
                    if is_vision:
                        correct_vision += 1
                    else:
                        correct_written += 1
            except (TypeError, ValueError):
                pass

        elif isinstance(gt_value, str):
            if str(reported_value) == str(gt_value):
                if is_vision:
                    correct_vision += 1
                else:
                    correct_written += 1

        elif isinstance(gt_value, list):
            if reported_value == gt_value:
                if is_vision:
                    correct_vision += 1
                else:
                    correct_written += 1

    return {
        "capsule_id": gt_capsule["capsule_id"],
        "correct_written_answers": correct_written,
        "correct_vision_answers": correct_vision,
        "total_written_questions": total_written,
        "total_vision_questions": total_vision,
    }


def compute_summary(capsule_results):
    """Aggregate capsule results into agent-level summary."""
    correct_tasks = sum(
        1 for r in capsule_results
        if r["correct_written_answers"] == r["total_written_questions"]
        and r["correct_vision_answers"] == r["total_vision_questions"]
    )
    correct_written_tasks = sum(
        1 for r in capsule_results
        if r["correct_written_answers"] == r["total_written_questions"]
        and r["total_written_questions"] > 0
    )
    correct_vision_tasks = sum(
        1 for r in capsule_results
        if r["correct_vision_answers"] == r["total_vision_questions"]
        and r["total_vision_questions"] > 0
    )

    total_tasks = len(capsule_results)
    total_written_tasks = sum(
        1 for r in capsule_results if r["total_written_questions"] > 0
    )
    total_vision_tasks = sum(
        1 for r in capsule_results if r["total_vision_questions"] > 0
    )

    cw = sum(r["correct_written_answers"] for r in capsule_results)
    cv = sum(r["correct_vision_answers"] for r in capsule_results)
    tw = sum(r["total_written_questions"] for r in capsule_results)
    tv = sum(r["total_vision_questions"] for r in capsule_results)

    return {
        "correct_tasks": correct_tasks,
        "total_tasks": total_tasks,
        "correct_questions": cw + cv,
        "total_questions": tw + tv,
        "correct_written_tasks": correct_written_tasks,
        "total_written_tasks": total_written_tasks,
        "correct_vision_tasks": correct_vision_tasks,
        "total_vision_tasks": total_vision_tasks,
        "correct_written_questions": cw,
        "total_written_questions": tw,
        "correct_vision_questions": cv,
        "total_vision_questions": tv,
    }


def main():
    parser = argparse.ArgumentParser(description="Evaluate agent submissions")
    parser.add_argument('--gt', required=True, help='Ground truth JSON file')
    parser.add_argument('--submissions', required=True, help='Submissions directory')
    parser.add_argument('--output', required=True, help='Output evaluation JSON')
    args = parser.parse_args()

    with open(args.gt) as f:
        ground_truth = json.load(f)

    agent_evaluations = {}

    for filename in sorted(os.listdir(args.submissions)):
        if not filename.endswith('.json'):
            continue

        agent_name = filename.replace('.json', '')
        with open(os.path.join(args.submissions, filename)) as f:
            submission = json.load(f)

        sub_by_id = {
            r["capsule_id"]: r["result_report"]
            for r in submission["capsule_results"]
        }

        capsule_results = []
        for gt_capsule in ground_truth:
            cid = gt_capsule["capsule_id"]
            reported = sub_by_id.get(cid, {})
            result = evaluate_capsule(gt_capsule, reported)
            capsule_results.append(result)

        agent_evaluations[agent_name] = {
            "capsule_results": capsule_results,
            "summary": compute_summary(capsule_results),
        }

    agents_by_tasks = sorted(
        agent_evaluations.keys(),
        key=lambda a: (-agent_evaluations[a]["summary"]["correct_tasks"], a),
    )
    agents_by_questions = sorted(
        agent_evaluations.keys(),
        key=lambda a: (-agent_evaluations[a]["summary"]["correct_questions"], a),
    )

    report = {
        "agent_evaluations": agent_evaluations,
        "rankings": {
            "by_correct_tasks": agents_by_tasks,
            "by_correct_questions": agents_by_questions,
        },
    }

    with open(args.output, 'w') as f:
        json.dump(report, f, indent=4)

    print(f"Evaluation written to {args.output}")


if __name__ == '__main__':
    main()
