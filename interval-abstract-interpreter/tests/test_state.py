
import pytest
import subprocess
import json
import os

EXPECTED = {
    "01_safe_loop.json": [
        {"line": 3, "kind": "boa", "status": "safe"},
    ],
    "02_bounds_errors.json": [
        {"line": 1, "kind": "boa", "status": "safe"},
        {"line": 2, "kind": "boa", "status": "safe"},
        {"line": 3, "kind": "boa", "status": "error"},
        {"line": 7, "kind": "boa", "status": "safe"},
        {"line": 8, "kind": "boa", "status": "warning"},
    ],
    "03_division_safety.json": [
        {"line": 2, "kind": "dbz", "status": "warning"},
        {"line": 4, "kind": "dbz", "status": "safe"},
        {"line": 6, "kind": "dbz", "status": "error"},
    ],
    "04_narrowing_proof.json": [
        {"line": 4, "kind": "assert", "status": "safe"},
        {"line": 5, "kind": "assert", "status": "safe"},
    ],
    "05_nested_array.json": [
        {"line": 6, "kind": "boa", "status": "safe"},
    ],
    "06_interval_limits.json": [
        {"line": 7, "kind": "dbz", "status": "warning"},
        {"line": 8, "kind": "boa", "status": "safe"},
    ],
}


def sort_checks(checks):
    return sorted(checks, key=lambda c: (c["line"], c["kind"]))


@pytest.mark.parametrize("program", sorted(EXPECTED.keys()))
def test_analyzer_output(program):
    """Run analyzer on a program and verify check results."""
    prog_path = f"/app/programs/{program}"
    assert os.path.exists(prog_path), f"Program file not found: {prog_path}"
    assert os.path.exists("/app/analyzer.py"), "Analyzer not found at /app/analyzer.py"

    result = subprocess.run(
        ["python3", "/app/analyzer.py", prog_path],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"Analyzer exited with code {result.returncode} on {program}.\n"
        f"stderr: {result.stderr[:500]}"
    )

    try:
        output = json.loads(result.stdout)
    except json.JSONDecodeError:
        pytest.fail(
            f"Analyzer output is not valid JSON for {program}.\n"
            f"stdout: {result.stdout[:500]}"
        )

    assert "checks" in output, f"Output missing 'checks' key for {program}"

    actual = sort_checks(output["checks"])
    expected = sort_checks(EXPECTED[program])

    assert len(actual) == len(expected), (
        f"Check count mismatch for {program}: "
        f"got {len(actual)}, expected {len(expected)}.\n"
        f"Actual:   {json.dumps(actual, indent=2)}\n"
        f"Expected: {json.dumps(expected, indent=2)}"
    )

    for i, (act, exp) in enumerate(zip(actual, expected)):
        assert act == exp, (
            f"Check {i} mismatch for {program}:\n"
            f"  Got:      {act}\n"
            f"  Expected: {exp}\n"
            f"  All actual:   {json.dumps(actual, indent=2)}\n"
            f"  All expected: {json.dumps(expected, indent=2)}"
        )


def test_analyzer_exists():
    """Verify analyzer.py exists and is executable."""
    assert os.path.exists("/app/analyzer.py"), (
        "analyzer.py not found at /app/analyzer.py"
    )


def test_all_programs_present():
    """Verify all test programs exist."""
    for prog in EXPECTED:
        path = f"/app/programs/{prog}"
        assert os.path.exists(path), f"Missing program: {path}"


def test_output_is_sorted():
    """Verify analyzer outputs checks in sorted order."""
    for program in sorted(EXPECTED.keys()):
        prog_path = f"/app/programs/{program}"
        result = subprocess.run(
            ["python3", "/app/analyzer.py", prog_path],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            continue
        try:
            output = json.loads(result.stdout)
        except json.JSONDecodeError:
            continue
        checks = output.get("checks", [])
        sorted_checks = sort_checks(checks)
        assert checks == sorted_checks, (
            f"Checks not sorted for {program}. "
            f"Got: {checks}, expected sorted: {sorted_checks}"
        )
