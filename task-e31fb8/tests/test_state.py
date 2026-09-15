
import subprocess
import pytest


def run(cmd, **kwargs):
    """Run a shell command in /app and return the result."""
    return subprocess.run(
        cmd, shell=True, capture_output=True, text=True, cwd="/app", **kwargs
    )


def test_build_succeeds():
    """Modified project must compile without errors."""
    result = run("go build ./...")
    assert result.returncode == 0, f"Build failed:\n{result.stderr}"


def test_all_tests_pass():
    """All tests (existing + new while loop tests) must pass."""
    result = run("go test ./... -count=1 -timeout=120s", timeout=180)
    assert result.returncode == 0, (
        f"go test ./... failed:\n{result.stdout}\n{result.stderr}"
    )


def test_while_basic():
    """Basic while loop counting and null evaluation via compiler+VM."""
    result = run(
        "go test ./vm/ -run TestWhileExpression -count=1 -v", timeout=60
    )
    assert result.returncode == 0, (
        f"TestWhileExpression failed:\n{result.stdout}\n{result.stderr}"
    )
    assert "PASS" in result.stdout


def test_while_break():
    """Break statement exits the innermost while loop correctly."""
    result = run(
        "go test ./vm/ -run TestWhileBreak -count=1 -v", timeout=60
    )
    assert result.returncode == 0, (
        f"TestWhileBreak failed:\n{result.stdout}\n{result.stderr}"
    )
    assert "PASS" in result.stdout


def test_while_continue():
    """Continue statement skips to next iteration correctly."""
    result = run(
        "go test ./vm/ -run TestWhileContinue -count=1 -v", timeout=60
    )
    assert result.returncode == 0, (
        f"TestWhileContinue failed:\n{result.stdout}\n{result.stderr}"
    )
    assert "PASS" in result.stdout


def test_nested_while():
    """Nested while loops with break affecting only innermost loop."""
    result = run(
        "go test ./vm/ -run TestNestedWhile -count=1 -v", timeout=60
    )
    assert result.returncode == 0, (
        f"TestNestedWhile failed:\n{result.stdout}\n{result.stderr}"
    )
    assert "PASS" in result.stdout


def test_while_in_function():
    """While loops work correctly inside function scope with locals."""
    result = run(
        "go test ./vm/ -run TestWhileInFunction -count=1 -v", timeout=60
    )
    assert result.returncode == 0, (
        f"TestWhileInFunction failed:\n{result.stdout}\n{result.stderr}"
    )
    assert "PASS" in result.stdout
