
import subprocess
import pytest

_cached_result = None

def _get_go_test_result():
    """Run go tests once and cache the result."""
    global _cached_result
    if _cached_result is None:
        # Skip TestFailChecks (ungraded reference test with tight predicates)
        result = subprocess.run(
            ["go", "test", "./pkg/paxos/", "-v", "-count=1", "-timeout", "240s",
             "-run", "TestUnit|TestBasic|TestBfs|TestInvariant|TestPartition|TestCase5Failures|TestNotTerminate|TestConcurrentProposer"],
            capture_output=True,
            text=True,
            cwd="/app",
            timeout=260,
        )
        _cached_result = (result.returncode, result.stdout + result.stderr)
    return _cached_result


def test_go_tests_pass():
    """All Go tests in the paxos package must pass."""
    exit_code, output = _get_go_test_result()
    assert exit_code == 0, f"Go tests failed with exit code {exit_code}:\n{output[-3000:]}"


def test_unit_tests_pass():
    """TestUnit must pass - verifies Paxos message handler correctness."""
    _, output = _get_go_test_result()
    assert "--- PASS: TestUnit" in output, f"TestUnit did not pass:\n{output[-3000:]}"


def test_bfs_tests_pass():
    """BFS scenario tests must pass."""
    _, output = _get_go_test_result()
    for test_name in ["TestBfs1", "TestBfs2", "TestBfs3"]:
        assert f"--- PASS: {test_name}" in output, f"{test_name} did not pass:\n{output[-3000:]}"


def test_invariant_pass():
    """TestInvariant must pass - consensus safety check."""
    _, output = _get_go_test_result()
    assert "--- PASS: TestInvariant" in output, f"TestInvariant did not pass:\n{output[-3000:]}"


def test_partition_tests_pass():
    """Partition scenario tests must pass."""
    _, output = _get_go_test_result()
    for test_name in ["TestPartition1", "TestPartition2"]:
        assert f"--- PASS: {test_name}" in output, f"{test_name} did not pass:\n{output[-3000:]}"


def test_student_scenario_tests_pass():
    """Student-implemented scenario predicate tests must pass."""
    _, output = _get_go_test_result()
    for test_name in ["TestCase5Failures", "TestNotTerminate", "TestConcurrentProposer"]:
        assert f"--- PASS: {test_name}" in output, f"{test_name} did not pass:\n{output[-3000:]}"
