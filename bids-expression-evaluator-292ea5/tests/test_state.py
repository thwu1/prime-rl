import subprocess
import json
import os



def test_typescript_compiles():
    """The TypeScript source must compile without errors."""
    result = subprocess.run(
        ["npx", "tsc", "--noEmit"],
        capture_output=True,
        text=True,
        cwd="/app",
        timeout=120,
    )
    assert result.returncode == 0, (
        f"TypeScript compilation failed:\n{result.stdout}\n{result.stderr}"
    )


def test_all_expression_tests_pass():
    """Every expression in expression_tests.yaml must evaluate correctly."""
    result = subprocess.run(
        ["npx", "ts-node", "src/run_tests.ts"],
        capture_output=True,
        text=True,
        cwd="/app",
        timeout=120,
    )
    assert result.returncode == 0, (
        f"Test runner exited with code {result.returncode}:\n{result.stderr}"
    )

    # Parse the JSON output
    stdout = result.stdout.strip()
    data = json.loads(stdout)

    total = data["total"]
    passed = data["passed"]
    failed = data["failed"]
    errors = data.get("errors", [])

    assert total > 0, "No test cases were executed"
    assert total >= 77, f"Expected at least 77 test cases, got {total}"
    assert failed == 0, (
        f"{failed}/{total} expression tests failed. "
        f"First failures:\n{json.dumps(errors[:5], indent=2, default=str)}"
    )


def test_evaluator_handles_edge_cases():
    """Spot-check a few critical expressions via the CLI."""
    cases = [
        ('false && null', 'false'),
        ('true || null', 'true'),
        ('3 % 2', '1'),
        ('"string"[0]', '"s"'),
    ]
    for expr, expected in cases:
        result = subprocess.run(
            ["npx", "ts-node", "src/index.ts", expr],
            capture_output=True,
            text=True,
            cwd="/app",
            timeout=30,
        )
        actual = result.stdout.strip()
        assert actual == expected, (
            f"Expression '{expr}': expected {expected}, got {actual}"
        )
