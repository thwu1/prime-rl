
import subprocess
import re
import pytest


def run_go_tests():
    """Run go test and return output and exit code."""
    result = subprocess.run(
        ["go", "test", "-count=1", "-timeout", "120s", "-v", "./pkg/..."],
        cwd="/app",
        capture_output=True,
        text=True,
        timeout=180,
    )
    return result.stdout + result.stderr, result.returncode


@pytest.fixture(scope="session")
def go_test_output():
    output, exit_code = run_go_tests()
    return output, exit_code


def test_go_tests_pass(go_test_output):
    """All go tests must pass."""
    output, exit_code = go_test_output
    assert exit_code == 0, f"go test failed with exit code {exit_code}:\n{output[-3000:]}"


def test_pingpong_state_tests(go_test_output):
    """Pingpong state tests must pass (model checker core)."""
    output, _ = go_test_output
    # Check that pingpong package tests pass
    assert "FAIL" not in output or "pingpong" not in output.split("FAIL")[1].split("\n")[0], \
        f"Pingpong tests failed:\n{output[-3000:]}"


def test_paxos_unit_test(go_test_output):
    """Paxos unit test must pass (MessageHandler + StartPropose)."""
    output, _ = go_test_output
    assert "Proposer - Send Propose Request" in output, \
        f"TestUnit not found in output:\n{output[-2000:]}"
    assert "Acceptor - Handle Decide Request" in output, \
        f"TestUnit did not complete:\n{output[-2000:]}"


def test_paxos_scenario_tests(go_test_output):
    """Paxos scenario tests must pass (predicate-guided verification)."""
    output, _ = go_test_output
    # Verify the paxos package didn't fail
    lines = output.split("\n")
    paxos_fail = False
    for line in lines:
        if "FAIL" in line and "paxos" in line:
            paxos_fail = True
            break
    assert not paxos_fail, f"Paxos scenario tests failed:\n{output[-3000:]}"


def test_no_panics(go_test_output):
    """No panics should occur during testing."""
    output, _ = go_test_output
    assert "panic:" not in output and "implement me" not in output and "fill me in" not in output, \
        f"Unimplemented functions detected:\n{output[-2000:]}"
