#!/usr/bin/env python3
"""TTCN-3 Conformance Pipeline Validator

Validates the structural integrity of test suite definitions, PICS profiles,
oracle test suites, and conformance reports.

Usage:
  python3 ttcn3_validate.py --suites DIR --oracle DIR --pics DIR
  python3 ttcn3_validate.py --reports DIR

"""

import argparse
import json
import os
import sys

VALID_VERDICTS = {"none", "pass", "inconc", "fail", "error"}


def validate_suites(suites_dir):
    """Validate engine test suite JSON files."""
    errors = []
    count = 0
    for fname in sorted(os.listdir(suites_dir)):
        if not fname.endswith(".json"):
            continue
        count += 1
        path = os.path.join(suites_dir, fname)
        try:
            with open(path) as f:
                suite = json.load(f)
        except json.JSONDecodeError as e:
            errors.append(f"suites/{fname}: invalid JSON: {e}")
            continue

        if "suite_name" not in suite:
            errors.append(f"suites/{fname}: missing 'suite_name'")
        if "test_cases" not in suite:
            errors.append(f"suites/{fname}: missing 'test_cases'")
            continue

        ids = set()
        for i, tc in enumerate(suite["test_cases"]):
            tc_id = tc.get("id", f"index-{i}")
            if "id" not in tc:
                errors.append(f"suites/{fname}: test_cases[{i}] missing 'id'")
            elif tc["id"] in ids:
                errors.append(f"suites/{fname}: duplicate test case id '{tc['id']}'")
            else:
                ids.add(tc["id"])
            if "behavior" not in tc:
                errors.append(
                    f"suites/{fname}: test case '{tc_id}' missing 'behavior'"
                )
            if "components" not in tc:
                errors.append(
                    f"suites/{fname}: test case '{tc_id}' missing 'components'"
                )

    if count == 0:
        errors.append(f"suites/: no JSON files found in {suites_dir}")
    return errors


def validate_oracle(oracle_dir):
    """Validate oracle test suite JSON files."""
    errors = []
    count = 0
    for fname in sorted(os.listdir(oracle_dir)):
        if not fname.endswith(".json"):
            continue
        count += 1
        path = os.path.join(oracle_dir, fname)
        try:
            with open(path) as f:
                suite = json.load(f)
        except json.JSONDecodeError as e:
            errors.append(f"oracle/{fname}: invalid JSON: {e}")
            continue

        if "suite_name" not in suite:
            errors.append(f"oracle/{fname}: missing 'suite_name'")
        if "test_cases" not in suite:
            errors.append(f"oracle/{fname}: missing 'test_cases'")
            continue

        for i, tc in enumerate(suite["test_cases"]):
            tc_id = tc.get("id", f"index-{i}")
            if "id" not in tc:
                errors.append(f"oracle/{fname}: test_cases[{i}] missing 'id'")
            tc_type = tc.get("type", "match")
            if tc_type == "match":
                if "template" not in tc and "template_ref" not in tc:
                    errors.append(
                        f"oracle/{fname}: '{tc_id}' missing 'template' or 'template_ref'"
                    )
                if "expected_match" not in tc:
                    errors.append(
                        f"oracle/{fname}: '{tc_id}' missing 'expected_match'"
                    )
            elif tc_type == "verdict":
                if "operations" not in tc:
                    errors.append(
                        f"oracle/{fname}: '{tc_id}' missing 'operations'"
                    )
                if "expected_verdict" not in tc:
                    errors.append(
                        f"oracle/{fname}: '{tc_id}' missing 'expected_verdict'"
                    )
            else:
                errors.append(
                    f"oracle/{fname}: '{tc_id}' unknown type '{tc_type}'"
                )

    if count == 0:
        errors.append(f"oracle/: no JSON files found in {oracle_dir}")
    return errors


def validate_pics(pics_dir):
    """Validate PICS profile JSON files."""
    errors = []
    count = 0
    for fname in sorted(os.listdir(pics_dir)):
        if not fname.endswith(".json"):
            continue
        count += 1
        path = os.path.join(pics_dir, fname)
        try:
            with open(path) as f:
                pics = json.load(f)
        except json.JSONDecodeError as e:
            errors.append(f"pics/{fname}: invalid JSON: {e}")
            continue

        if "capabilities" not in pics:
            errors.append(f"pics/{fname}: missing 'capabilities'")
            continue

        for cap, val in pics["capabilities"].items():
            if not isinstance(val, bool):
                errors.append(
                    f"pics/{fname}: capability '{cap}' must be boolean, "
                    f"got {type(val).__name__}"
                )

    if count == 0:
        errors.append(f"pics/: no JSON files found in {pics_dir}")
    return errors


def validate_reports(reports_dir):
    """Validate conformance report JSON files."""
    errors = []
    report_files = sorted(
        f for f in os.listdir(reports_dir)
        if f.startswith("report_") and f.endswith(".json")
    )

    if not report_files:
        errors.append(f"No report files (report_*.json) found in {reports_dir}")
        return errors

    for fname in report_files:
        path = os.path.join(reports_dir, fname)
        try:
            with open(path) as f:
                report = json.load(f)
        except json.JSONDecodeError as e:
            errors.append(f"{fname}: invalid JSON: {e}")
            continue

        if "profile" not in report:
            errors.append(f"{fname}: missing 'profile'")
        if "overall_verdict" not in report:
            errors.append(f"{fname}: missing 'overall_verdict'")
        elif report["overall_verdict"] not in VALID_VERDICTS:
            errors.append(
                f"{fname}: invalid overall_verdict '{report['overall_verdict']}'"
            )

        if "suites" not in report:
            errors.append(f"{fname}: missing 'suites'")
            continue

        for i, suite in enumerate(report["suites"]):
            prefix = f"{fname}/suites[{i}]"
            required_keys = (
                "suite_name", "total", "selected", "skipped",
                "results", "suite_verdict"
            )
            for key in required_keys:
                if key not in suite:
                    errors.append(f"{prefix}: missing '{key}'")

            sv = suite.get("suite_verdict")
            if sv is not None and sv not in VALID_VERDICTS:
                errors.append(f"{prefix}: invalid suite_verdict '{sv}'")

            results = suite.get("results", [])
            for j, r in enumerate(results):
                for key in ("id", "verdict", "group"):
                    if key not in r:
                        errors.append(f"{prefix}/results[{j}]: missing '{key}'")
                rv = r.get("verdict")
                if rv is not None and rv not in VALID_VERDICTS:
                    errors.append(
                        f"{prefix}/results[{j}]: invalid verdict '{rv}'"
                    )

            if all(k in suite for k in ("total", "selected", "skipped")):
                expected = suite["selected"] + len(suite["skipped"])
                if expected != suite["total"]:
                    errors.append(
                        f"{prefix}: selected({suite['selected']}) + "
                        f"skipped({len(suite['skipped'])}) != "
                        f"total({suite['total']})"
                    )

    return errors


def main():
    parser = argparse.ArgumentParser(
        description="TTCN-3 conformance pipeline validator"
    )
    parser.add_argument("--suites", help="Validate engine test suite directory")
    parser.add_argument("--oracle", help="Validate oracle test suite directory")
    parser.add_argument("--pics", help="Validate PICS profile directory")
    parser.add_argument("--reports", help="Validate conformance report directory")
    args = parser.parse_args()

    if not any([args.suites, args.oracle, args.pics, args.reports]):
        parser.print_help()
        return 1

    all_errors = []

    if args.suites:
        print(f"Validating engine suites: {args.suites}")
        all_errors.extend(validate_suites(args.suites))
    if args.oracle:
        print(f"Validating oracle suites: {args.oracle}")
        all_errors.extend(validate_oracle(args.oracle))
    if args.pics:
        print(f"Validating PICS profiles: {args.pics}")
        all_errors.extend(validate_pics(args.pics))
    if args.reports:
        print(f"Validating conformance reports: {args.reports}")
        all_errors.extend(validate_reports(args.reports))

    if all_errors:
        print(
            f"\nVALIDATION FAILED -- {len(all_errors)} error(s):",
            file=sys.stderr
        )
        for e in all_errors:
            print(f"  [X] {e}", file=sys.stderr)
        return 1

    print("Validation passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
