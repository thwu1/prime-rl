#!/usr/bin/env python3
"""TTCN-3 Conformance Test Oracle -- Runner

Loads protocol conformance test suites from /app/oracle/ and runs
them through the template matching engine at /app/matcher.py.
Reports verdict discrepancies against expected results.

"""

import json
import os
import sys
import copy
import traceback

sys.path.insert(0, "/app")
from matcher import match, VerdictResolver

SUITES_DIR = "/app/oracle"


def run_match_test(tc, registry):
    """Run a template-match test case."""
    template = tc.get("template")
    if template is None:
        ref = tc["template_ref"]
        if ref not in registry:
            return "ERROR", f"template_ref '{ref}' not found in registry"
        template = registry[ref]

    message = tc["message"]
    expected = tc["expected_match"]

    try:
        result = match(template, message, registry)
        if result == expected:
            return "PASS", None
        else:
            return "FAIL", f"expected match={expected}, got match={result}"
    except Exception as e:
        return "ERROR", f"{type(e).__name__}: {e}"


def run_verdict_test(tc):
    """Run a verdict-resolution test case."""
    operations = tc["operations"]
    expected = tc["expected_verdict"]

    try:
        vr = VerdictResolver()
        result = vr.resolve_from_operations(operations)
        if result == expected:
            return "PASS", None
        else:
            return "FAIL", f"expected verdict='{expected}', got verdict='{result}'"
    except Exception as e:
        if expected == "error":
            return "PASS", None
        return "ERROR", f"{type(e).__name__}: {e}"


def run_suite(suite_path):
    """Run all test cases in a conformance suite."""
    with open(suite_path) as f:
        suite = json.load(f)

    suite_name = suite["suite_name"]
    registry = copy.deepcopy(suite.get("registry", {}))

    results = []
    for tc in suite["test_cases"]:
        tc_id = tc["id"]
        tc_type = tc.get("type", "match")

        if tc_type == "match":
            status, detail = run_match_test(tc, registry)
        elif tc_type == "verdict":
            status, detail = run_verdict_test(tc)
        else:
            status, detail = "ERROR", f"unknown test type: {tc_type}"

        results.append({
            "id": tc_id,
            "status": status,
            "detail": detail,
            "description": tc.get("description", "")
        })

    return suite_name, results


def main():
    print("=" * 72)
    print("TTCN-3 Conformance Test Oracle")
    print("=" * 72)

    total_pass = 0
    total_fail = 0
    total_error = 0

    suite_files = sorted(f for f in os.listdir(SUITES_DIR) if f.endswith(".json"))

    for fname in suite_files:
        path = os.path.join(SUITES_DIR, fname)
        try:
            suite_name, results = run_suite(path)
        except Exception as e:
            print(f"\n[SUITE LOAD ERROR] {fname}: {e}")
            traceback.print_exc()
            total_error += 1
            continue

        print(f"\n--- {suite_name} ---")
        for r in results:
            marker = {"PASS": "PASS", "FAIL": "FAIL", "ERROR": "ERR!"}[r["status"]]
            line = f"  [{marker}] {r['id']}: {r['description']}"
            if r["detail"]:
                line += f"\n         {r['detail']}"
            print(line)

            if r["status"] == "PASS":
                total_pass += 1
            elif r["status"] == "FAIL":
                total_fail += 1
            else:
                total_error += 1

    print(f"\n{'=' * 72}")
    print(f"Results: {total_pass + total_fail + total_error} total, "
          f"{total_pass} passed, {total_fail} failed, {total_error} errors")
    print(f"{'=' * 72}")

    return 0 if total_fail == 0 and total_error == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
