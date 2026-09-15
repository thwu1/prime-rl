"""
Tests for the SQL dialect transpiler.

Reads results from /tmp/transpiler_test_results.json, produced by
the test runner (test_runner.js) executed before pytest.
"""

import json
import os
import pytest

RESULTS_FILE = '/tmp/transpiler_test_results.json'


def _load_results():
    if not os.path.exists(RESULTS_FILE):
        return [
            {
                "title": "compilation_or_runner_failure",
                "passed": False,
                "expected": "results file to exist",
                "actual": "test runner did not produce results - build pipeline may have failed",
            }
        ]
    with open(RESULTS_FILE) as f:
        data = json.load(f)
    return data.get("results", [])


_cases = _load_results()


@pytest.mark.parametrize("case", _cases, ids=lambda c: c.get("title", "unknown"))
def test_transpiler(case):
    assert case["passed"], (
        f"\n  Expected: {case['expected']}\n  Actual:   {case['actual']}"
    )


def test_minimum_case_count():
    """Ensure the test runner produced all expected test cases."""
    assert len(_cases) >= 38, (
        f"Expected at least 38 test cases, got {len(_cases)}"
    )


def test_no_runtime_errors():
    """Ensure no test case produced a runtime error (exception)."""
    errors = [c for c in _cases if c.get("actual", "").startswith("ERROR:")]
    assert len(errors) == 0, (
        f"{len(errors)} test(s) threw runtime errors:\n"
        + "\n".join(f"  {e['title']}: {e['actual']}" for e in errors)
    )


def test_parser_tests_present():
    """Ensure round-trip (parser) tests ran, not just stringify tests."""
    roundtrips = [c for c in _cases if c.get("title", "").startswith("parse_")]
    assert len(roundtrips) >= 14, (
        f"Expected at least 14 parser round-trip tests, got {len(roundtrips)}"
    )


def test_transpile_tests_present():
    """Ensure cross-dialect transpilation tests ran."""
    transpiles = [c for c in _cases if c.get("title", "").startswith("transpile_")]
    assert len(transpiles) >= 5, (
        f"Expected at least 5 transpilation tests, got {len(transpiles)}"
    )
