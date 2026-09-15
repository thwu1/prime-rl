
"""
Tests for the IOPDDL graph scheduling optimizer.
Validates that /app/scheduler.py produces valid, optimized schedules
for diverse benchmark problems covering fusion, split-K, traversal,
and retention strategies.
"""

import json
import os
import subprocess
import tempfile

import pytest

SCHEDULER = "/app/scheduler.py"
EVALUATOR = "/app/evaluate.py"
TOLERANCE = 1.0  # absolute tolerance for latency match


def run_scheduler(problem: dict) -> dict:
    """Run the scheduler on a problem, return parsed solution JSON."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(problem, f)
        pf = f.name
    try:
        result = subprocess.run(
            ["python3", SCHEDULER, pf],
            capture_output=True, text=True, timeout=120,
        )
        assert result.returncode == 0, (
            f"Scheduler exited with code {result.returncode}.\n"
            f"stdout: {result.stdout[:500]}\nstderr: {result.stderr[:500]}"
        )
        out = result.stdout.strip()
        assert out, "Scheduler produced empty output"
        return json.loads(out)
    finally:
        os.unlink(pf)


def run_evaluator(problem: dict, solution: dict) -> dict:
    """Run the reference evaluator on a (problem, solution) pair."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as pf:
        json.dump(problem, pf)
        pfp = pf.name
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as sf:
        json.dump(solution, sf)
        sfp = sf.name
    try:
        result = subprocess.run(
            ["python3", EVALUATOR, pfp, sfp],
            capture_output=True, text=True, timeout=60,
        )
        assert result.returncode == 0, (
            f"Evaluator failed: {result.stderr[:500]}"
        )
        return json.loads(result.stdout.strip())
    finally:
        os.unlink(pfp)
        os.unlink(sfp)


def check_solution_fields(solution: dict):
    """Verify the solution has all required fields with correct types."""
    required = ["subgraphs", "granularities", "tensors_to_retain",
                "traversal_orders", "subgraph_latencies"]
    for field in required:
        assert field in solution, f"Missing required field: {field}"
    n = len(solution["subgraphs"])
    assert n > 0, "Solution has no subgraphs"
    assert len(solution["granularities"]) == n
    assert len(solution["tensors_to_retain"]) == n
    assert len(solution["traversal_orders"]) == n
    assert len(solution["subgraph_latencies"]) == n
    for i, g in enumerate(solution["granularities"]):
        assert len(g) == 3, f"Granularity {i} must have 3 elements [w,h,k]"
        assert all(v > 0 for v in g), f"Granularity {i} values must be positive"


def schedule_and_validate(problem: dict, latency_threshold: float):
    """Full pipeline: schedule, validate structure, evaluate, check quality."""
    solution = run_scheduler(problem)
    check_solution_fields(solution)
    eval_result = run_evaluator(problem, solution)
    assert eval_result["valid"] is True, (
        f"Evaluator rejected solution: {eval_result.get('error', 'unknown')}"
    )
    actual_latency = eval_result["total_latency"]
    assert actual_latency <= latency_threshold, (
        f"Latency {actual_latency:.1f} exceeds threshold {latency_threshold:.1f}"
    )
    # Check self-reported latency roughly matches evaluator
    reported = sum(solution["subgraph_latencies"])
    assert abs(reported - actual_latency) < TOLERANCE, (
        f"Reported latency {reported:.1f} != evaluator {actual_latency:.1f}"
    )
    return actual_latency


# ---------------------------------------------------------------------------
# Problem definitions
# ---------------------------------------------------------------------------

# Problem 1: Simple Pointwise chain (spec Example 1)
# Optimal via fusion: 3276.8. Naive (separate): 6553.6.
PROB_SIMPLE_FUSION = {
    "widths": [128, 128, 128],
    "heights": [128, 128, 128],
    "inputs": [[0], [1]],
    "outputs": [[1], [2]],
    "base_costs": [1000, 100],
    "op_types": ["Pointwise", "Pointwise"],
    "fast_memory_capacity": 35000,
    "slow_memory_bandwidth": 10,
    "native_granularity": [128, 128],
}

# Problem 2: Diamond graph with skip connection (spec Example 3)
# Full fusion gives 4500. Retention strategy gives 4638.4. Naive: 11468.8.
PROB_DIAMOND = {
    "widths": [128, 128, 128, 128],
    "heights": [128, 128, 128, 128],
    "inputs": [[0], [1], [1, 2]],
    "outputs": [[1], [2], [3]],
    "base_costs": [1500, 1500, 1500],
    "op_types": ["Pointwise", "Pointwise", "Pointwise"],
    "fast_memory_capacity": 50000,
    "slow_memory_bandwidth": 10,
    "native_granularity": [128, 128],
}

# Problem 3: MatMul requiring sub-native granularity (spec Example 4)
# OOM at native [128,128,128]. Must use [64,64,128].
# Raster: 7096. Zigzag: 6548.
PROB_MATMUL_TILING = {
    "widths": [128, 128, 128],
    "heights": [128, 128, 128],
    "inputs": [[0, 1]],
    "outputs": [[2]],
    "base_costs": [1500],
    "op_types": ["MatMul"],
    "fast_memory_capacity": 25000,
    "slow_memory_bandwidth": 10,
    "native_granularity": [128, 128],
}

# Problem 4: Chained MatMul requiring split-K (spec Example 5)
# Full k=128 → OOM. Split k=64 → 6553.6. Split k=32 → 6915.2.
PROB_SPLIT_K = {
    "widths": [128, 128, 128, 128, 128],
    "heights": [128, 128, 128, 128, 128],
    "inputs": [[0, 1], [3, 2]],
    "outputs": [[3], [4]],
    "base_costs": [2000, 2000],
    "op_types": ["MatMul", "MatMul"],
    "fast_memory_capacity": 45000,
    "slow_memory_bandwidth": 10,
    "native_granularity": [128, 128],
}

# Problem 5: Mixed Pointwise → MatMul → Pointwise chain (NOVEL)
# Full fusion at [128,128,128]: 4915.2. Naive separate: 11468.8.
PROB_MIXED_CHAIN = {
    "widths": [128, 128, 128, 128, 128],
    "heights": [128, 128, 128, 128, 128],
    "inputs": [[0], [1, 2], [3]],
    "outputs": [[1], [3], [4]],
    "base_costs": [500, 2000, 500],
    "op_types": ["Pointwise", "MatMul", "Pointwise"],
    "fast_memory_capacity": 50000,
    "slow_memory_bandwidth": 10,
    "native_granularity": [128, 128],
}

# Problem 6: Long Pointwise chain on 256x256 tensors (NOVEL)
# Full fusion: 13107.2. Pair fusion: 26214.4. Naive: 52428.8.
PROB_LONG_CHAIN = {
    "widths": [256, 256, 256, 256, 256],
    "heights": [256, 256, 256, 256, 256],
    "inputs": [[0], [1], [2], [3]],
    "outputs": [[1], [2], [3], [4]],
    "base_costs": [800, 800, 800, 800],
    "op_types": ["Pointwise", "Pointwise", "Pointwise", "Pointwise"],
    "fast_memory_capacity": 40000,
    "slow_memory_bandwidth": 10,
    "native_granularity": [128, 128],
}


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

class TestSchedulerStructure:
    """Verify scheduler produces well-formed output."""

    def test_output_fields(self):
        """Scheduler output has all required fields with correct types."""
        solution = run_scheduler(PROB_SIMPLE_FUSION)
        check_solution_fields(solution)
        eval_result = run_evaluator(PROB_SIMPLE_FUSION, solution)
        assert eval_result["valid"] is True


class TestPointwiseFusion:
    """Problem 1: Two Pointwise ops, must discover fusion."""

    def test_latency_threshold(self):
        """Fused solution should achieve ≤ 4000 (naive is 6553.6)."""
        schedule_and_validate(PROB_SIMPLE_FUSION, 4000.0)


class TestDiamondGraph:
    """Problem 2: Diamond graph, must discover fusion or retention."""

    def test_latency_threshold(self):
        """Must beat naive (11468.8) significantly. Threshold: 7000."""
        schedule_and_validate(PROB_DIAMOND, 7000.0)


class TestMatMulTiling:
    """Problem 3: MatMul with OOM at native granularity."""

    def test_latency_threshold(self):
        """Must find valid sub-native granularity. Threshold: 7200."""
        schedule_and_validate(PROB_MATMUL_TILING, 7200.0)


class TestSplitK:
    """Problem 4: Chained MatMul requiring split-K to avoid OOM."""

    def test_latency_threshold(self):
        """Must discover split-K. Threshold: 7500."""
        schedule_and_validate(PROB_SPLIT_K, 7500.0)


class TestMixedChain:
    """Problem 5: Pointwise→MatMul→Pointwise (novel, not in benchmarks)."""

    def test_latency_threshold(self):
        """Must fuse the chain. Threshold: 7000."""
        schedule_and_validate(PROB_MIXED_CHAIN, 7000.0)


class TestLongChain:
    """Problem 6: 4-op Pointwise chain on 256x256 (novel)."""

    def test_latency_threshold(self):
        """Must fuse at least pairs. Threshold: 28000."""
        schedule_and_validate(PROB_LONG_CHAIN, 28000.0)
