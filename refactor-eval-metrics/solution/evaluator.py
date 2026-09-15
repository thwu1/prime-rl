#!/usr/bin/env python3

"""
Refactoring evaluation pipeline.

Processes SARIF 2.1.0 scan results, OpenGrep/Semgrep rule definitions,
and test execution results to compute composite refactoring quality metrics.
"""

import json
import os
from pathlib import Path

import numpy as np
import yaml


# -------------------------------------------------------------------
# Rule counting
# -------------------------------------------------------------------

def count_rules(yaml_path: str) -> int:
    """Count top-level rules in an OpenGrep/Semgrep rule YAML file."""
    with open(yaml_path) as f:
        data = yaml.safe_load(f)
    if data is None or not isinstance(data, dict):
        return 0
    rules = data.get("rules")
    if rules is None or not isinstance(rules, list):
        return 0
    return len(rules)


# -------------------------------------------------------------------
# SARIF parsing
# -------------------------------------------------------------------

def parse_sarif_matched_rules(sarif_path: str) -> set:
    """
    Parse a SARIF 2.1.0 file and return the set of distinct matched rule IDs.

    Handles:
    - Multiple runs within a single SARIF file
    - Results referencing rules by ruleId (string)
    - Results referencing rules by ruleIndex (integer)
    - Cross-run deduplication of matched rule IDs
    """
    with open(sarif_path) as f:
        sarif = json.load(f)

    matched_rule_ids = set()

    for run in sarif.get("runs", []):
        driver_rules = run.get("tool", {}).get("driver", {}).get("rules", [])

        for result in run.get("results", []):
            rule_id = result.get("ruleId")

            if rule_id is None:
                # Fall back to ruleIndex
                rule_index = result.get("ruleIndex")
                if rule_index is not None and 0 <= rule_index < len(driver_rules):
                    rule_id = driver_rules[rule_index].get("id")

            if rule_id is not None:
                matched_rule_ids.add(rule_id)

    return matched_rule_ids


# -------------------------------------------------------------------
# Metric computation
# -------------------------------------------------------------------

def compute_ifr(positive_matched: int, total_positive: int,
                negative_matched: int, total_negative: int):
    """
    Compute Instruction Following Rate metrics.

    Returns (positive_ifr, negative_ifr, combined_ifr) where any may be None.
    """
    positive_ifr = (positive_matched / total_positive) if total_positive > 0 else None

    negative_avoided = total_negative - negative_matched
    negative_ifr = (negative_avoided / total_negative) if total_negative > 0 else None

    total_rules = total_positive + total_negative
    if total_rules == 0:
        combined_ifr = None
    else:
        combined_ifr = (positive_matched + negative_avoided) / total_rules

    return positive_ifr, negative_ifr, combined_ifr


def parse_test_results(test_path: str):
    """
    Parse test results with multi-run flakiness handling.

    Returns (best_passed, worst_failed, total, error).
    """
    with open(test_path) as f:
        data = json.load(f)

    error = data.get("error")
    runs = data.get("runs", [])

    if not runs:
        return 0, 0, 0, error or "No test runs found"

    best_passed = max(r["passed"] for r in runs)
    worst_failed = min(r["failed"] for r in runs)
    total = runs[0]["total"]

    return best_passed, worst_failed, total, error


def check_test_validity(best_passed: int, total: int, error) -> bool:
    """Check if test results meet validity criteria."""
    if error is not None:
        return False
    if total < 10:
        return False
    if best_passed / total < 0.3:
        return False
    return True


# -------------------------------------------------------------------
# Bootstrap confidence intervals
# -------------------------------------------------------------------

def bootstrap_ci(values, n_bootstrap=10000, seed=42):
    """
    Compute bootstrap 95% confidence interval using percentile method.

    Returns [lower, upper] or None if fewer than 2 values.
    """
    if len(values) < 2:
        return None

    rng = np.random.RandomState(seed)
    n = len(values)
    arr = np.array(values, dtype=np.float64)
    bootstrap_means = np.empty(n_bootstrap)

    for i in range(n_bootstrap):
        sample = rng.choice(arr, size=n, replace=True)
        bootstrap_means[i] = np.mean(sample)

    lower = float(np.percentile(bootstrap_means, 2.5))
    upper = float(np.percentile(bootstrap_means, 97.5))
    return [lower, upper]


# -------------------------------------------------------------------
# Instance evaluation
# -------------------------------------------------------------------

def evaluate_instance(instance_dir: str) -> dict:
    """Evaluate a single benchmark instance."""
    # Count rules from YAML definitions
    total_positive = count_rules(os.path.join(instance_dir, "rules_positive.yml"))
    total_negative = count_rules(os.path.join(instance_dir, "rules_negative.yml"))

    # Parse SARIF to find matched rules
    positive_matched_ids = parse_sarif_matched_rules(
        os.path.join(instance_dir, "positive.sarif")
    )
    negative_matched_ids = parse_sarif_matched_rules(
        os.path.join(instance_dir, "negative.sarif")
    )

    positive_matched = len(positive_matched_ids)
    negative_matched = len(negative_matched_ids)

    # Compute IFR
    positive_ifr, negative_ifr, ifr = compute_ifr(
        positive_matched, total_positive, negative_matched, total_negative
    )

    # Parse and validate test results
    best_passed, worst_failed, total, error = parse_test_results(
        os.path.join(instance_dir, "test_results.json")
    )
    test_valid = check_test_validity(best_passed, total, error)
    pass_score = 1.0 if test_valid else 0.0

    # Compute alignment
    if ifr is None:
        alignment = None
    else:
        alignment = pass_score * ifr

    return {
        "positive_rules_total": total_positive,
        "positive_rules_matched": positive_matched,
        "negative_rules_total": total_negative,
        "negative_rules_matched": negative_matched,
        "positive_ifr": positive_ifr,
        "negative_ifr": negative_ifr,
        "ifr": ifr,
        "test_passed": best_passed,
        "test_failed": worst_failed,
        "test_total": total,
        "test_valid": test_valid,
        "pass_score": pass_score,
        "alignment": alignment,
    }


# -------------------------------------------------------------------
# Aggregation
# -------------------------------------------------------------------

def aggregate_metrics(instances: dict) -> dict:
    """Compute aggregate metrics across all instances."""
    # Collect per-metric values, excluding nulls where appropriate
    ifr_values = [v["ifr"] for v in instances.values() if v["ifr"] is not None]
    pos_ifr_values = [v["positive_ifr"] for v in instances.values() if v["positive_ifr"] is not None]
    neg_ifr_values = [v["negative_ifr"] for v in instances.values() if v["negative_ifr"] is not None]
    pass_values = [v["pass_score"] for v in instances.values()]
    alignment_values = [v["alignment"] for v in instances.values() if v["alignment"] is not None]

    def safe_mean(vals):
        return float(np.mean(vals)) if vals else None

    return {
        "mean_positive_ifr": safe_mean(pos_ifr_values),
        "mean_negative_ifr": safe_mean(neg_ifr_values),
        "mean_ifr": safe_mean(ifr_values),
        "mean_pass": safe_mean(pass_values),
        "mean_alignment": safe_mean(alignment_values),
        "ci95_alignment": bootstrap_ci(alignment_values) if len(alignment_values) >= 2 else None,
        "ci95_ifr": bootstrap_ci(ifr_values) if len(ifr_values) >= 2 else None,
        "ci95_pass": bootstrap_ci(pass_values) if len(pass_values) >= 2 else None,
        "num_instances": len(instances),
    }


# -------------------------------------------------------------------
# Main
# -------------------------------------------------------------------

def main():
    data_dir = Path("/app/data/instances")
    results_dir = Path("/app/results")
    results_dir.mkdir(parents=True, exist_ok=True)

    # Evaluate each instance
    instances = {}
    for instance_name in sorted(os.listdir(data_dir)):
        instance_path = data_dir / instance_name
        if instance_path.is_dir():
            instances[instance_name] = evaluate_instance(str(instance_path))

    # Aggregate
    agg = aggregate_metrics(instances)

    # Write output
    output = {
        "instances": instances,
        "aggregate": agg,
    }

    output_path = results_dir / "evaluation.json"
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)

    print(f"Evaluation complete. Results written to {output_path}")
    print(f"  Instances evaluated: {len(instances)}")
    print(f"  Mean IFR: {agg['mean_ifr']}")
    print(f"  Mean Alignment: {agg['mean_alignment']}")
    print(f"  Mean Pass: {agg['mean_pass']}")


if __name__ == "__main__":
    main()
