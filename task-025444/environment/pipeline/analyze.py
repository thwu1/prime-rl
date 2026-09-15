#!/usr/bin/env python3
"""Analyze tool findings against expected results — CWE matching and classification."""

import sqlite3

import yaml

DB_PATH = "/app/benchmark.db"


def load_cwe_exceptions(config_path):
    """Load CWE exception rules from configuration."""
    with open(config_path) as f:
        config = yaml.safe_load(f)
    return config.get("cwe_exceptions", [])


def check_cwe_match(actual_cwe, expected_cwe, tool_name, exceptions):
    """Check if a finding's CWE matches the expected CWE, considering exceptions.

    CWE exceptions allow certain tools to report alternative CWE numbers
    that should be treated as matches. Each exception specifies tool_prefixes
    that indicate which tools receive the exception.
    """
    if actual_cwe == expected_cwe:
        return True

    for exc in exceptions:
        if exc["expected_cwe"] == expected_cwe and exc["accepted_cwe"] == actual_cwe:
            prefixes = exc["tool_prefixes"]
            for prefix in prefixes:
                if prefix == "*" or tool_name == prefix:
                    return True
    return False


def analyze(config_path):
    """Classify each (tool, test_case) pair as TP/FN/FP/TN."""
    exceptions = load_cwe_exceptions(config_path)

    conn = sqlite3.connect(DB_PATH)

    conn.execute("DROP TABLE IF EXISTS classifications")
    conn.execute("""
        CREATE TABLE classifications (
            tool_name TEXT,
            test_name TEXT,
            category TEXT,
            classification TEXT,
            PRIMARY KEY (tool_name, test_name)
        )
    """)

    tools = [row[0] for row in conn.execute("SELECT name FROM tools")]
    expected = conn.execute(
        "SELECT test_name, category, is_true_positive, cwe FROM expected_results"
    ).fetchall()

    for tool_name in tools:
        # Collect all findings for this tool, grouped by test case
        findings = {}
        for row in conn.execute(
            "SELECT test_name, cwe FROM findings WHERE tool_name = ?", (tool_name,)
        ):
            findings.setdefault(row[0], []).append(row[1])

        for test_name, category, is_tp, expected_cwe in expected:
            tool_findings = findings.get(test_name, [])

            match_found = False
            for finding_cwe in tool_findings:
                if check_cwe_match(finding_cwe, expected_cwe, tool_name, exceptions):
                    match_found = True
                    break

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
    conn.close()
    print("Analysis complete — classifications stored")


if __name__ == "__main__":
    analyze("/app/data/config.yaml")
