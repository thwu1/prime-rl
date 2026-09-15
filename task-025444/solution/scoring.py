#!/usr/bin/env python3
"""OWASP Benchmark Scoring Engine — implements the scoring algorithm
specified in BenchmarkScore.java using SQLite as the data store."""

import json
import os
import sqlite3

import yaml

DB_PATH = "/app/benchmark.db"
CONFIG_PATH = "/app/data/config.yaml"


def cwe_matches(actual_cwe, expected_cwe, tool_name, exceptions):
    """Check if a finding's CWE matches the expected CWE, considering exceptions.

    Implements the compare() logic from BenchmarkScore.java:
    - Direct CWE equality
    - CWE 564 -> 89 exception (all tools)
    - CWE 328 -> 327 exception (AppScan/Vera/CodeQL prefixed tools)
    """
    if actual_cwe == expected_cwe:
        return True
    for exc in exceptions:
        if exc["expected_cwe"] == expected_cwe and exc["accepted_cwe"] == actual_cwe:
            for prefix in exc["tool_prefixes"]:
                if prefix == "*" or tool_name.startswith(prefix):
                    return True
    return False


def main():
    # Load configuration
    with open(CONFIG_PATH) as f:
        config = yaml.safe_load(f)

    data_dir = os.path.dirname(CONFIG_PATH)
    exceptions = config.get("cwe_exceptions", [])

    conn = sqlite3.connect(DB_PATH)

    # --- Ingest expected results ---
    expected_path = os.path.join(data_dir, config["expected_results_file"])
    with open(expected_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split(",")
            conn.execute(
                "INSERT INTO expected_results (test_name, category, is_true_positive, cwe) "
                "VALUES (?, ?, ?, ?)",
                (parts[0].strip(), parts[1].strip(),
                 1 if parts[2].strip().lower() == "true" else 0,
                 int(parts[3].strip()))
            )

    # --- Ingest tool definitions and findings ---
    for tool in config["tools"]:
        conn.execute(
            "INSERT INTO tools (name, results_file, commercial) VALUES (?, ?, ?)",
            (tool["name"], tool["results_file"], 1 if tool["commercial"] else 0)
        )
        results_path = os.path.join(data_dir, tool["results_file"])
        with open(results_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                entry = json.loads(line)
                conn.execute(
                    "INSERT INTO findings (tool_name, test_name, cwe) VALUES (?, ?, ?)",
                    (tool["name"], entry["test_name"], entry["cwe"])
                )

    conn.commit()

    # --- Classify each (tool, test_case) pair ---
    tools = [row[0] for row in conn.execute("SELECT name FROM tools")]
    expected = conn.execute(
        "SELECT test_name, category, is_true_positive, cwe FROM expected_results"
    ).fetchall()

    for tool_name in tools:
        # Collect all findings for this tool, grouped by test case
        # Must preserve duplicates (a tool can report multiple CWEs per test)
        findings = {}
        for row in conn.execute(
            "SELECT test_name, cwe FROM findings WHERE tool_name = ?", (tool_name,)
        ):
            findings.setdefault(row[0], []).append(row[1])

        for test_name, category, is_tp, expected_cwe in expected:
            tool_findings = findings.get(test_name, [])

            # Check if any reported CWE matches the expected CWE (with exceptions)
            match_found = any(
                cwe_matches(f_cwe, expected_cwe, tool_name, exceptions)
                for f_cwe in tool_findings
            )

            if is_tp and match_found:
                classification = "TP"
            elif is_tp and not match_found:
                classification = "FN"
            elif not is_tp and match_found:
                classification = "FP"
            else:
                classification = "TN"

            conn.execute(
                "INSERT INTO classifications (tool_name, test_name, category, classification) "
                "VALUES (?, ?, ?, ?)",
                (tool_name, test_name, category, classification)
            )

    conn.commit()

    # --- Compute per-category metrics ---
    tools_output = []
    for tool_name in tools:
        commercial = conn.execute(
            "SELECT commercial FROM tools WHERE name = ?", (tool_name,)
        ).fetchone()[0]

        categories = conn.execute("""
            SELECT category,
                   SUM(CASE WHEN classification = 'TP' THEN 1 ELSE 0 END) as tp,
                   SUM(CASE WHEN classification = 'FN' THEN 1 ELSE 0 END) as fn,
                   SUM(CASE WHEN classification = 'FP' THEN 1 ELSE 0 END) as fp,
                   SUM(CASE WHEN classification = 'TN' THEN 1 ELSE 0 END) as tn
            FROM classifications
            WHERE tool_name = ?
            GROUP BY category
        """, (tool_name,)).fetchall()

        tpr_sum = 0.0
        fpr_sum = 0.0
        n_categories = len(categories)
        categories_out = {}

        for cat_name, tp, fn, fp, tn in categories:
            tpr = tp / (tp + fn) if (tp + fn) > 0 else 0.0
            fpr = fp / (fp + tn) if (fp + tn) > 0 else 0.0

            conn.execute(
                "INSERT INTO category_metrics "
                "(tool_name, category, tp, fn, fp, tn, tpr, fpr) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (tool_name, cat_name, tp, fn, fp, tn, tpr, fpr)
            )

            categories_out[cat_name] = {
                "tp": tp, "fn": fn, "fp": fp, "tn": tn,
                "tpr": tpr, "fpr": fpr,
            }

            # Accumulate for MACRO-averaging (mean of per-category rates)
            tpr_sum += tpr
            fpr_sum += fpr

        # MACRO-averaged overall metrics (NOT micro-averaged from total counts)
        macro_tpr = tpr_sum / n_categories if n_categories > 0 else 0.0
        macro_fpr = fpr_sum / n_categories if n_categories > 0 else 0.0
        youdens_j = macro_tpr - macro_fpr

        conn.execute(
            "INSERT INTO overall_metrics (tool_name, macro_tpr, macro_fpr, youdens_j) "
            "VALUES (?, ?, ?, ?)",
            (tool_name, macro_tpr, macro_fpr, youdens_j)
        )

        tools_output.append({
            "name": tool_name,
            "commercial": bool(commercial),
            "categories": categories_out,
            "overall": {
                "macro_tpr": macro_tpr,
                "macro_fpr": macro_fpr,
                "youdens_j": youdens_j,
            }
        })

    conn.commit()
    conn.close()

    # --- Export scorecard JSON ---
    # Rank tools by descending Youden's J
    ranked = sorted(tools_output, key=lambda t: t["overall"]["youdens_j"], reverse=True)
    ranking = [
        {"rank": i + 1, "name": t["name"], "youdens_j": t["overall"]["youdens_j"]}
        for i, t in enumerate(ranked)
    ]

    os.makedirs("/app/output", exist_ok=True)
    output = {"tools": tools_output, "ranking": ranking}
    with open("/app/output/scorecard.json", "w") as f:
        json.dump(output, f, indent=2)

    print("Scorecard exported to /app/output/scorecard.json")


if __name__ == "__main__":
    main()
