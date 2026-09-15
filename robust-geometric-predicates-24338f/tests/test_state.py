
import subprocess
import os
import pytest


def build_predicates():
    """Build the project, return make result."""
    subprocess.run(["make", "-C", "/app", "clean"], capture_output=True, text=True)
    result = subprocess.run(["make", "-C", "/app"], capture_output=True, text=True)
    return result


def run_predicates():
    """Build and run the predicate tests, return stdout."""
    result = build_predicates()
    assert result.returncode == 0, f"Build failed:\n{result.stderr}"
    assert os.path.isfile("/app/test_predicates"), "test_predicates binary not produced by make"

    result = subprocess.run(
        ["/app/test_predicates"],
        capture_output=True, text=True,
        timeout=120
    )
    return result


class TestPredicates:
    """Verify that all four geometric predicates produce correct signs."""

    def test_builds_successfully(self):
        """The project must compile without errors and produce test_predicates."""
        result = build_predicates()
        assert result.returncode == 0, f"Build failed:\n{result.stderr}"
        assert os.path.isfile("/app/test_predicates"), "test_predicates binary not produced by make"

    def test_orient2d_passes(self):
        """orient2d must return correct signs for all 100 near-degenerate test cases."""
        result = run_predicates()
        lines = result.stdout.strip().split("\n")
        orient2d_line = [l for l in lines if l.startswith("orient2d:")]
        assert len(orient2d_line) == 1, f"Missing orient2d output. stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        parts = orient2d_line[0].split()
        counts = parts[1].split("/")
        passed, total = int(counts[0]), int(counts[1])
        assert total == 100, f"Expected 100 orient2d tests, got {total}"
        assert passed == total, f"orient2d: {passed}/{total} passed"

    def test_orient3d_passes(self):
        """orient3d must return correct signs for all 100 near-degenerate test cases."""
        result = run_predicates()
        lines = result.stdout.strip().split("\n")
        orient3d_line = [l for l in lines if l.startswith("orient3d:")]
        assert len(orient3d_line) == 1, f"Missing orient3d output. stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        parts = orient3d_line[0].split()
        counts = parts[1].split("/")
        passed, total = int(counts[0]), int(counts[1])
        assert total == 100, f"Expected 100 orient3d tests, got {total}"
        assert passed == total, f"orient3d: {passed}/{total} passed"

    def test_incircle_passes(self):
        """incircle must return correct signs for all 100 near-degenerate test cases."""
        result = run_predicates()
        lines = result.stdout.strip().split("\n")
        incircle_line = [l for l in lines if l.startswith("incircle:")]
        assert len(incircle_line) == 1, f"Missing incircle output. stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        parts = incircle_line[0].split()
        counts = parts[1].split("/")
        passed, total = int(counts[0]), int(counts[1])
        assert total == 100, f"Expected 100 incircle tests, got {total}"
        assert passed == total, f"incircle: {passed}/{total} passed"

    def test_insphere_passes(self):
        """insphere must return correct signs for all 100 near-degenerate test cases."""
        result = run_predicates()
        lines = result.stdout.strip().split("\n")
        insphere_line = [l for l in lines if l.startswith("insphere:")]
        assert len(insphere_line) == 1, f"Missing insphere output. stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        parts = insphere_line[0].split()
        counts = parts[1].split("/")
        passed, total = int(counts[0]), int(counts[1])
        assert total == 100, f"Expected 100 insphere tests, got {total}"
        assert passed == total, f"insphere: {passed}/{total} passed"

    def test_all_pass(self):
        """The test binary must exit with code 0 (all 400 tests pass)."""
        result = run_predicates()
        assert result.returncode == 0, (
            f"test_predicates exited with code {result.returncode}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
        assert "ALL TESTS PASSED" in result.stdout
