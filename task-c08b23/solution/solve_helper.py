#!/usr/bin/env python3
"""
Corrected BESSPIN Scale Security Evaluation Engine

Fixes all 5 bugs from the buggy implementation:
1. DETECTED effective value = 3 (aliased to NONE), NORM_DIVISOR = 3
2. Error propagation uses min (most severe error)
3. Error/N/A CWEs excluded from category averages (not counted as 0)
4. Weight formula: 0.6*AV + 0.4*(BI+LDX)/2 (not swapped)
5. Floor division uses math.floor() (not round())
"""

import json
import csv
import os
import math
from collections import defaultdict


# ---------------------------------------------------------------------------
# SCORES enum (corrected)
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
    "DETECTED": 3,  # FIX 1: aliased to NONE (effective value 3, not 4)
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
}

NORM_DIVISOR = 3.0  # FIX 1: divisor is 3 (effective value of DETECTED/NONE)


def effective_value(score_name):
    return SCORE_VALUES[score_name]


def floor_score_name(value):
    floored = int(math.floor(value))  # FIX 5: use floor() not round()
    floored = max(-4, min(3, floored))  # FIX 1: max is 3, not 4
    return VALUE_TO_SCORE[floored]


def normalize(exact_value):
    return exact_value / NORM_DIVISOR


# ---------------------------------------------------------------------------
# Factor weight mapping
# ---------------------------------------------------------------------------

TI_MAP = {"critical": 1.0, "moderate": 0.6, "limited": 0.1}
AV_MAP = {"user": 1.0, "supervisor": 0.6, "machine": 0.4}
BI_MAP = {"high": 1.0, "low": 0.5}
LDX_MAP = {"high": 1.0, "low": 0.5}


def compute_category_weight(factors):
    ti = TI_MAP[factors["TI"]]
    av = AV_MAP[factors["AV"]]
    bi = BI_MAP[factors["ENV"]["BI"]]
    ldx = LDX_MAP[factors["ENV"]["LDX"]]
    return ti * (0.6 * av + 0.4 * (bi + ldx) / 2)  # FIX 4: correct coefficient order


# ---------------------------------------------------------------------------
# Parse data
# ---------------------------------------------------------------------------

def load_coefficients(path):
    with open(path) as f:
        data = json.load(f)
    result = {}
    for key, value in data.items():
        if key.startswith("_"):
            continue
        result[key] = {}
        for cat_key, cat_data in value.items():
            result[key][cat_key] = {
                "name": cat_data["name"],
                "cwes": set(cat_data["cwes"]),
                "weight": compute_category_weight(cat_data["factors"]),
            }
    return result


def load_test_results(test_results_dir):
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
# Aggregate multi-part CWE scores (corrected)
# ---------------------------------------------------------------------------

def aggregate_cwe_parts(parts):
    values = [effective_value(score_name) for _, score_name in parts]

    # FIX 2: use min (most severe/conservative) for error propagation
    min_val = min(values)
    if min_val < 0:
        min_score = None
        for _, score_name in parts:
            v = effective_value(score_name)
            if v == min_val:
                min_score = score_name
                break
        return (min_score, float(min_val), normalize(float(min_val)))

    exact = sum(values) / len(values)
    floor_name = floor_score_name(exact)
    norm = normalize(exact)

    if len(parts) == 1:
        original_name = parts[0][1]
        if original_name == "DETECTED":
            floor_name = "DETECTED"

    return (floor_name, exact, norm)


# ---------------------------------------------------------------------------
# Main computation (corrected)
# ---------------------------------------------------------------------------

def compute_report(coefficients, test_results):
    cwe_scores = {}
    for vul_class, cwe_parts in test_results.items():
        cwe_scores[vul_class] = {}
        for cwe_id, parts in cwe_parts.items():
            cwe_scores[vul_class][cwe_id] = aggregate_cwe_parts(parts)

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

            # FIX 3: exclude error CWEs from category average (don't count as 0)
            valid_norms = []
            cwe_details = {}
            for cwe_id, (floor_s, exact_v, norm_v) in cat_cwe_scores.items():
                cwe_details[cwe_id] = {
                    "floor_score": floor_s,
                    "exact_value": exact_v,
                    "normalized": norm_v,
                }
                if effective_value(floor_s) >= 0:
                    valid_norms.append(norm_v)

            if valid_norms:
                cat_norm_score = sum(valid_norms) / len(valid_norms)
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

    if scale_denominator > 0:
        report["besspin_scale"] = (scale_numerator / scale_denominator) * 100

    # Naive tallies
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


def compute_comparison(alpha_report, beta_report, coefficients):
    alpha_scale = alpha_report["besspin_scale"]
    beta_scale = beta_report["besspin_scale"]

    alpha_advantages = []
    beta_advantages = []
    max_impact = 0.0
    highest_impact_cat = None

    for vul_class in coefficients:
        for cat_key, cat_info in coefficients[vul_class].items():
            alpha_cat = alpha_report["vulnerability_classes"].get(vul_class, {}).get(cat_key)
            beta_cat = beta_report["vulnerability_classes"].get(vul_class, {}).get(cat_key)

            if not alpha_cat or not beta_cat:
                continue

            a_score = alpha_cat.get("normalized_score")
            b_score = beta_cat.get("normalized_score")

            if a_score is None and b_score is None:
                continue
            if a_score is None:
                a_score = 0.0
            if b_score is None:
                b_score = 0.0

            if a_score > b_score + 1e-9:
                alpha_advantages.append(cat_key)
            elif b_score > a_score + 1e-9:
                beta_advantages.append(cat_key)

            weight = cat_info["weight"]
            impact = weight * abs(b_score - a_score)
            if impact > max_impact:
                max_impact = impact
                highest_impact_cat = cat_key

    return {
        "alpha_besspin_scale": alpha_scale,
        "beta_besspin_scale": beta_scale,
        "more_secure_processor": "beta" if beta_scale > alpha_scale else "alpha",
        "alpha_category_advantages": sorted(alpha_advantages),
        "beta_category_advantages": sorted(beta_advantages),
        "highest_impact_category": highest_impact_cat,
    }


def main():
    coefficients = load_coefficients("/app/data/coefficients.json")

    # Alpha: from CSV
    alpha_results = load_test_results("/app/data/test_results")
    alpha_report = compute_report(coefficients, alpha_results)

    # Beta: from extracted CSV (solve.sh extracts from SQLite)
    beta_results = load_test_results("/tmp/beta_results")
    beta_report = compute_report(coefficients, beta_results)

    # Comparison
    comparison = compute_comparison(alpha_report, beta_report, coefficients)

    os.makedirs("/app/output", exist_ok=True)
    with open("/app/output/alpha_report.json", "w") as f:
        json.dump(alpha_report, f, indent=2)
    with open("/app/output/beta_report.json", "w") as f:
        json.dump(beta_report, f, indent=2)
    with open("/app/output/comparison.json", "w") as f:
        json.dump(comparison, f, indent=2)

    print(f"Alpha BESSPIN Scale: {alpha_report['besspin_scale']:.4f}%")
    print(f"Beta BESSPIN Scale:  {beta_report['besspin_scale']:.4f}%")
    print(f"More secure: {comparison['more_secure_processor']}")
    print(f"Highest impact category: {comparison['highest_impact_category']}")


if __name__ == "__main__":
    main()
