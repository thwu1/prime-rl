"""
Pytest wrapper that validates the Go-based consensus cluster simulation.
Runs the pre-compiled Go test binary and checks individual test outcomes.

"""
import subprocess
import os
import shutil
import pytest

_GO_RESULTS = None


def _run_go_tests():
    """Run the Go test binary once and cache parsed results."""
    global _GO_RESULTS
    if _GO_RESULTS is not None:
        return _GO_RESULTS

    # Ensure test file is in the right place
    if not os.path.exists("/app/raft/node_test.go"):
        shutil.copy("/tests/node_test.go", "/app/raft/node_test.go")

    # Build the test binary if it does not already exist
    if not os.path.exists("/tmp/raft_test"):
        build = subprocess.run(
            ["go", "test", "-c", "-o", "/tmp/raft_test", "./raft/"],
            capture_output=True, text=True, cwd="/app", timeout=120,
        )
        if build.returncode != 0:
            _GO_RESULTS = {"__build_error__": build.stderr}
            return _GO_RESULTS

    try:
        result = subprocess.run(
            ["/tmp/raft_test", "-test.v", "-test.timeout=120s"],
            capture_output=True, text=True, timeout=180,
        )
        output = result.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        _GO_RESULTS = {"__error__": str(exc)}
        return _GO_RESULTS

    results = {}
    for line in output.split("\n"):
        line = line.strip()
        if line.startswith("--- PASS: "):
            name = line.split("--- PASS: ")[1].split(" ")[0]
            results[name] = "pass"
        elif line.startswith("--- FAIL: "):
            name = line.split("--- FAIL: ")[1].split(" ")[0]
            results[name] = "fail"
    _GO_RESULTS = results
    return results


def _check(test_name):
    results = _run_go_tests()
    if "__build_error__" in results:
        pytest.fail(f"Go build failed: {results['__build_error__']}")
    if "__error__" in results:
        pytest.fail(f"Go test error: {results['__error__']}")
    status = results.get(test_name)
    assert status == "pass", (
        f"Go test {test_name} did not pass (status: {status or 'not found'})"
    )


# ----------------------------------------------------------------
#  Leader election
# ----------------------------------------------------------------

class TestLeaderElection:
    def test_initial_election_three_nodes(self):
        _check("TestInitialElectionThreeNodes")

    def test_initial_election_five_nodes(self):
        _check("TestInitialElectionFiveNodes")

    def test_election_safety(self):
        _check("TestElectionSafety")

    def test_reelection_after_leader_failure(self):
        _check("TestReelectionAfterLeaderFailure")

    def test_cascading_leader_failures(self):
        _check("TestCascadingLeaderFailures")


# ----------------------------------------------------------------
#  Log replication
# ----------------------------------------------------------------

class TestLogReplication:
    def test_basic_replication(self):
        _check("TestBasicReplication")

    def test_multiple_entries_in_order(self):
        _check("TestMultipleEntriesInOrder")

    def test_replication_survives_leader_change(self):
        _check("TestReplicationSurvivesLeaderChange")

    def test_many_entries_across_leader_change(self):
        _check("TestManyEntriesAcrossLeaderChange")


# ----------------------------------------------------------------
#  Follower recovery
# ----------------------------------------------------------------

class TestFollowerRecovery:
    def test_follower_catches_up(self):
        _check("TestFollowerCatchesUp")


# ----------------------------------------------------------------
#  Network partitions
# ----------------------------------------------------------------

class TestNetworkPartition:
    def test_partition_majority_continues(self):
        _check("TestPartitionMajorityContinues")

    def test_partition_heal_convergence(self):
        _check("TestPartitionHealConvergence")


# ----------------------------------------------------------------
#  Log consistency
# ----------------------------------------------------------------

class TestLogConsistency:
    def test_committed_logs_agree(self):
        _check("TestCommittedLogsAgree")

    def test_overwritten_stale_entries(self):
        _check("TestOverwrittenStaleEntries")
