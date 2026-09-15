#!/usr/bin/env python3

"""
Refactoring evaluation pipeline.

Processes SARIF 2.1.0 scan results, OpenGrep/Semgrep rule definitions,
and test execution results to compute composite refactoring quality metrics.

Produces:
  - /app/pipeline/extract_rules.jq  (jq filter for SARIF rule extraction)
  - /app/results/evaluation.db      (SQLite database with instance_metrics)
  - /app/results/evaluation.json    (JSON report with per-instance and aggregate metrics)
"""

import json
import os
import sqlite3
import subprocess
from pathlib import Path

import numpy as np
import yaml


DATA_DIR = Path("/app/data/instances")
RESULTS_DIR = Path("/app/results")
DB_PATH = RESULTS_DIR / "evaluation.db"
JSON_PATH = RESULTS_DIR / "evaluation.json"
JQ_FILTER = Path("/app/pipeline/extract_rules.jq")


def extract_matched_rules(sarif_path):
    """Use jq filter to extract matched rule IDs from a SARIF file."""
    result = subprocess.run(
        ['jq', '-r', '-f', str(JQ_FILTER), str(sarif_path)],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(f"jq failed on {sarif_path}: {result.stderr}")
    lines = [l.strip() for l in result.stdout.strip().split('\n') if l.strip()]
    return set(lines)


def count_rules(yaml_path):
    """Count top-level rules in an OpenGrep/Semgrep rule YAML file."""
    with open(yaml_path) as f:
        data = yaml.safe_load(f)
    if data is None or not isinstance(data, dict):
        return 0
    rules = data.get("rules")
    if rules is None or not isinstance(rules, list):
        return 0
    return len(rules)


def get_rule_ids(yaml_path):
    """Get the set of rule IDs defined in a YAML file."""
    with open(yaml_path) as f:
        data = yaml.safe_load(f)
    if data is None or not isinstance(data, dict):
        return set()
    rules = data.get("rules")
    if rules is None or not isinstance(rules, list):
        return set()
    return {r["id"] for r in rules if isinstance(r, dict) and "id" in r}


def parse_test_results(test_path):
    """Parse test results with multi-run flakiness handling."""
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


def compute_ifr(pos_matched, pos_total, neg_matched, neg_total):
    """Compute IFR metrics following the reference implementation."""
    pos_ifr = (pos_matched / pos_total) if pos_total > 0 else None
    neg_avoided = neg_total - neg_matched
    neg_ifr = (neg_avoided / neg_total) if neg_total > 0 else None
    total_rules = pos_total + neg_total
    if total_rules == 0:
        ifr = None
    else:
        ifr = (pos_matched + neg_avoided) / total_rules
    return pos_ifr, neg_ifr, ifr


def bootstrap_ci(values, n_bootstrap=10000, seed=42):
    """Compute bootstrap 95% CI using percentile method."""
    if len(values) < 2:
        return None
    rng = np.random.RandomState(seed)
    n = len(values)
    arr = np.array(values, dtype=np.float64)
    means = np.empty(n_bootstrap)
    for i in range(n_bootstrap):
        sample = rng.choice(arr, size=n, replace=True)
        means[i] = np.mean(sample)
    lower = float(np.percentile(means, 2.5))
    upper = float(np.percentile(means, 97.5))
    return [lower, upper]


def main():
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    # Initialize SQLite database
    if DB_PATH.exists():
        DB_PATH.unlink()
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("""
        CREATE TABLE instance_metrics (
            instance_name TEXT PRIMARY KEY,
            positive_rules_total INTEGER,
            positive_rules_matched INTEGER,
            negative_rules_total INTEGER,
            negative_rules_matched INTEGER,
            positive_ifr REAL,
            negative_ifr REAL,
            ifr REAL,
            test_passed INTEGER,
            test_failed INTEGER,
            test_total INTEGER,
            test_valid INTEGER,
            pass_score REAL,
            alignment REAL,
            phantom_positive_count INTEGER,
            phantom_negative_count INTEGER
        )
    """)

    instances = {}
    total_phantoms = 0

    for instance_name in sorted(os.listdir(DATA_DIR)):
        instance_dir = DATA_DIR / instance_name
        if not instance_dir.is_dir():
            continue

        # Count rules from YAML
        pos_total = count_rules(instance_dir / "rules_positive.yml")
        neg_total = count_rules(instance_dir / "rules_negative.yml")

        # Get defined rule IDs for phantom detection
        pos_defined_ids = get_rule_ids(instance_dir / "rules_positive.yml")
        neg_defined_ids = get_rule_ids(instance_dir / "rules_negative.yml")

        # Extract matched rules using jq
        pos_sarif_ids = extract_matched_rules(instance_dir / "positive.sarif")
        neg_sarif_ids = extract_matched_rules(instance_dir / "negative.sarif")

        # Detect phantom rules (SARIF references rules not in YAML)
        pos_phantoms = pos_sarif_ids - pos_defined_ids
        neg_phantoms = neg_sarif_ids - neg_defined_ids
        phantom_pos_count = len(pos_phantoms)
        phantom_neg_count = len(neg_phantoms)
        total_phantoms += phantom_pos_count + phantom_neg_count

        # Real matches = SARIF matches that are in YAML
        pos_matched = len(pos_sarif_ids & pos_defined_ids)
        neg_matched = len(neg_sarif_ids & neg_defined_ids)

        # Compute IFR
        pos_ifr, neg_ifr, ifr = compute_ifr(pos_matched, pos_total, neg_matched, neg_total)

        # Parse and validate test results
        best_passed, worst_failed, total, error = parse_test_results(
            instance_dir / "test_results.json"
        )

        # Test validity (from reference: is_valid check)
        if error is not None or total < 10:
            test_valid = False
        else:
            test_valid = (best_passed / total) >= 0.3

        pass_score = 1.0 if test_valid else 0.0

        # Alignment
        if ifr is None:
            alignment = None
        else:
            alignment = pass_score * ifr

        # Insert into SQLite
        conn.execute(
            "INSERT INTO instance_metrics VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (instance_name, pos_total, pos_matched, neg_total, neg_matched,
             pos_ifr, neg_ifr, ifr,
             best_passed, worst_failed, total,
             1 if test_valid else 0, pass_score, alignment,
             phantom_pos_count, phantom_neg_count)
        )

        # Build JSON entry
        instances[instance_name] = {
            "positive_rules_total": pos_total,
            "positive_rules_matched": pos_matched,
            "negative_rules_total": neg_total,
            "negative_rules_matched": neg_matched,
            "positive_ifr": pos_ifr,
            "negative_ifr": neg_ifr,
            "ifr": ifr,
            "test_passed": best_passed,
            "test_failed": worst_failed,
            "test_total": total,
            "test_valid": test_valid,
            "pass_score": pass_score,
            "alignment": alignment,
            "phantom_positive_count": phantom_pos_count,
            "phantom_negative_count": phantom_neg_count,
        }

    conn.commit()
    conn.close()

    # Compute aggregates
    ifr_vals = [v["ifr"] for v in instances.values() if v["ifr"] is not None]
    pos_ifr_vals = [v["positive_ifr"] for v in instances.values() if v["positive_ifr"] is not None]
    neg_ifr_vals = [v["negative_ifr"] for v in instances.values() if v["negative_ifr"] is not None]
    pass_vals = [v["pass_score"] for v in instances.values()]
    align_vals = [v["alignment"] for v in instances.values() if v["alignment"] is not None]

    def safe_mean(vals):
        return float(np.mean(vals)) if vals else None

    agg = {
        "mean_positive_ifr": safe_mean(pos_ifr_vals),
        "mean_negative_ifr": safe_mean(neg_ifr_vals),
        "mean_ifr": safe_mean(ifr_vals),
        "mean_pass": safe_mean(pass_vals),
        "mean_alignment": safe_mean(align_vals),
        "ci95_alignment": bootstrap_ci(align_vals),
        "ci95_ifr": bootstrap_ci(ifr_vals),
        "ci95_pass": bootstrap_ci(pass_vals),
        "num_instances": len(instances),
        "total_phantom_rules": total_phantoms,
    }

    output = {"instances": instances, "aggregate": agg}

    with open(JSON_PATH, "w") as f:
        json.dump(output, f, indent=2)

    print(f"Pipeline complete. Results at {JSON_PATH} and {DB_PATH}")
    print(f"  Instances: {len(instances)}")
    print(f"  Mean IFR: {agg['mean_ifr']}")
    print(f"  Mean Alignment: {agg['mean_alignment']}")
    print(f"  Total Phantom Rules: {total_phantoms}")


if __name__ == "__main__":
    main()
