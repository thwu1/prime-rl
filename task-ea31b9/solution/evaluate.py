#!/usr/bin/env python3
"""
Computational Reproducibility Evaluator
Implements prediction intervals, Grubbs' test, and submission evaluation
per /app/SPECIFICATION.md
"""
import json
import math
import os
import numpy as np
from scipy.stats import t as t_dist


def classify_type(value):
    if isinstance(value, bool):
        return "string"
    if isinstance(value, (int, float)):
        return "numeric"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "list"
    return "unknown"


def compute_prediction_interval(values, confidence=0.95):
    n = len(values)
    mean = float(np.mean(values))
    if n < 2:
        return mean, 0.0, mean, mean
    std = float(np.std(values, ddof=1))
    if std == 0.0:
        return mean, 0.0, mean, mean
    alpha = 1.0 - confidence
    t_val = float(t_dist.ppf(1.0 - alpha / 2.0, n - 1))
    margin = t_val * std * math.sqrt(1.0 + 1.0 / n)
    return mean, std, mean - margin, mean + margin


def grubbs_test(values, alpha=0.05):
    n = len(values)
    if n < 3:
        return False, None, None, None, None
    mean = float(np.mean(values))
    std = float(np.std(values, ddof=1))
    if std == 0.0:
        return False, None, None, None, None

    deviations = [abs(float(v) - mean) for v in values]
    max_idx = int(np.argmax(deviations))
    G = deviations[max_idx] / std

    t_c = float(t_dist.ppf(1.0 - alpha / (2.0 * n), n - 2))
    G_crit = ((n - 1) / math.sqrt(n)) * math.sqrt(
        t_c ** 2 / (n - 2 + t_c ** 2)
    )

    if G > G_crit:
        return True, max_idx, float(values[max_idx]), float(G), float(G_crit)
    return False, None, None, float(G), float(G_crit)


def coerce_submitted(value):
    if isinstance(value, str):
        cleaned = value.replace("%", "")
        try:
            return float(cleaned)
        except (ValueError, TypeError):
            return value
    return value


def main():
    with open("/app/data/ground_truth.json") as f:
        ground_truth = json.load(f)
    with open("/app/data/submissions.json") as f:
        submissions = json.load(f)

    result = {"experiments": {}, "evaluations": {}, "summary": {}}

    # ---- Process experiments ----
    for exp in ground_truth:
        exp_id = exp["experiment_id"]
        runs = exp["runs"]
        first_run = runs[0]
        exp_data = {}

        for key in first_run:
            val = first_run[key]
            qtype = classify_type(val)

            entry = {
                "type": qtype,
                "mean": None,
                "std": None,
                "standard_pi": None,
                "grubbs_statistic": None,
                "grubbs_critical_value": None,
                "outlier_detected": False,
                "outlier_index": None,
                "outlier_value": None,
                "robust_pi": None,
            }

            if qtype == "numeric":
                values = [float(run[key]) for run in runs]
                mean, std, pi_lo, pi_hi = compute_prediction_interval(values)
                entry["mean"] = mean
                entry["std"] = std
                entry["standard_pi"] = {"lower": pi_lo, "upper": pi_hi}

                detected, idx, oval, G, G_crit = grubbs_test(values)
                entry["grubbs_statistic"] = G
                entry["grubbs_critical_value"] = G_crit
                entry["outlier_detected"] = detected

                if detected:
                    entry["outlier_index"] = idx
                    entry["outlier_value"] = oval
                    robust_vals = [v for i, v in enumerate(values) if i != idx]
                    _, _, rpi_lo, rpi_hi = compute_prediction_interval(robust_vals)
                    entry["robust_pi"] = {"lower": rpi_lo, "upper": rpi_hi}
                else:
                    entry["robust_pi"] = {"lower": pi_lo, "upper": pi_hi}

            exp_data[key] = entry

        result["experiments"][exp_id] = exp_data

    # ---- Evaluate submissions ----
    for sub in submissions:
        sub_id = sub["submission_id"]
        answers = sub["answers"]
        eval_data = {}
        total_q = 0
        std_correct = 0
        rob_correct = 0

        for exp in ground_truth:
            exp_id = exp["experiment_id"]
            first_run = exp["runs"][0]
            sub_ans = answers.get(exp_id, {})
            eval_exp = {}

            for key in first_run:
                total_q += 1
                gt_val = first_run[key]
                qtype = classify_type(gt_val)

                submitted = sub_ans.get(key) if sub_ans else None
                s_ok = False
                r_ok = False

                if submitted is not None:
                    coerced = coerce_submitted(submitted)

                    if qtype == "numeric":
                        try:
                            num_val = float(coerced)
                            pi = result["experiments"][exp_id][key]["standard_pi"]
                            rpi = result["experiments"][exp_id][key]["robust_pi"]
                            if pi["lower"] <= num_val <= pi["upper"]:
                                s_ok = True
                            if rpi and rpi["lower"] <= num_val <= rpi["upper"]:
                                r_ok = True
                        except (ValueError, TypeError):
                            pass
                    elif qtype == "string":
                        if str(coerced).lower() == str(gt_val).lower():
                            s_ok = True
                            r_ok = True
                    elif qtype == "list":
                        if coerced == gt_val:
                            s_ok = True
                            r_ok = True

                if s_ok:
                    std_correct += 1
                if r_ok:
                    rob_correct += 1

                eval_exp[key] = {
                    "submitted": submitted,
                    "standard_correct": s_ok,
                    "robust_correct": r_ok,
                }

            eval_data[exp_id] = eval_exp

        result["evaluations"][sub_id] = eval_data
        result["summary"][sub_id] = {
            "total_questions": total_q,
            "standard_correct": std_correct,
            "robust_correct": rob_correct,
            "standard_accuracy": std_correct / total_q if total_q > 0 else 0.0,
            "robust_accuracy": rob_correct / total_q if total_q > 0 else 0.0,
        }

    os.makedirs("/app/output", exist_ok=True)
    with open("/app/output/evaluation.json", "w") as f:
        json.dump(result, f, indent=2)

    print("Evaluation complete. Output written to /app/output/evaluation.json")


if __name__ == "__main__":
    main()
