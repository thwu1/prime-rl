
import json
import pytest
import subprocess
import os

RESULTS_PATH = "/tmp/test_results.json"


@pytest.fixture(scope="session", autouse=True)
def build_and_run():
    """Compile TypeScript and run the Node.js test runner."""
    subprocess.run(
        ["bash", "-c", "cd /app && npm install --silent 2>/dev/null && npx tsc"],
        check=True,
        timeout=120,
    )
    result = subprocess.run(
        ["node", "/tests/test_runner.js"],
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, "NODE_PATH": "/app/node_modules"},
    )
    if result.returncode != 0:
        pytest.fail(
            f"Test runner failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )


@pytest.fixture(scope="session")
def results():
    with open(RESULTS_PATH) as f:
        return json.load(f)


def test_full_sync_convergence(results):
    """Two peers must converge after full state exchange."""
    r = results["full_sync_convergence"]
    assert r["pass"], f"Full sync failed: {r.get('detail')}"


def test_delta_sync_convergence(results):
    """Two peers must converge after delta sync."""
    r = results["delta_sync_convergence"]
    assert r["pass"], f"Delta sync failed: {r.get('detail')}"


def test_convergence_check_accuracy(results):
    """checkConvergence() must report true when peers are in sync."""
    r = results["convergence_check_accuracy"]
    assert r["pass"], f"Convergence check wrong: {r.get('detail')}"


def test_three_peer_broadcast(results):
    """broadcastSync must propagate state to ALL peers."""
    r = results["three_peer_broadcast"]
    assert r["pass"], f"Broadcast failed: {r.get('detail')}"


def test_docless_after_full_sync(results):
    """Docless sync must use current doc state, not stale data."""
    r = results["docless_after_full_sync"]
    assert r["pass"], f"Stale snapshot used: {r.get('detail')}"


def test_pending_updates_filtering(results):
    """Sync operations must not contaminate pendingUpdates buffer."""
    r = results["pending_updates_filtering"]
    assert r["pass"], f"Pending grew during sync: {r.get('detail')}"


def test_complex_multi_round(results):
    """Four peers with mixed strategies must all converge."""
    r = results["complex_multi_round"]
    assert r["pass"], f"Multi-round failed: {r.get('detail')}"


def test_delta_sync_diff_correctness(results):
    """Delta sync must send actual data diffs, not empty updates."""
    r = results["delta_sync_diff_correctness"]
    assert r["pass"], f"Delta diffs wrong: {r.get('detail')}"


def test_docless_sync_convergence(results):
    """Two peers must converge using binary-level docless sync."""
    r = results["docless_sync_convergence"]
    assert r["pass"], f"Docless sync failed: {r.get('detail')}"


def test_repeated_edit_sync_cycles(results):
    """Multiple edit-sync rounds must maintain consistency."""
    r = results["repeated_edit_sync_cycles"]
    assert r["pass"], f"Repeated cycles broke: {r.get('detail')}"


def test_fork_peer_state(results):
    """Forked peer must have correct state and update tracking."""
    r = results["fork_peer_state"]
    assert r["pass"], f"Fork state wrong: {r.get('detail')}"


def test_fork_then_sync(results):
    """Forked peer must sync correctly with its parent."""
    r = results["fork_then_sync"]
    assert r["pass"], f"Fork-sync failed: {r.get('detail')}"


def test_drain_pending_updates(results):
    """drainPendingUpdates must return merged update and clear buffer."""
    r = results["drain_pending_updates"]
    assert r["pass"], f"Drain failed: {r.get('detail')}"


def test_network_stats(results):
    """getNetworkStats must return valid values in all cases."""
    r = results["network_stats"]
    assert r["pass"], f"Stats wrong: {r.get('detail')}"


def test_incremental_sync_convergence(results):
    """Incremental sync must exchange pending updates and converge."""
    r = results["incremental_sync_convergence"]
    assert r["pass"], f"Incremental sync failed: {r.get('detail')}"


def test_incremental_sync_buffer_management(results):
    """Incremental sync must clear pending buffers and not pollute them."""
    r = results["incremental_sync_buffer_management"]
    assert r["pass"], f"Buffer management failed: {r.get('detail')}"


def test_checkpoint_diff_applied(results):
    """Checkpoint diff must contain only post-checkpoint changes."""
    r = results["checkpoint_diff_applied"]
    assert r["pass"], f"Checkpoint diff wrong: {r.get('detail')}"


def test_checkpoint_no_changes(results):
    """Checkpoint diff must return null when no changes occurred."""
    r = results["checkpoint_no_changes"]
    assert r["pass"], f"Checkpoint null check failed: {r.get('detail')}"
