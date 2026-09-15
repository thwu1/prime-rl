#!/usr/bin/env python3

"""
Correct evaluation pipeline — reads ground truth directly from SQLite,
normalizes submissions, applies proper statistical methodology, and
produces both the evaluation report and methodology specification.
"""

import json
import math
import os
import sqlite3

import numpy as np
from scipy.stats import t as t_dist


def extract_ground_truth(db_path):
    """Extract ground truth from SQLite database with proper type coercion."""
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    capsules = c.execute(
        'SELECT capsule_id, field, language FROM capsules ORDER BY rowid'
    ).fetchall()

    result = []
    for cap_id, field, lang in capsules:
        runs = c.execute(
            'SELECT run_number FROM runs WHERE capsule_id=? ORDER BY run_number',
            (cap_id,)
        ).fetchall()

        results_list = []
        for (run_num,) in runs:
            run_data = {}

            # Numeric metrics
            for row in c.execute(
                'SELECT metric, value FROM numeric_results '
                'WHERE capsule_id=? AND run_number=?',
                (cap_id, run_num)
            ):
                run_data[row[0]] = row[1]

            # String metrics
            for row in c.execute(
                'SELECT metric, value FROM string_results '
                'WHERE capsule_id=? AND run_number=?',
                (cap_id, run_num)
            ):
                run_data[row[0]] = row[1]

            # List metrics — coerce elements to original types
            list_metrics = c.execute(
                'SELECT DISTINCT metric FROM list_results '
                'WHERE capsule_id=? AND run_number=?',
                (cap_id, run_num)
            ).fetchall()
            for (metric,) in list_metrics:
                elements = c.execute(
                    'SELECT element FROM list_results '
                    'WHERE capsule_id=? AND run_number=? AND metric=? '
                    'ORDER BY position',
                    (cap_id, run_num, metric)
                ).fetchall()
                typed_elements = []
                for (e,) in elements:
                    try:
                        typed_elements.append(int(e))
                    except ValueError:
                        try:
                            typed_elements.append(float(e))
                        except ValueError:
                            typed_elements.append(e)
                run_data[metric] = typed_elements

            results_list.append(run_data)

        result.append({
            'capsule_id': cap_id,
            'field': field,
            'language': lang,
            'results': results_list
        })

    conn.close()
    return result


def preprocess_submission(result_report):
    """Normalize submission values: strip %, coerce strings to numbers."""
    processed = dict(result_report)
    for key in list(processed.keys()):
        val = processed[key]
        if isinstance(val, str):
            cleaned = val.replace('%', '').strip()
            try:
                processed[key] = float(cleaned)
            except ValueError:
                processed[key] = val
    return processed


def evaluate_capsule(gt_capsule, reported_result):
    """Evaluate one capsule using 95% prediction intervals (t-distribution)."""
    gt_results = gt_capsule["results"]
    gt_first = gt_results[0]
    n = len(gt_results)

    t_val = t_dist.ppf(0.975, n - 1)

    correct_written = 0
    correct_vision = 0
    total_written = 0
    total_vision = 0

    reported = preprocess_submission(reported_result)

    for key, gt_value in gt_first.items():
        is_vision = "fig" in key
        if is_vision:
            total_vision += 1
        else:
            total_written += 1

        if key not in reported:
            continue

        reported_value = reported[key]

        if isinstance(gt_value, (int, float)):
            values = [r[key] for r in gt_results]
            mean = np.mean(values)
            std = np.std(values, ddof=1)
            width = t_val * std * math.sqrt(1 + 1 / n)
            lower = mean - width
            upper = mean + width

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
            if str(reported_value).lower() == str(gt_value).lower():
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
    """Compute agent-level summary statistics."""
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
    correct_tasks = sum(
        1 for r in capsule_results
        if r["correct_written_answers"] == r["total_written_questions"]
        and r["correct_vision_answers"] == r["total_vision_questions"]
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
    ground_truth = extract_ground_truth('/app/capsules.db')

    agent_evaluations = {}
    submissions_dir = '/app/submissions'

    for filename in sorted(os.listdir(submissions_dir)):
        if not filename.endswith('.json'):
            continue

        agent_name = filename.replace('.json', '')
        with open(os.path.join(submissions_dir, filename)) as f:
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

    with open('/app/evaluation_report.json', 'w') as f:
        json.dump(report, f, indent=4)

    # Write methodology specification
    methodology = {
        "distribution": "t",
        "degrees_of_freedom": "n-1",
        "variance_estimator": "bessel",
        "interval_type": "prediction",
        "interval_half_width_formula": "t * s * sqrt(1 + 1/n)",
        "string_comparison": "case_insensitive",
        "vision_classification_rule": "fig_substring",
        "submission_preprocessing": ["percent_strip", "string_to_number"]
    }
    with open('/app/methodology.json', 'w') as f:
        json.dump(methodology, f, indent=4)

    print("Evaluation report written to /app/evaluation_report.json")
    print("Methodology specification written to /app/methodology.json")


if __name__ == '__main__':
    main()
