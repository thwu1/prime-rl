
import subprocess
import os
import pytest

MAELSTROM = "/opt/maelstrom/maelstrom"
NODE_BIN = "/app/node"


def run_maelstrom(extra_args, timeout=120):
    """Run Maelstrom with the txn-rw-register workload against the node binary."""
    cmd = [
        MAELSTROM, "test",
        "-w", "txn-rw-register",
        "--bin", NODE_BIN,
    ] + extra_args
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd="/opt/maelstrom",
    )
    return result


def test_node_exists_and_executable():
    """The node binary must exist and be executable."""
    assert os.path.isfile(NODE_BIN), f"Node binary not found at {NODE_BIN}"
    assert os.access(NODE_BIN, os.X_OK), f"{NODE_BIN} is not executable"


def test_single_node():
    """Single-node basic correctness: init + txn handling."""
    result = run_maelstrom([
        "--node-count", "1",
        "--time-limit", "5",
        "--rate", "500",
        "--concurrency", "2n",
    ], timeout=90)
    output = result.stdout + result.stderr
    assert result.returncode == 0, (
        f"Single-node test failed (exit {result.returncode}):\n"
        f"{output[-3000:]}"
    )


def test_multi_node_read_committed():
    """Multi-node read-committed consistency without network faults."""
    result = run_maelstrom([
        "--node-count", "2",
        "--time-limit", "8",
        "--rate", "500",
        "--concurrency", "2n",
        "--consistency-models", "read-committed",
    ], timeout=90)
    output = result.stdout + result.stderr
    assert result.returncode == 0, (
        f"Multi-node read-committed test failed (exit {result.returncode}):\n"
        f"{output[-3000:]}"
    )


def test_multi_node_partitions_total_availability():
    """Multi-node read-committed with total availability under network partitions."""
    result = run_maelstrom([
        "--node-count", "2",
        "--time-limit", "10",
        "--rate", "500",
        "--concurrency", "2n",
        "--consistency-models", "read-committed",
        "--availability", "total",
        "--nemesis", "partition",
    ], timeout=120)
    output = result.stdout + result.stderr
    assert result.returncode == 0, (
        f"Partition + total availability test failed (exit {result.returncode}):\n"
        f"{output[-3000:]}"
    )
