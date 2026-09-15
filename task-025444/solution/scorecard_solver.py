#!/usr/bin/env python3
"""
OWASP Benchmark Scorecard Engine — Solution

Implements the OWASP Benchmark scoring algorithm:
1. Parse expected results CSV, tool results JSONL, and config YAML
2. For each test case, compare tool findings against expected CWE
   (with CWE exception handling for tool-name-prefix-specific rules)
3. Classify outcomes as TP/FN/FP/TN per category
4. Compute per-category TPR and FPR
5. Macro-average across categories for overall metrics
6. Rank tools by Youden's J = macro_tpr - macro_fpr
"""
import csv
import json
import os
from collections import defaultdict

import yaml


def parse_expected_results(filepath):
    """Parse expected results CSV.

    Returns list of dicts with keys: test_name, category, is_true_positive, cwe.
    """
    results = []
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split(",")
            results.append({
                "test_name": parts[0].strip(),
                "category": parts[1].strip(),
                "is_true_positive": parts[2].strip().lower() == "true",
                "cwe": int(parts[3].strip()),
            })
    return results


def parse_tool_results(filepath):
    """Parse JSONL tool results.

    Returns dict mapping test_name -> list of CWE ints found by the tool.
    """
    findings = defaultdict(list)
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            findings[entry["test_name"]].append(entry["cwe"])
    return dict(findings)


def build_cwe_exceptions(config, tool_name):
    """Build applicable CWE exception map for a given tool.

    Returns dict: expected_cwe -> set of additionally accepted CWEs.
    """
    exceptions = {}
    for exc in config.get("cwe_exceptions", []):
        prefixes = exc["tool_prefixes"]
        applies = False
        for prefix in prefixes:
            if prefix == "*" or tool_name.startswith(prefix):
                applies = True
                break
        if applies:
            expected = exc["expected_cwe"]
            accepted = exc["accepted_cwe"]
            exceptions.setdefault(expected, set()).add(accepted)
    return exceptions


def cwe_matches(actual_cwe, expected_cwe, exceptions):
    """Check if actual CWE matches expected CWE, considering exceptions."""
    if actual_cwe == expected_cwe:
        return True
    if expected_cwe in exceptions and actual_cwe in exceptions[expected_cwe]:
        return True
    return False


def score_tool(expected_results, tool_findings, exceptions):
    """Score a tool's findings against expected results.

    Returns dict: category -> {tp, fn, fp, tn}.
    """
    counts = defaultdict(lambda: {"tp": 0, "fn": 0, "fp": 0, "tn": 0})

    for test in expected_results:
        test_name = test["test_name"]
        expected_cwe = test["cwe"]
        is_tp = test["is_true_positive"]
        category = test["category"]

        findings = tool_findings.get(test_name, [])

        # Check if any finding CWE matches the expected CWE
        match_found = False
        for finding_cwe in findings:
            if cwe_matches(finding_cwe, expected_cwe, exceptions):
                match_found = True
                break

        # Classify outcome
        if is_tp and match_found:
            counts[category]["tp"] += 1
        elif is_tp and not match_found:
            counts[category]["fn"] += 1
        elif not is_tp and match_found:
            counts[category]["fp"] += 1
        else:  # not is_tp and not match_found
            counts[category]["tn"] += 1

    return dict(counts)


def compute_metrics(category_counts):
    """Compute per-category rates and macro-averaged overall metrics.

    Returns (categories_dict, overall_dict).
    """
    categories = {}
    tpr_sum = 0.0
    fpr_sum = 0.0
    n_categories = len(category_counts)

    for cat_name in sorted(category_counts.keys()):
        c = category_counts[cat_name]
        tp, fn, fp, tn = c["tp"], c["fn"], c["fp"], c["tn"]

        tpr = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        fpr = fp / (fp + tn) if (fp + tn) > 0 else 0.0

        categories[cat_name] = {
            "tp": tp, "fn": fn, "fp": fp, "tn": tn,
            "tpr": tpr, "fpr": fpr,
        }

        tpr_sum += tpr
        fpr_sum += fpr

    macro_tpr = tpr_sum / n_categories if n_categories > 0 else 0.0
    macro_fpr = fpr_sum / n_categories if n_categories > 0 else 0.0

    overall = {
        "macro_tpr": macro_tpr,
        "macro_fpr": macro_fpr,
        "youdens_j": macro_tpr - macro_fpr,
    }

    return categories, overall


def main():
    data_dir = "/app/data"

    # Load configuration
    with open(os.path.join(data_dir, "config.yaml")) as f:
        config = yaml.safe_load(f)

    # Load expected results
    expected_path = os.path.join(data_dir, config["expected_results_file"])
    expected = parse_expected_results(expected_path)

    # Score each tool
    tools_output = []
    for tool_cfg in config["tools"]:
        tool_name = tool_cfg["name"]
        results_path = os.path.join(data_dir, tool_cfg["results_file"])

        findings = parse_tool_results(results_path)
        exceptions = build_cwe_exceptions(config, tool_name)

        counts = score_tool(expected, findings, exceptions)
        categories, overall = compute_metrics(counts)

        tools_output.append({
            "name": tool_name,
            "commercial": tool_cfg["commercial"],
            "categories": categories,
            "overall": overall,
        })

    # Rank by Youden's J (descending)
    ranked = sorted(tools_output,
                    key=lambda t: t["overall"]["youdens_j"],
                    reverse=True)
    ranking = [
        {"rank": i + 1, "name": t["name"], "youdens_j": t["overall"]["youdens_j"]}
        for i, t in enumerate(ranked)
    ]

    # Write output
    os.makedirs("/app/output", exist_ok=True)
    output = {"tools": tools_output, "ranking": ranking}
    with open("/app/output/scorecard.json", "w") as f:
        json.dump(output, f, indent=2)

    print("Scorecard written to /app/output/scorecard.json")


if __name__ == "__main__":
    main()
