#!/usr/bin/env python3
"""
BESSPIN Scale Security Evaluation Engine

Computes the BESSPIN Scale security figure of merit from CWE test results
and coefficient weights per the scoring specification.
"""

import json
import csv
import os
import math
import sys
from collections import defaultdict


# ---------------------------------------------------------------------------
# SCORES enum
# ---------------------------------------------------------------------------

SCORE_VALUES = {
    "NOT_APPLICABLE": -4,
    "NOT_IMPLEMENTED": -3,
    "FAIL": -2,
    "CALL_ERR": -1,
    "HIGH": 0,
    "MED": 1,
    "LOW": 2,
    "NONE": 3,
    "DETECTED": 4,
}

VALUE_TO_SCORE = {
    -4: "NOT_APPLICABLE",
    -3: "NOT_IMPLEMENTED",
    -2: "FAIL",
    -1: "CALL_ERR",
    0: "HIGH",
    1: "MED",
    2: "LOW",
    3: "NONE",
    4: "DETECTED",
}

NORM_DIVISOR = 4.0


def effective_value(score_name):
    """Get the effective numeric value of a score name."""
    return SCORE_VALUES[score_name]


def floor_score_name(value):
    """Convert a numeric value to a score name via floor division."""
    floored = round(value)
    floored = max(-4, min(4, floored))
    return VALUE_TO_SCORE[floored]


def normalize(exact_value):
    """Normalize a score value to [0, 1] range."""
    return exact_value / NORM_DIVISOR


# ---------------------------------------------------------------------------
# Factor weight mapping
# ---------------------------------------------------------------------------

TI_MAP = {"critical": 1.0, "moderate": 0.6, "limited": 0.1}
AV_MAP = {"user": 1.0, "supervisor": 0.6, "machine": 0.4}
BI_MAP = {"high": 1.0, "low": 0.5}
LDX_MAP = {"high": 1.0, "low": 0.5}


def compute_category_weight(factors):
    """Compute category weight from CWSS-inspired factor labels."""
    ti = TI_MAP[factors["TI"]]
    av = AV_MAP[factors["AV"]]
    bi = BI_MAP[factors["ENV"]["BI"]]
    ldx = LDX_MAP[factors["ENV"]["LDX"]]
    return ti * (0.4 * av + 0.6 * (bi + ldx) / 2)


# ---------------------------------------------------------------------------
# Parse coefficients
# ---------------------------------------------------------------------------

def load_coefficients(path):
    """Load and parse the BESSPIN coefficients JSON."""
    with open(path) as f:
        data = json.load(f)

    result = {}
    for key, value in data.items():
        if key.startswith("_"):
            continue
        vul_class = key
        result[vul_class] = {}
        for cat_key, cat_data in value.items():
            result[vul_class][cat_key] = {
                "name": cat_data["name"],
                "cwes": set(cat_data["cwes"]),
                "weight": compute_category_weight(cat_data["factors"]),
            }
    return result


# ---------------------------------------------------------------------------
# Parse test results
# ---------------------------------------------------------------------------

def load_test_results(test_results_dir):
    """Load all CSV test result files.

    Returns: dict mapping vul_class -> {cwe_id -> [(part, score_name), ...]}
    """
    results = {}
    for filename in os.listdir(test_results_dir):
        if not filename.endswith(".csv"):
            continue
        vul_class = filename[:-4]
        results[vul_class] = defaultdict(list)

        with open(os.path.join(test_results_dir, filename)) as f:
            reader = csv.DictReader(f)
            for row in reader:
                cwe_id = row["cwe"].strip()
                part = int(row["part"].strip())
                score = row["score"].strip()
                results[vul_class][cwe_id].append((part, score))

    return results


# ---------------------------------------------------------------------------
# Aggregate multi-part CWE scores
# ---------------------------------------------------------------------------

def aggregate_cwe_parts(parts):
    """Aggregate multi-part scores for a single CWE.

    Args:
        parts: list of (part_num, score_name) tuples

    Returns:
        (floor_score_name, exact_value, normalized_value)
    """
    values = [effective_value(score_name) for _, score_name in parts]

    # Error propagation: if error parts exist, propagate
    max_val = max(values)
    if max_val < 0:
        err_score = None
        for _, score_name in parts:
            v = effective_value(score_name)
            if v == max_val:
                err_score = score_name
                break
        return (err_score, float(max_val), normalize(float(max_val)))

    # Weighted average with equal weights
    exact = sum(values) / len(values)
    floor_name = floor_score_name(exact)
    norm = normalize(exact)

    # Preserve DETECTED for single-part CWEs
    if len(parts) == 1:
        original_name = parts[0][1]
        if original_name == "DETECTED":
            floor_name = "DETECTED"

    return (floor_name, exact, norm)


# ---------------------------------------------------------------------------
# Main computation
# ---------------------------------------------------------------------------

def compute_report(coefficients, test_results):
    """Compute the full BESSPIN Scale report."""

    # Step 1: Compute per-CWE scores for each vulnerability class
    cwe_scores = {}
    for vul_class, cwe_parts in test_results.items():
        cwe_scores[vul_class] = {}
        for cwe_id, parts in cwe_parts.items():
            cwe_scores[vul_class][cwe_id] = aggregate_cwe_parts(parts)

    # Step 2: Build the report structure
    report = {
        "besspin_scale": 0.0,
        "naive_tally": {
            "binary_percentage": 0.0,
            "exact_percentage": 0.0,
            "total_cwes": 0,
            "binary_pass_count": 0,
        },
        "vulnerability_classes": {},
    }

    scale_numerator = 0.0
    scale_denominator = 0.0

    # Step 3: Process each vulnerability class and category
    for vul_class in coefficients:
        report["vulnerability_classes"][vul_class] = {}

        for cat_key, cat_info in coefficients[vul_class].items():
            cat_cwes = cat_info["cwes"]
            weight = cat_info["weight"]

            cat_cwe_scores = {}
            if vul_class in cwe_scores:
                for cwe_id in cat_cwes:
                    if cwe_id in cwe_scores[vul_class]:
                        cat_cwe_scores[cwe_id] = cwe_scores[vul_class][cwe_id]

            # Compute category score including all CWEs
            all_norms = []
            cwe_details = {}
            for cwe_id, (floor_s, exact_v, norm_v) in cat_cwe_scores.items():
                cwe_details[cwe_id] = {
                    "floor_score": floor_s,
                    "exact_value": exact_v,
                    "normalized": norm_v,
                }
                all_norms.append(max(0.0, norm_v))

            if all_norms:
                cat_norm_score = sum(all_norms) / len(all_norms)
            else:
                cat_norm_score = None

            report["vulnerability_classes"][vul_class][cat_key] = {
                "name": cat_info["name"],
                "weight": weight,
                "normalized_score": cat_norm_score,
                "cwe_scores": cwe_details,
            }

            if cat_norm_score is not None:
                scale_numerator += weight * cat_norm_score
                scale_denominator += weight

    # Step 4: Compute BESSPIN Scale
    if scale_denominator > 0:
        report["besspin_scale"] = (scale_numerator / scale_denominator) * 100
    else:
        report["besspin_scale"] = 0.0

    # Step 5: Compute naive tallies
    unique_cwes = {}
    for vul_class, cwes in cwe_scores.items():
        for cwe_id, score_tuple in cwes.items():
            unique_cwes[(vul_class, cwe_id)] = score_tuple

    total = 0
    binary_pass = 0
    exact_sum = 0.0

    for (vul_class, cwe_id), (floor_s, exact_v, norm_v) in unique_cwes.items():
        if floor_s in ("NOT_APPLICABLE", "NOT_IMPLEMENTED"):
            continue
        total += 1
        if floor_s in ("NONE", "DETECTED"):
            binary_pass += 1
        exact_sum += max(0.0, norm_v)

    report["naive_tally"]["total_cwes"] = total
    report["naive_tally"]["binary_pass_count"] = binary_pass
    if total > 0:
        report["naive_tally"]["binary_percentage"] = (binary_pass / total) * 100
        report["naive_tally"]["exact_percentage"] = (exact_sum / total) * 100

    return report


def main():
    coefficients = load_coefficients("/app/data/coefficients.json")

    results_dir = sys.argv[1] if len(sys.argv) > 1 else "/app/data/test_results"
    output_file = sys.argv[2] if len(sys.argv) > 2 else "/app/output/report.json"

    test_results = load_test_results(results_dir)
    report = compute_report(coefficients, test_results)

    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    with open(output_file, "w") as f:
        json.dump(report, f, indent=2)

    print(f"BESSPIN Scale: {report['besspin_scale']:.4f}%")
    tally = report["naive_tally"]
    print(f"Naive Binary:  {tally['binary_percentage']:.4f}%")
    print(f"Naive Exact:   {tally['exact_percentage']:.4f}%")
    print(f"Total CWEs:    {tally['total_cwes']}")
    print(f"Report written to {output_file}")


if __name__ == "__main__":
    main()
