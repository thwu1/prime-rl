#!/usr/bin/env python3
"""
Fixed reproducibility scoring pipeline.
Corrects all bugs from the original evaluator:
1. Uses t-distribution instead of normal distribution for prediction intervals
2. Uses prediction interval formula (sqrt(1+1/n)) instead of confidence interval (sqrt(1/n))
3. Uses sample standard deviation (ddof=1) instead of population (ddof=0)
4. Uses alpha/(2n) instead of alpha/n in Grubbs critical value
5. Case-insensitive string comparison
6. Percentage string coercion before numeric comparison
7. Graceful handling of missing submission keys
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
    mean_val = float(np.mean(values))
    if n < 2:
        return mean_val, 0.0, mean_val, mean_val
    std_val = float(np.std(values, ddof=1))
    if std_val == 0.0:
        return mean_val, 0.0, mean_val, mean_val
    alpha = 1.0 - confidence
    t_val = float(t_dist.ppf(1.0 - alpha / 2.0, n - 1))
    margin = t_val * std_val * math.sqrt(1.0 + 1.0 / n)
    return mean_val, std_val, mean_val - margin, mean_val + margin


def grubbs_test(values, alpha=0.05):
    n = len(values)
    if n < 3:
        return False, None, None, None, None
    mean_val = float(np.mean(values))
    std_val = float(np.std(values, ddof=1))
    if std_val == 0.0:
        return False, None, None, None, None
    deviations = [abs(float(v) - mean_val) for v in values]
    max_idx = int(np.argmax(deviations))
    G = deviations[max_idx] / std_val
    t_crit = float(t_dist.ppf(1.0 - alpha / (2.0 * n), n - 2))
    G_crit = ((n - 1) / math.sqrt(n)) * math.sqrt(
        t_crit ** 2 / (n - 2 + t_crit ** 2)
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


def run_evaluation(gt_path, sub_path, out_path):
    with open(gt_path) as f:
        ground_truth = json.load(f)
    with open(sub_path) as f:
        submissions = json.load(f)

    output = {"experiments": {}, "evaluations": {}, "summary": {}}

    for exp in ground_truth:
        exp_id = exp["experiment_id"]
        runs = exp["runs"]
        ref = runs[0]
        analysis = {}
        for key in ref:
            val = ref[key]
            qtype = classify_type(val)
            entry = {
                "type": qtype, "n_runs": len(runs),
                "mean": None, "std": None,
                "prediction_interval": None,
                "grubbs_statistic": None, "grubbs_critical": None,
                "outlier_detected": False,
                "outlier_index": None, "outlier_value": None,
                "robust_interval": None,
            }
            if qtype == "numeric":
                vals = [float(r[key]) for r in runs]
                mu, sigma, lo, hi = compute_prediction_interval(vals)
                entry["mean"] = mu
                entry["std"] = sigma
                entry["prediction_interval"] = {"lower": lo, "upper": hi}
                is_outlier, o_idx, o_val, g_stat, g_crit = grubbs_test(vals)
                entry["grubbs_statistic"] = g_stat
                entry["grubbs_critical"] = g_crit
                entry["outlier_detected"] = is_outlier
                if is_outlier:
                    entry["outlier_index"] = o_idx
                    entry["outlier_value"] = o_val
                    clean = [v for i, v in enumerate(vals) if i != o_idx]
                    _, _, rlo, rhi = compute_prediction_interval(clean)
                    entry["robust_interval"] = {"lower": rlo, "upper": rhi}
                else:
                    entry["robust_interval"] = {"lower": lo, "upper": hi}
            analysis[key] = entry
        output["experiments"][exp_id] = analysis

    for sub in submissions:
        sid = sub["submission_id"]
        answers = sub["answers"]
        scores = {}
        n_total = 0
        n_std = 0
        n_rob = 0
        for exp in ground_truth:
            eid = exp["experiment_id"]
            ref = exp["runs"][0]
            sub_exp = answers.get(eid, {})
            exp_scores = {}
            for key in ref:
                n_total += 1
                gt_val = ref[key]
                qtype = classify_type(gt_val)
                submitted = sub_exp.get(key) if sub_exp else None
                std_ok = False
                rob_ok = False
                if submitted is not None:
                    coerced = coerce_submitted(submitted)
                    if qtype == "numeric":
                        try:
                            num = float(coerced)
                            pi = output["experiments"][eid][key]["prediction_interval"]
                            rpi = output["experiments"][eid][key]["robust_interval"]
                            if pi["lower"] <= num <= pi["upper"]:
                                std_ok = True
                            if rpi and rpi["lower"] <= num <= rpi["upper"]:
                                rob_ok = True
                        except (ValueError, TypeError):
                            pass
                    elif qtype == "string":
                        if str(coerced).lower() == str(gt_val).lower():
                            std_ok = True
                            rob_ok = True
                    elif qtype == "list":
                        if coerced == gt_val:
                            std_ok = True
                            rob_ok = True
                if std_ok:
                    n_std += 1
                if rob_ok:
                    n_rob += 1
                exp_scores[key] = {
                    "submitted": submitted,
                    "standard_correct": std_ok,
                    "robust_correct": rob_ok,
                }
            scores[eid] = exp_scores
        output["evaluations"][sid] = scores
        output["summary"][sid] = {
            "total_questions": n_total,
            "standard_correct": n_std,
            "robust_correct": n_rob,
            "standard_accuracy": round(n_std / n_total, 4) if n_total > 0 else 0.0,
            "robust_accuracy": round(n_rob / n_total, 4) if n_total > 0 else 0.0,
        }

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"Evaluation complete. Results: {out_path}")


if __name__ == "__main__":
    run_evaluation(
        "/app/data/experiments.json",
        "/app/data/submissions.json",
        "/app/output/results.json",
    )
