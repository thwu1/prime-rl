
"""Conformance tests for the SQL-on-FHIR ViewDefinition evaluator."""

import subprocess
import json
import pytest


@pytest.fixture(scope="session")
def all_results():
    """Run the conformance test runner and parse JSON output."""
    result = subprocess.run(
        ["npx", "tsx", "/app/runner.ts"],
        capture_output=True,
        text=True,
        cwd="/app",
        timeout=120,
    )
    stdout = result.stdout.strip()
    if not stdout:
        pytest.fail(
            f"Test runner produced no output.\nstderr: {result.stderr[:1000]}"
        )
    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        pytest.fail(
            f"Test runner output is not valid JSON.\nstdout: {stdout[:500]}\nstderr: {result.stderr[:500]}"
        )


@pytest.fixture(scope="session")
def results_by_file(all_results):
    by_file = {}
    for r in all_results["results"]:
        by_file.setdefault(r["file"], []).append(r)
    return by_file


def test_no_failures(all_results):
    """All conformance tests must pass (zero failures)."""
    failed = [r for r in all_results["results"] if not r["passed"]]
    total = all_results["total"]
    if failed:
        msgs = [
            f"  FAIL {r['file']}::{r['title']}: {r.get('error', '?')}"
            for r in failed[:15]
        ]
        detail = "\n".join(msgs)
        suffix = ""
        if len(failed) > 15:
            suffix = f"\n  ... and {len(failed) - 15} more"
        pytest.fail(
            f"{len(failed)}/{total} conformance tests failed:\n{detail}{suffix}"
        )


FIXTURE_FILES = [
    "basic.json",
    "foreach.json",
    "union.json",
    "where.json",
    "collection.json",
    "fhirpath.json",
    "logic.json",
    "combinations.json",
    "repeat.json",
    "row_index.json",
    "constant.json",
    "validate.json",
]


@pytest.mark.parametrize("fixture_file", FIXTURE_FILES)
def test_fixture_file(results_by_file, fixture_file):
    """Each fixture file's tests must all pass."""
    results = results_by_file.get(fixture_file, [])
    assert len(results) > 0, f"No test results found for {fixture_file}"
    failed = [r for r in results if not r["passed"]]
    if failed:
        msgs = [f"  - {r['title']}: {r.get('error', '?')}" for r in failed]
        pytest.fail(
            f"{len(failed)}/{len(results)} tests in {fixture_file} failed:\n"
            + "\n".join(msgs)
        )


def test_minimum_test_count(all_results):
    """Ensure the runner executed a reasonable number of tests."""
    assert all_results["total"] >= 100, (
        f"Expected at least 100 tests, got {all_results['total']}"
    )
