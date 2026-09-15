
import subprocess
import pytest


def run_go_tests():
    """Run go test for the paxos package and return the result."""
    result = subprocess.run(
        ["go", "test", "./pkg/paxos/...", "-v", "-count=1", "-timeout", "540s"],
        cwd="/app",
        capture_output=True,
        text=True,
        timeout=570,
    )
    return result


def parse_test_results(output):
    """Parse go test -v output and return dict of test_name -> pass/fail."""
    results = {}
    for line in output.split("\n"):
        line = line.strip()
        if line.startswith("--- PASS:"):
            name = line.split("--- PASS:")[1].strip().split(" ")[0]
            results[name] = True
        elif line.startswith("--- FAIL:"):
            name = line.split("--- FAIL:")[1].strip().split(" ")[0]
            results[name] = False
    return results


@pytest.fixture(scope="module")
def go_test_output():
    result = run_go_tests()
    combined = result.stdout + "\n" + result.stderr
    return {
        "returncode": result.returncode,
        "output": combined,
        "results": parse_test_results(combined),
    }


class TestPaxosUnit:
    """Verify Paxos unit tests pass."""

    def test_all_pass(self, go_test_output):
        assert go_test_output["returncode"] == 0, \
            f"Go tests failed (exit {go_test_output['returncode']}):\n{go_test_output['output']}"

    def test_unit(self, go_test_output):
        assert go_test_output["results"].get("TestUnit", False), \
            f"TestUnit failed:\n{go_test_output['output']}"


class TestPaxosScenarios:
    """Verify consensus scenario tests pass."""

    def test_basic_consensus(self, go_test_output):
        assert go_test_output["results"].get("TestBasicConsensus", False), \
            f"TestBasicConsensus failed:\n{go_test_output['output']}"

    def test_dual_proposer(self, go_test_output):
        assert go_test_output["results"].get("TestDualProposerConsensus", False), \
            f"TestDualProposerConsensus failed:\n{go_test_output['output']}"

    def test_safety_invariant(self, go_test_output):
        assert go_test_output["results"].get("TestSafetyInvariant", False), \
            f"TestSafetyInvariant failed:\n{go_test_output['output']}"


class TestAnalysisFunctions:
    """Verify state-space analysis functions pass."""

    def test_count_reachable_states(self, go_test_output):
        assert go_test_output["results"].get("TestCountReachableStates", False), \
            f"TestCountReachableStates failed:\n{go_test_output['output']}"

    def test_find_shortest_consensus_path(self, go_test_output):
        assert go_test_output["results"].get("TestFindShortestConsensusPath", False), \
            f"TestFindShortestConsensusPath failed:\n{go_test_output['output']}"

    def test_verify_safety(self, go_test_output):
        assert go_test_output["results"].get("TestVerifySafety", False), \
            f"TestVerifySafety failed:\n{go_test_output['output']}"

    def test_find_non_terminating(self, go_test_output):
        assert go_test_output["results"].get("TestFindNonTerminatingExecution", False), \
            f"TestFindNonTerminatingExecution failed:\n{go_test_output['output']}"


class TestPredicates:
    """Verify custom predicate tests pass."""

    def test_value_adoption(self, go_test_output):
        assert go_test_output["results"].get("TestValueAdoption", False), \
            f"TestValueAdoption failed:\n{go_test_output['output']}"

    def test_progressive_contention(self, go_test_output):
        assert go_test_output["results"].get("TestProgressiveContention", False), \
            f"TestProgressiveContention failed:\n{go_test_output['output']}"

    def test_three_way_resolution(self, go_test_output):
        assert go_test_output["results"].get("TestThreeWayResolution", False), \
            f"TestThreeWayResolution failed:\n{go_test_output['output']}"
