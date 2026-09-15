#!/usr/bin/env python3
"""
Correct unified evaluator — reconciles evaluator_alpha.py and evaluator_beta.R
against the CORE-Bench paper excerpt, plus sensitivity audit.


Reconciliation decisions (from paper_excerpt.md):
- t-distribution quantile: t.ppf(0.975, n-1) for two-sided 95%  [alpha correct]
- Prediction interval formula: sqrt(1 + 1/n)                     [alpha correct]
- Vision classification: 'fig' in key (substring, not prefix)    [beta correct]
- String comparison: case-insensitive                            [beta correct]
- Percentage handling: strip trailing '%' before float parse     [alpha correct]
- Zero variance: interval collapses to [mean, mean] exactly     [beta correct]
- Aggregate scoring: implemented per paper                       [alpha correct]
"""

import json
import math
import os
import sqlite3
import numpy as np
from scipy.stats import t as t_dist


def extract_ground_truth(db_path):
    """Extract ground truth data from SQLite database."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    capsules = conn.execute(
        "SELECT capsule_id, field, language, num_runs FROM capsules ORDER BY capsule_id"
    ).fetchall()

    gt_data = []
    for capsule in capsules:
        cid = capsule['capsule_id']
        n_runs = capsule['num_runs']

        # Get distinct metrics for this capsule
        metrics = conn.execute(
            "SELECT DISTINCT metric_name, metric_type FROM run_metrics "
            "WHERE capsule_id = ? ORDER BY metric_name",
            (cid,)
        ).fetchall()

        results = []
        for run_idx in range(n_runs):
            run_data = {}
            for metric in metrics:
                mname = metric['metric_name']
                mtype = metric['metric_type']
                row = conn.execute(
                    "SELECT numeric_value, text_value FROM run_metrics "
                    "WHERE capsule_id = ? AND run_index = ? AND metric_name = ?",
                    (cid, run_idx, mname)
                ).fetchone()
                if mtype == 'numeric':
                    run_data[mname] = row['numeric_value']
                elif mtype == 'string':
                    run_data[mname] = row['text_value']
                elif mtype == 'list':
                    run_data[mname] = json.loads(row['text_value'])
            results.append(run_data)

        gt_data.append({
            'capsule_id': cid,
            'field': capsule['field'],
            'language': capsule['language'],
            'results': results
        })

    conn.close()
    return gt_data


def main():
    db_path = "/app/ground_truth.db"
    reports_dir = "/app/agent_reports"
    output_dir = "/app/results"
    os.makedirs(output_dir, exist_ok=True)

    gt_data = extract_ground_truth(db_path)

    # --- Compute prediction intervals AND confidence intervals ---
    all_pi = {}
    all_ci = {}
    for capsule in gt_data:
        cid = capsule["capsule_id"]
        results = capsule["results"]
        first = results[0]
        n = len(results)
        pi = {}
        ci = {}

        for key, val in first.items():
            if not isinstance(val, (int, float)):
                continue
            values = [r[key] for r in results]
            mean = float(np.mean(values))
            std = float(np.std(values, ddof=1))
            if std == 0.0:
                pi[key] = [mean, mean]
                ci[key] = [mean, mean]
            else:
                t_val = float(t_dist.ppf(0.975, n - 1))
                pi_margin = t_val * std * math.sqrt(1.0 + 1.0 / n)
                ci_margin = t_val * std * math.sqrt(1.0 / n)
                pi[key] = [mean - pi_margin, mean + pi_margin]
                ci[key] = [mean - ci_margin, mean + ci_margin]

        all_pi[cid] = pi
        all_ci[cid] = ci

    # Write prediction intervals
    with open(os.path.join(output_dir, "prediction_intervals.json"), "w") as f:
        json.dump(all_pi, f, indent=2)

    # --- Evaluate each agent ---
    agents = {}
    all_fragile = []

    for filename in sorted(os.listdir(reports_dir)):
        if not filename.endswith(".json"):
            continue
        agent_name = filename.replace(".json", "")
        with open(os.path.join(reports_dir, filename)) as f:
            report = json.load(f)

        capsule_results = []

        for cr in report["capsule_results"]:
            cid = cr["capsule_id"]
            reported = cr.get("result_report", {})

            gt_capsule = None
            for g in gt_data:
                if g["capsule_id"] == cid:
                    gt_capsule = g
                    break
            if gt_capsule is None:
                continue

            gt_results = gt_capsule["results"]
            first = gt_results[0]

            correct_written = 0
            correct_vision = 0
            total_written = 0
            total_vision = 0

            for key, gt_val in first.items():
                # Vision classification: 'fig' anywhere in key (beta correct)
                is_vision = "fig" in key

                if is_vision:
                    total_vision += 1
                else:
                    total_written += 1

                if key not in reported:
                    continue

                # Value coercion with percentage handling (alpha correct)
                rep_val = reported[key]
                if isinstance(rep_val, str):
                    cleaned = rep_val.strip()
                    if cleaned.endswith("%"):
                        cleaned = cleaned[:-1]
                    try:
                        rep_val = float(cleaned)
                    except ValueError:
                        pass

                # Evaluate
                correct = False
                if isinstance(gt_val, (int, float)):
                    if isinstance(rep_val, (int, float)):
                        lower, upper = all_pi[cid][key]
                        if lower <= rep_val <= upper:
                            correct = True
                        # Track fragile results for sensitivity audit
                        ci_lower, ci_upper = all_ci[cid][key]
                        pi_correct = lower <= rep_val <= upper
                        ci_correct = ci_lower <= rep_val <= ci_upper
                        if pi_correct != ci_correct:
                            all_fragile.append({
                                "agent": agent_name,
                                "capsule_id": cid,
                                "key": key,
                                "reported_value": rep_val,
                                "pi_correct": pi_correct,
                                "ci_correct": ci_correct,
                            })
                elif isinstance(gt_val, str):
                    # Case-insensitive comparison (beta correct)
                    if str(rep_val).lower() == gt_val.lower():
                        correct = True
                elif isinstance(gt_val, list):
                    if rep_val == gt_val:
                        correct = True

                if correct:
                    if is_vision:
                        correct_vision += 1
                    else:
                        correct_written += 1

            capsule_results.append({
                "capsule_id": cid,
                "correct_written": correct_written,
                "correct_vision": correct_vision,
                "total_written": total_written,
                "total_vision": total_vision,
            })

        # Aggregate scoring (alpha correct, follows paper)
        correct_tasks = sum(
            1 for r in capsule_results
            if r["correct_written"] == r["total_written"]
            and r["correct_vision"] == r["total_vision"]
        )
        correct_written_tasks = sum(
            1 for r in capsule_results
            if r["total_written"] > 0
            and r["correct_written"] == r["total_written"]
        )
        correct_vision_tasks = sum(
            1 for r in capsule_results
            if r["total_vision"] > 0
            and r["correct_vision"] == r["total_vision"]
        )
        total_written_tasks = sum(
            1 for r in capsule_results if r["total_written"] > 0
        )
        total_vision_tasks = sum(
            1 for r in capsule_results if r["total_vision"] > 0
        )

        agents[agent_name] = {
            "capsule_results": capsule_results,
            "summary": {
                "correct_tasks": correct_tasks,
                "total_tasks": len(capsule_results),
                "correct_questions": sum(
                    r["correct_written"] + r["correct_vision"]
                    for r in capsule_results
                ),
                "total_questions": sum(
                    r["total_written"] + r["total_vision"]
                    for r in capsule_results
                ),
                "correct_written_tasks": correct_written_tasks,
                "total_written_tasks": total_written_tasks,
                "correct_vision_tasks": correct_vision_tasks,
                "total_vision_tasks": total_vision_tasks,
                "correct_written_questions": sum(
                    r["correct_written"] for r in capsule_results
                ),
                "total_written_questions": sum(
                    r["total_written"] for r in capsule_results
                ),
                "correct_vision_questions": sum(
                    r["correct_vision"] for r in capsule_results
                ),
                "total_vision_questions": sum(
                    r["total_vision"] for r in capsule_results
                ),
            },
        }

    # Write evaluation summary
    with open(os.path.join(output_dir, "evaluation_summary.json"), "w") as f:
        json.dump({"agents": agents}, f, indent=2)

    # --- Sensitivity Audit ---
    # Method comparison: PI and CI bounds for each numeric key
    method_comparison = {}
    for cid in all_pi:
        method_comparison[cid] = {}
        for key in all_pi[cid]:
            method_comparison[cid][key] = {
                "prediction_interval": all_pi[cid][key],
                "confidence_interval": all_ci[cid][key],
            }

    # Robustness scores
    robustness_scores = {}
    for agent_name in sorted(agents.keys()):
        total_pi_correct = agents[agent_name]["summary"]["correct_questions"]
        fragile_count = len([
            f for f in all_fragile if f["agent"] == agent_name
        ])
        if total_pi_correct == 0:
            robustness_scores[agent_name] = 1.0
        else:
            robustness_scores[agent_name] = (
                (total_pi_correct - fragile_count) / total_pi_correct
            )

    sensitivity_audit = {
        "method_comparison": method_comparison,
        "fragile_results": all_fragile,
        "robustness_scores": robustness_scores,
    }

    with open(os.path.join(output_dir, "sensitivity_audit.json"), "w") as f:
        json.dump(sensitivity_audit, f, indent=2)

    print("Evaluation complete. Output written to /app/results/")


if __name__ == "__main__":
    main()
