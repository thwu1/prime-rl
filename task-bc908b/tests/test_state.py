
"""Verify REST API fault discovery: coverage, classification, and tool usage."""

import json
import os
import pytest

REPORT_PATH = '/app/results/report.json'
SPEC_PATH = '/app/spec/openapi.json'
SCHEMATHESIS_OUTPUT_DIR = '/app/results/schemathesis_output'
MIN_COVERAGE_RATIO = 0.80
MIN_UNIQUE_FAULTS = 6
MIN_DISTINCT_EXCEPTION_TYPES = 3


def _load_spec_operations():
    """Dynamically load valid (METHOD, path) pairs from the OpenAPI spec."""
    with open(SPEC_PATH) as f:
        spec = json.load(f)
    ops = set()
    for path, methods in spec.get('paths', {}).items():
        for method in methods:
            m = method.upper()
            if m in ('GET', 'POST', 'PUT', 'PATCH', 'DELETE'):
                ops.add((m, path))
    return ops


VALID_OPERATIONS = _load_spec_operations()
TOTAL_OPERATIONS = len(VALID_OPERATIONS)


@pytest.fixture
def report():
    assert os.path.exists(REPORT_PATH), \
        f"Report not found at {REPORT_PATH}. Did run_fuzzer.sh produce output?"
    with open(REPORT_PATH) as f:
        data = json.load(f)
    return data


def test_report_has_required_fields(report):
    """Report must contain operations_covered, faults, and summary."""
    assert 'operations_covered' in report, "Missing 'operations_covered'"
    assert 'faults' in report, "Missing 'faults'"
    assert 'summary' in report, "Missing 'summary'"
    assert isinstance(report['operations_covered'], list)
    assert isinstance(report['faults'], list)
    assert isinstance(report['summary'], dict)


def test_operations_covered_format(report):
    """Each covered operation must have method and path."""
    for op in report['operations_covered']:
        assert 'method' in op, f"Operation missing 'method': {op}"
        assert 'path' in op, f"Operation missing 'path': {op}"


def test_fault_format_and_classification(report):
    """Each fault must have method, path, status, and exception_type."""
    for fault in report['faults']:
        assert 'method' in fault, f"Fault missing 'method': {fault}"
        assert 'path' in fault, f"Fault missing 'path': {fault}"
        assert 'exception_type' in fault, f"Fault missing 'exception_type': {fault}"
        assert isinstance(fault['exception_type'], str) and len(fault['exception_type']) > 0, \
            f"Fault has empty or non-string exception_type: {fault}"
        has_status = 'status_code' in fault or 'status' in fault
        assert has_status, f"Fault missing status code field: {fault}"


def test_operation_coverage_meets_threshold(report):
    """At least 80% of operations must return 2XX."""
    ops = report['operations_covered']
    covered = len(ops)
    min_required = int(TOTAL_OPERATIONS * MIN_COVERAGE_RATIO)
    assert covered >= min_required, (
        f"Operation coverage too low: {covered}/{TOTAL_OPERATIONS} "
        f"({covered / TOTAL_OPERATIONS:.1%}), need >= {MIN_COVERAGE_RATIO:.0%} "
        f"({min_required}/{TOTAL_OPERATIONS})"
    )


def test_unique_faults_meet_threshold(report):
    """Must find at least 6 unique server-side faults."""
    faults = report['faults']
    found = len(faults)
    assert found >= MIN_UNIQUE_FAULTS, (
        f"Found only {found} unique faults, need >= {MIN_UNIQUE_FAULTS}."
    )


def test_covered_operations_are_valid(report):
    """All reported covered operations must be real API operations from the spec."""
    for op in report['operations_covered']:
        key = (op['method'].upper(), op['path'])
        assert key in VALID_OPERATIONS, (
            f"Reported operation {key} is not a valid API operation from the spec. "
            f"Paths must use templates like /api/v1/users/{{user_id}}, not actual IDs."
        )


def test_faults_reference_valid_operations(report):
    """All reported faults must reference real API operations from the spec."""
    for fault in report['faults']:
        key = (fault['method'].upper(), fault['path'])
        assert key in VALID_OPERATIONS, (
            f"Reported fault operation {key} is not a valid API operation from the spec."
        )


def test_no_duplicate_covered_operations(report):
    """No duplicate entries in operations_covered."""
    ops = report['operations_covered']
    keys = [(op['method'].upper(), op['path']) for op in ops]
    assert len(keys) == len(set(keys)), (
        f"Duplicate operations in coverage report: "
        f"{[k for k in keys if keys.count(k) > 1]}"
    )


def test_no_duplicate_faults(report):
    """No duplicate entries in faults (by method+path)."""
    faults = report['faults']
    keys = [(f['method'].upper(), f['path']) for f in faults]
    assert len(keys) == len(set(keys)), (
        f"Duplicate faults: {[k for k in keys if keys.count(k) > 1]}"
    )


def test_distinct_exception_types(report):
    """Faults must include at least 3 distinct Python exception types."""
    types = set(f['exception_type'] for f in report['faults'])
    assert len(types) >= MIN_DISTINCT_EXCEPTION_TYPES, (
        f"Only {len(types)} distinct exception types found ({types}), "
        f"need >= {MIN_DISTINCT_EXCEPTION_TYPES}. "
        f"The API has diverse failure modes — classify each fault accurately."
    )


def test_schemathesis_output_exists():
    """Schemathesis must have been used: output artifacts must be present."""
    assert os.path.isdir(SCHEMATHESIS_OUTPUT_DIR), (
        f"Schemathesis output directory not found at {SCHEMATHESIS_OUTPUT_DIR}. "
        f"Schemathesis must be used as the primary testing engine."
    )
    files = [f for f in os.listdir(SCHEMATHESIS_OUTPUT_DIR)
             if os.path.isfile(os.path.join(SCHEMATHESIS_OUTPUT_DIR, f))]
    assert len(files) > 0, (
        f"No files found in {SCHEMATHESIS_OUTPUT_DIR}. "
        f"Save Schemathesis output artifacts (cassettes, logs, or reports)."
    )
    max_size = max(
        os.path.getsize(os.path.join(SCHEMATHESIS_OUTPUT_DIR, f))
        for f in files
    )
    assert max_size > 512, (
        f"Schemathesis output files too small ({max_size} bytes). "
        f"Expected substantial output from property-based API testing."
    )
