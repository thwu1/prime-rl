
import json
import os


def _load_report():
    path = "/app/report.json"
    assert os.path.exists(path), (
        f"Report file not found at {path}. "
        "Run: cd /app && npm install && npx ts-node src/cli.ts run testdata/*.json > /app/report.json"
    )
    with open(path) as f:
        return json.load(f)


def test_report_exists():
    """Check that the CLI produced a well-formed report."""
    report = _load_report()
    assert "total" in report, "Report missing 'total' field"
    assert "passed" in report, "Report missing 'passed' field"
    assert "results" in report, "Report missing 'results' field"


def test_minimum_test_count():
    """Ensure all test files were loaded (at least 100 tests total)."""
    report = _load_report()
    assert report["total"] >= 100, (
        f"Expected at least 100 tests, got {report['total']}. "
        "Some test data files may not have been loaded."
    )


def test_all_tests_pass():
    """All ViewDefinition compliance tests must pass."""
    report = _load_report()

    failed = [r for r in report.get("results", []) if r["status"] != "PASS"]
    fail_summary = "\n".join(
        f"  [{r.get('file', '?')}] {r.get('title', '?')}: {r.get('message', 'no message')}"
        for r in failed[:15]
    )

    assert report["passed"] == report["total"], (
        f"Expected all {report['total']} tests to pass, "
        f"but only {report['passed']} passed ({report.get('failed', 0)} failed, "
        f"{report.get('errors', 0)} errors).\n"
        f"First failures:\n{fail_summary}"
    )


def test_no_errors():
    """No tests should have thrown unexpected errors."""
    report = _load_report()
    error_tests = [r for r in report.get("results", []) if r["status"] == "ERROR"]
    error_summary = "\n".join(
        f"  [{r.get('file', '?')}] {r.get('title', '?')}: {r.get('message', '')}"
        for r in error_tests[:10]
    )
    assert len(error_tests) == 0, (
        f"{len(error_tests)} test(s) threw unexpected errors:\n{error_summary}"
    )


def test_foreach_null_injection():
    """forEachOrNull tests must pass (null row injection)."""
    report = _load_report()

    foreach_null_tests = [
        r for r in report.get("results", [])
        if "forEachOrNull" in r.get("title", "")
    ]
    failed = [r for r in foreach_null_tests if r["status"] != "PASS"]
    assert len(foreach_null_tests) >= 4, (
        f"Expected at least 4 forEachOrNull tests, found {len(foreach_null_tests)}"
    )
    assert len(failed) == 0, (
        f"{len(failed)} forEachOrNull test(s) failed: "
        + ", ".join(r.get("title", "?") for r in failed)
    )


def test_repeat_tests():
    """repeat directive tests must pass (recursive traversal)."""
    report = _load_report()

    repeat_tests = [
        r for r in report.get("results", [])
        if r.get("file", "") == "test_repeat.json"
    ]
    failed = [r for r in repeat_tests if r["status"] != "PASS"]
    assert len(repeat_tests) >= 15, (
        f"Expected at least 15 repeat tests, found {len(repeat_tests)}"
    )
    assert len(failed) == 0, (
        f"{len(failed)} repeat test(s) failed: "
        + ", ".join(r.get("title", "?") for r in failed)
    )


def test_union_validation():
    """unionAll column validation tests must pass."""
    report = _load_report()

    union_tests = [
        r for r in report.get("results", [])
        if r.get("file", "") == "test_union.json"
    ]
    failed = [r for r in union_tests if r["status"] != "PASS"]
    assert len(failed) == 0, (
        f"{len(failed)} union test(s) failed: "
        + ", ".join(r.get("title", "?") for r in failed)
    )


def test_constant_validation():
    """Constant error-handling tests must pass."""
    report = _load_report()

    constant_tests = [
        r for r in report.get("results", [])
        if r.get("file", "") == "test_constant.json"
    ]
    failed = [r for r in constant_tests if r["status"] != "PASS"]
    assert len(failed) == 0, (
        f"{len(failed)} constant test(s) failed: "
        + ", ".join(r.get("title", "?") for r in failed)
    )


def test_collection_enforcement():
    """Collection flag enforcement tests must pass."""
    report = _load_report()

    collection_tests = [
        r for r in report.get("results", [])
        if r.get("file", "") == "test_collection.json"
    ]
    failed = [r for r in collection_tests if r["status"] != "PASS"]
    assert len(failed) == 0, (
        f"{len(failed)} collection test(s) failed: "
        + ", ".join(r.get("title", "?") for r in failed)
    )


def test_view_resource_validation():
    """View resource tests must pass (including missing resource error)."""
    report = _load_report()

    vr_tests = [
        r for r in report.get("results", [])
        if r.get("file", "") == "test_view_resource.json"
    ]
    failed = [r for r in vr_tests if r["status"] != "PASS"]
    assert len(vr_tests) >= 3, (
        f"Expected at least 3 view_resource tests, found {len(vr_tests)}"
    )
    assert len(failed) == 0, (
        f"{len(failed)} view_resource test(s) failed: "
        + ", ".join(r.get("title", "?") for r in failed)
    )


def test_constant_types():
    """Constant type-aware comparison tests must pass."""
    report = _load_report()

    ct_tests = [
        r for r in report.get("results", [])
        if r.get("file", "") == "test_constant_types.json"
    ]
    failed = [r for r in ct_tests if r["status"] != "PASS"]
    assert len(ct_tests) >= 14, (
        f"Expected at least 14 constant_types tests, found {len(ct_tests)}"
    )
    assert len(failed) == 0, (
        f"{len(failed)} constant_types test(s) failed: "
        + ", ".join(r.get("title", "?") for r in failed)
    )


def test_logic_filtering():
    """Logic (and/or/not) filtering tests must pass."""
    report = _load_report()

    logic_tests = [
        r for r in report.get("results", [])
        if r.get("file", "") == "test_logic.json"
    ]
    failed = [r for r in logic_tests if r["status"] != "PASS"]
    assert len(logic_tests) >= 3, (
        f"Expected at least 3 logic tests, found {len(logic_tests)}"
    )
    assert len(failed) == 0, (
        f"{len(failed)} logic test(s) failed: "
        + ", ".join(r.get("title", "?") for r in failed)
    )


def test_error_cases_handled():
    """Tests that expect errors must correctly raise them."""
    report = _load_report()

    error_titles = [
        "accessing an undefined constant",
        "incorrect constant definition",
        "resource not specified",
        "column mismatch",
        "column order mismatch",
        "fail when 'collection' is not true",
    ]
    for title in error_titles:
        matching = [
            r for r in report.get("results", [])
            if r.get("title", "") == title
        ]
        assert len(matching) > 0, (
            f"Error test '{title}' not found in report"
        )
        assert matching[0]["status"] == "PASS", (
            f"Error test '{title}' did not pass: "
            f"{matching[0].get('message', 'no message')}"
        )


def test_pass_rate():
    """Overall pass rate must be 100%."""
    report = _load_report()
    total = report["total"]
    passed = report["passed"]
    assert total > 0, "No tests were run"
    rate = passed / total
    assert rate == 1.0, (
        f"Pass rate is {rate:.1%} ({passed}/{total}), expected 100%"
    )
