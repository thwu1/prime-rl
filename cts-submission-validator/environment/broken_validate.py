#!/usr/bin/env python3
"""Conformance submission validator for VK-GL-CTS audit reports.

NOTE: This validator is known to produce incorrect results. It is provided
as a reference for the data format, not as a working solution.
"""
import os
import re
import json
import xml.etree.ElementTree as ET
from collections import defaultdict

DATA_DIR = "/data"

ALLOWED_STATUSES = {
    "Pass", "NotSupported", "QualityWarning", "CompatibilityWarning", "Waiver"
}


def parse_qpa(filepath):
    """Extract test results from a QPA file."""
    with open(filepath) as f:
        content = f.read()
    results = []
    for match in re.finditer(
        r"#beginTestCaseResult\s+(\S+)\s*\n(.*?)#endTestCaseResult",
        content, re.DOTALL
    ):
        test_name = match.group(1)
        block = match.group(2)
        status_match = re.search(r'StatusCode="(\w+)"', block)
        if status_match:
            results.append((test_name, status_match.group(1)))
    return results


def load_mustpass(base_dir):
    """Load all mustpass test names from the index file and category files."""
    index_path = os.path.join(base_dir, "vk-default.txt")
    tests = set()
    with open(index_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            cat_path = os.path.join(base_dir, line)
            if os.path.isfile(cat_path):
                with open(cat_path) as cf:
                    for entry in cf:
                        entry = entry.strip()
                        if entry:
                            tests.add(entry)
    return tests


def load_waiver_patterns(waiver_path):
    """Parse waiver XML and return list of test path patterns."""
    tree = ET.parse(waiver_path)
    root = tree.getroot()
    patterns = []
    for waiver_elem in root.findall("waiver"):
        for test_elem in waiver_elem.findall("test"):
            if test_elem.text:
                patterns.append(test_elem.text.strip())
    return patterns


def is_waived(test_name, patterns):
    """Check if a test name matches any waiver pattern."""
    for pattern in patterns:
        if test_name == pattern:
            return True
    return False


def validate_statement(submission_dir):
    """Validate the conformance statement file for required fields."""
    required_fields = ["CONFORM_VERSION", "PRODUCT", "CPU"]
    stmt_files = [
        f for f in os.listdir(submission_dir) if f.startswith("STATEMENT")
    ]
    if not stmt_files:
        return False, ["No STATEMENT file found"]

    found_fields = set()
    stmt_path = os.path.join(submission_dir, stmt_files[0])
    with open(stmt_path) as f:
        for line in f:
            line = line.strip()
            if ":" in line:
                field_name = line.split(":")[0].strip()
                found_fields.add(field_name)

    missing = [
        f"Missing required field: {r}"
        for r in required_fields
        if r not in found_fields
    ]
    return len(missing) == 0, missing


def main():
    mustpass = load_mustpass(f"{DATA_DIR}/mustpass")

    results_dir = f"{DATA_DIR}/results"
    result_files = sorted(
        f for f in os.listdir(results_dir) if f.endswith(".qpa")
    )

    merged_results = {}
    duplicate_tests = set()
    per_fraction = {}

    for rf in result_files:
        entries = parse_qpa(os.path.join(results_dir, rf))
        per_fraction[rf] = entries

        fraction_seen = {}
        for test_name, status in entries:
            if test_name in fraction_seen:
                duplicate_tests.add(test_name)
            else:
                fraction_seen[test_name] = status

        merged_results.update(fraction_seen)

    waiver_patterns = load_waiver_patterns(f"{DATA_DIR}/waivers/waivers.xml")

    with open(f"{DATA_DIR}/fraction-mandatory.txt") as f:
        mandatory_tests = {line.strip() for line in f if line.strip()}

    mandatory_complete = True
    for rf, entries in per_fraction.items():
        fraction_names = {name for name, _ in entries}
        if not mandatory_tests.issubset(fraction_names):
            mandatory_complete = False
            break

    tested = set(merged_results.keys())
    missing_tests = mustpass - tested

    raw_counts = defaultdict(int)
    for status in merged_results.values():
        raw_counts[status] += 1

    waived_tests = set()
    effective_results = {}
    for name, status in merged_results.items():
        if status == "Fail" and is_waived(name, waiver_patterns):
            waived_tests.add(name)
            effective_results[name] = "Waiver"
        else:
            effective_results[name] = status

    effective_counts = defaultdict(int)
    for status in effective_results.values():
        effective_counts[status] += 1

    violations = sorted(
        name for name, status in effective_results.items()
        if status not in ALLOWED_STATUSES
    )

    stmt_valid, stmt_errors = validate_statement(f"{DATA_DIR}/submission")

    conformant = (
        len(violations) == 0
        and len(missing_tests) == 0
        and stmt_valid
        and mandatory_complete
    )

    report = {
        "mustpass_total": len(mustpass),
        "tests_with_results": len(tested),
        "tests_missing_count": len(missing_tests),
        "tests_missing": sorted(missing_tests),
        "raw_status_counts": dict(raw_counts),
        "waived_tests_count": len(waived_tests),
        "waived_tests": sorted(waived_tests),
        "effective_status_counts": dict(effective_counts),
        "conformance_violations_count": len(violations),
        "conformance_violations": violations,
        "duplicate_results_count": len(duplicate_tests),
        "duplicate_results": sorted(duplicate_tests),
        "fraction_count": len(result_files),
        "fraction_mandatory_complete": mandatory_complete,
        "statement_valid": stmt_valid,
        "statement_errors": stmt_errors,
        "overall_conformant": conformant,
    }

    with open("/app/report.json", "w") as f:
        json.dump(report, f, indent=2)
    print("Audit report written to /app/report.json")


if __name__ == "__main__":
    main()
