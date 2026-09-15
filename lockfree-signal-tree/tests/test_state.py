"""
Tests for the lock-free signal tree implementation.

Compiles /app/signal_tree.c, runs the C test suite, and verifies
all 12 tests pass.

"""

import subprocess
import pytest


@pytest.fixture(scope="module")
def test_output():
    """Build the signal tree and run the C test suite once."""
    # Clean build
    subprocess.run(["make", "-C", "/app", "clean"],
                   capture_output=True, timeout=30)

    build = subprocess.run(["make", "-C", "/app"],
                           capture_output=True, text=True, timeout=60)
    assert build.returncode == 0, (
        f"Build failed (exit {build.returncode}):\n"
        f"STDOUT:\n{build.stdout}\nSTDERR:\n{build.stderr}"
    )

    run = subprocess.run(["/app/test_runner"],
                         capture_output=True, text=True, timeout=120)
    return run


EXPECTED_TESTS = [
    "test_create_destroy",
    "test_empty_initially",
    "test_set_single",
    "test_set_all_select_all",
    "test_double_set",
    "test_select_empty",
    "test_tree_was_empty",
    "test_interleaved",
    "test_boundary_signals",
    "test_specific_pattern",
    "test_concurrent",
    "test_stress",
]


def test_no_failures(test_output):
    """The test runner must exit 0 with no FAIL lines."""
    assert test_output.returncode == 0, (
        f"test_runner exited {test_output.returncode}:\n{test_output.stdout}"
    )
    assert "FAIL" not in test_output.stdout, (
        f"Some C tests failed:\n{test_output.stdout}"
    )


@pytest.mark.parametrize("test_name", EXPECTED_TESTS)
def test_individual(test_output, test_name):
    """Each named C test must print PASS."""
    assert f"PASS: {test_name}" in test_output.stdout, (
        f"{test_name} did not pass. Output:\n{test_output.stdout}"
    )
