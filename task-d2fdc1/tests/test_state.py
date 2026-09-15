"""
Tests for the graph scheduling cost model evaluator with asymmetric bandwidth.
Verifies against all worked examples from the specification.

"""

import json
import os
import subprocess
import tempfile
import pytest

EVALUATOR = "/app/evaluate.py"

# ─── Problem definitions from the spec ─────────────────────────────────────

PROBLEM_1 = {
    "widths": [128, 128, 128],
    "heights": [128, 128, 128],
    "inputs": [[0], [1]],
    "outputs": [[1], [2]],
    "base_costs": [1000, 100],
    "op_types": ["Pointwise", "Pointwise"],
    "fast_memory_capacity": 35000,
    "slow_memory_read_bandwidth": 10,
    "slow_memory_write_bandwidth": 8,
    "transition_cost": 100,
    "native_granularity": [128, 128]
}

PROBLEM_2 = {
    "widths": [256, 256, 256],
    "heights": [256, 256, 256],
    "inputs": [[0], [1]],
    "outputs": [[1], [2]],
    "base_costs": [1000, 100],
    "op_types": ["Pointwise", "Pointwise"],
    "fast_memory_capacity": 35000,
    "slow_memory_read_bandwidth": 10,
    "slow_memory_write_bandwidth": 8,
    "transition_cost": 100,
    "native_granularity": [128, 128]
}

PROBLEM_3 = {
    "widths": [128, 128, 128, 128],
    "heights": [128, 128, 128, 128],
    "inputs": [[0], [1], [1, 2]],
    "outputs": [[1], [2], [3]],
    "base_costs": [1500, 1500, 1500],
    "op_types": ["Pointwise", "Pointwise", "Pointwise"],
    "fast_memory_capacity": 50000,
    "slow_memory_read_bandwidth": 10,
    "slow_memory_write_bandwidth": 8,
    "transition_cost": 100,
    "native_granularity": [128, 128]
}

PROBLEM_4 = {
    "widths": [128, 128, 128],
    "heights": [128, 128, 128],
    "inputs": [[0, 1]],
    "outputs": [[2]],
    "base_costs": [1500],
    "op_types": ["MatMul"],
    "fast_memory_capacity": 25000,
    "slow_memory_read_bandwidth": 10,
    "slow_memory_write_bandwidth": 8,
    "transition_cost": 100,
    "native_granularity": [128, 128]
}

PROBLEM_5 = {
    "widths": [128, 128, 128, 128, 128],
    "heights": [128, 128, 128, 128, 128],
    "inputs": [[0, 1], [3, 2]],
    "outputs": [[3], [4]],
    "base_costs": [2000, 2000],
    "op_types": ["MatMul", "MatMul"],
    "fast_memory_capacity": 45000,
    "slow_memory_read_bandwidth": 10,
    "slow_memory_write_bandwidth": 8,
    "transition_cost": 100,
    "native_granularity": [128, 128]
}

PROBLEM_6 = {
    "widths": [128, 128, 128, 128],
    "heights": [128, 128, 128, 128],
    "inputs": [[0, 1], [2]],
    "outputs": [[2], [3]],
    "base_costs": [1800, 600],
    "op_types": ["MatMul", "Pointwise"],
    "fast_memory_capacity": 40000,
    "slow_memory_read_bandwidth": 10,
    "slow_memory_write_bandwidth": 8,
    "transition_cost": 75,
    "native_granularity": [128, 128]
}


def run_evaluator(problem, solution):
    """Run the evaluator and return (stdout, exit_code)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        prob_path = os.path.join(tmpdir, "problem.json")
        sol_path = os.path.join(tmpdir, "solution.json")
        with open(prob_path, "w") as f:
            json.dump(problem, f)
        with open(sol_path, "w") as f:
            json.dump(solution, f)
        result = subprocess.run(
            ["python3", EVALUATOR, prob_path, sol_path],
            capture_output=True, text=True, timeout=30
        )
        return result.stdout.strip(), result.returncode


# ─── Example 1: Baseline (two Pointwise ops, 128x128 tensors) ──────────────

class TestExample1:
    """Example 1: Two chained Pointwise ops on 128x128 tensors."""

    def test_strategy_a_always_spill(self):
        """Strategy A: Each op in its own subgraph, always spill. Total = 3686.4+100+3686.4 = 7472.8"""
        solution = {
            "subgraphs": [[0], [1]],
            "granularities": [[128, 128, 1], [128, 128, 1]],
            "tensors_to_retain": [[], []],
            "traversal_orders": [None, None],
            "subgraph_latencies": [3686.4, 3686.4]
        }
        out, rc = run_evaluator(PROBLEM_1, solution)
        assert rc == 0
        assert abs(float(out) - 7472.8) < 0.01

    def test_strategy_b_mega_group_large(self):
        """Strategy B: Fuse both ops, 128x128 granularity. Single subgraph = 3686.4"""
        solution = {
            "subgraphs": [[0, 1]],
            "granularities": [[128, 128, 1]],
            "tensors_to_retain": [[]],
            "traversal_orders": [None],
            "subgraph_latencies": [3686.4]
        }
        out, rc = run_evaluator(PROBLEM_1, solution)
        assert rc == 0
        assert abs(float(out) - 3686.4) < 0.01

    def test_strategy_c_mega_group_small(self):
        """Strategy C: Fuse both ops, 64x64 granularity (compute-bound). 4*1100 = 4400"""
        solution = {
            "subgraphs": [[0, 1]],
            "granularities": [[64, 64, 1]],
            "tensors_to_retain": [[]],
            "traversal_orders": [None],
            "subgraph_latencies": [4400.0]
        }
        out, rc = run_evaluator(PROBLEM_1, solution)
        assert rc == 0
        assert abs(float(out) - 4400.0) < 0.01


# ─── Example 2: Larger Tensors (256x256) ───────────────────────────────────

class TestExample2:
    """Example 2: Same structure as Example 1 but with 256x256 tensors."""

    def test_strategy_a_always_spill(self):
        """Strategy A: Each op alone, multiple spatial tiles. 14745.6+100+14745.6 = 29591.2"""
        solution = {
            "subgraphs": [[0], [1]],
            "granularities": [[128, 128, 1], [128, 128, 1]],
            "tensors_to_retain": [[], []],
            "traversal_orders": [None, None],
            "subgraph_latencies": [14745.6, 14745.6]
        }
        out, rc = run_evaluator(PROBLEM_2, solution)
        assert rc == 0
        assert abs(float(out) - 29591.2) < 0.01

    def test_strategy_b_mega_group(self):
        """Strategy B: Fuse ops, 128x128 granularity. Single subgraph = 14745.6"""
        solution = {
            "subgraphs": [[0, 1]],
            "granularities": [[128, 128, 1]],
            "tensors_to_retain": [[]],
            "traversal_orders": [None],
            "subgraph_latencies": [14745.6]
        }
        out, rc = run_evaluator(PROBLEM_2, solution)
        assert rc == 0
        assert abs(float(out) - 14745.6) < 0.01


# ─── Example 3: Diamond graph with skip connection ─────────────────────────

class TestExample3:
    """Example 3: Diamond graph. Tensor1 consumed by two downstream ops."""

    def test_strategy_a_spilling(self):
        """Strategy A: All separate, spill everything. 3686.4+100+3686.4+100+5324.8 = 12897.6"""
        solution = {
            "subgraphs": [[0], [1], [2]],
            "granularities": [[128, 128, 1], [128, 128, 1], [128, 128, 1]],
            "tensors_to_retain": [[], [], []],
            "traversal_orders": [None, None, None],
            "subgraph_latencies": [3686.4, 3686.4, 5324.8]
        }
        out, rc = run_evaluator(PROBLEM_3, solution)
        assert rc == 0
        assert abs(float(out) - 12897.6) < 0.01

    def test_strategy_b_recomputation(self):
        """Strategy B: Recompute Op0 in both subgraphs (Flash approach). 3000+100+3686.4 = 6786.4"""
        solution = {
            "subgraphs": [[0, 1], [0, 2]],
            "granularities": [[128, 128, 1], [128, 128, 1]],
            "tensors_to_retain": [[2], []],
            "traversal_orders": [None, None],
            "subgraph_latencies": [3000, 3686.4]
        }
        out, rc = run_evaluator(PROBLEM_3, solution)
        assert rc == 0
        assert abs(float(out) - 6786.4) < 0.01

    def test_strategy_c_selective_residency(self):
        """Strategy C: Keep Tensor1 resident (Hybrid approach). 1638.4+100+3000 = 4738.4"""
        solution = {
            "subgraphs": [[0], [1, 2]],
            "granularities": [[128, 128, 1], [128, 128, 1]],
            "tensors_to_retain": [[1], []],
            "traversal_orders": [None, None],
            "subgraph_latencies": [1638.4, 3000]
        }
        out, rc = run_evaluator(PROBLEM_3, solution)
        assert rc == 0
        assert abs(float(out) - 4738.4) < 0.01


# ─── Example 4: MatMul with traversal order optimization ───────────────────

class TestExample4:
    """Example 4: Single MatMul, optimizing traversal order for data reuse."""

    def test_strategy_a_raster_traversal(self):
        """Strategy A: Default raster order. 2150.4+1500+2150.4+1500 = 7300.8"""
        solution = {
            "subgraphs": [[0]],
            "granularities": [[64, 64, 128]],
            "tensors_to_retain": [[]],
            "traversal_orders": [None],
            "subgraph_latencies": [7300.8]
        }
        out, rc = run_evaluator(PROBLEM_4, solution)
        assert rc == 0
        assert abs(float(out) - 7300.8) < 0.01

    def test_strategy_b_zigzag_traversal(self):
        """Strategy B: Zigzag order maximizes data reuse. 2150.4+1500+1500+1500 = 6650.4"""
        solution = {
            "subgraphs": [[0]],
            "granularities": [[64, 64, 128]],
            "tensors_to_retain": [[]],
            "traversal_orders": [[0, 1, 3, 2]],
            "subgraph_latencies": [6650.4]
        }
        out, rc = run_evaluator(PROBLEM_4, solution)
        assert rc == 0
        assert abs(float(out) - 6650.4) < 0.01


# ─── Example 5: Chained MatMul with Split-K ────────────────────────────────

class TestExample5:
    """Example 5: Chained MatMul (A @ B) @ C, Split-K pipelining."""

    def test_strategy_a_oom(self):
        """Strategy A: Full reduction k=128 causes OOM (working set 49152 > 45000)."""
        solution = {
            "subgraphs": [[0, 1]],
            "granularities": [[128, 128, 128]],
            "tensors_to_retain": [[]],
            "traversal_orders": [None],
            "subgraph_latencies": [0]
        }
        out, rc = run_evaluator(PROBLEM_5, solution)
        assert rc == 1
        assert "OOM" in out.upper() or rc != 0

    def test_strategy_b_split_k(self):
        """Strategy B: Split-K k=32, intermediate ephemeral. 2457.6+1000+1000+2867.2 = 7324.8"""
        solution = {
            "subgraphs": [[0, 1]],
            "granularities": [[128, 128, 32]],
            "tensors_to_retain": [[]],
            "traversal_orders": [None],
            "subgraph_latencies": [7324.8]
        }
        out, rc = run_evaluator(PROBLEM_5, solution)
        assert rc == 0
        assert abs(float(out) - 7324.8) < 0.01


# ─── Example 6: MatMul with Retention and Transition ──────────────────────

class TestExample6:
    """Example 6: MatMul + Pointwise, retention across subgraphs, transition_cost=75."""

    def test_strategy_a_oom(self):
        """Strategy A: Full [128,128,128] granularity causes OOM (49152 > 40000)."""
        solution = {
            "subgraphs": [[0]],
            "granularities": [[128, 128, 128]],
            "tensors_to_retain": [[]],
            "traversal_orders": [None],
            "subgraph_latencies": [0]
        }
        out, rc = run_evaluator(PROBLEM_6, solution)
        assert rc == 1
        assert "OOM" in out.upper() or rc != 0

    def test_strategy_b_retain(self):
        """Strategy B: Tiled MatMul retaining Tensor2. 7200+75+2048.0 = 9323.0"""
        solution = {
            "subgraphs": [[0], [1]],
            "granularities": [[64, 64, 128], [128, 128, 1]],
            "tensors_to_retain": [[2], []],
            "traversal_orders": [None, None],
            "subgraph_latencies": [7200, 2048.0]
        }
        out, rc = run_evaluator(PROBLEM_6, solution)
        assert rc == 0
        assert abs(float(out) - 9323.0) < 0.01

    def test_strategy_c_no_retain(self):
        """Strategy C: Tiled MatMul without retention. 7900.8+75+3686.4 = 11662.2"""
        solution = {
            "subgraphs": [[0], [1]],
            "granularities": [[64, 64, 128], [128, 128, 1]],
            "tensors_to_retain": [[], []],
            "traversal_orders": [None, None],
            "subgraph_latencies": [7900.8, 3686.4]
        }
        out, rc = run_evaluator(PROBLEM_6, solution)
        assert rc == 0
        assert abs(float(out) - 11662.2) < 0.01


# ─── Additional structural tests ───────────────────────────────────────────

class TestStructural:
    """Tests for structural correctness of the evaluator."""

    def test_evaluator_exists(self):
        """The evaluator script must exist at /app/evaluate.py."""
        assert os.path.isfile(EVALUATOR), f"{EVALUATOR} not found"

    def test_evaluator_is_executable_python(self):
        """The evaluator must be runnable with python3."""
        result = subprocess.run(
            ["python3", "-c", f"import importlib.util; spec = importlib.util.spec_from_file_location('eval', '{EVALUATOR}'); assert spec is not None"],
            capture_output=True, text=True
        )
        assert result.returncode == 0

    def test_returns_float_output(self):
        """Output must be parseable as a float for valid solutions."""
        solution = {
            "subgraphs": [[0], [1]],
            "granularities": [[128, 128, 1], [128, 128, 1]],
            "tensors_to_retain": [[], []],
            "traversal_orders": [None, None],
            "subgraph_latencies": [3686.4, 3686.4]
        }
        out, rc = run_evaluator(PROBLEM_1, solution)
        assert rc == 0
        val = float(out)
        assert val > 0

    def test_oom_returns_nonzero(self):
        """OOM solutions must return non-zero exit code."""
        solution = {
            "subgraphs": [[0, 1]],
            "granularities": [[128, 128, 128]],
            "tensors_to_retain": [[]],
            "traversal_orders": [None],
            "subgraph_latencies": [0]
        }
        _, rc = run_evaluator(PROBLEM_5, solution)
        assert rc != 0

    def test_traversal_order_affects_latency(self):
        """Different traversal orders on same problem should give different latencies."""
        sol_raster = {
            "subgraphs": [[0]],
            "granularities": [[64, 64, 128]],
            "tensors_to_retain": [[]],
            "traversal_orders": [None],
            "subgraph_latencies": [7300.8]
        }
        sol_zigzag = {
            "subgraphs": [[0]],
            "granularities": [[64, 64, 128]],
            "tensors_to_retain": [[]],
            "traversal_orders": [[0, 1, 3, 2]],
            "subgraph_latencies": [6650.4]
        }
        out1, _ = run_evaluator(PROBLEM_4, sol_raster)
        out2, _ = run_evaluator(PROBLEM_4, sol_zigzag)
        assert float(out1) > float(out2), "Zigzag should be faster than raster"

    def test_fusion_reduces_latency(self):
        """Fusing ops should reduce latency vs separate execution (includes transition cost)."""
        sol_separate = {
            "subgraphs": [[0], [1]],
            "granularities": [[128, 128, 1], [128, 128, 1]],
            "tensors_to_retain": [[], []],
            "traversal_orders": [None, None],
            "subgraph_latencies": [3686.4, 3686.4]
        }
        sol_fused = {
            "subgraphs": [[0, 1]],
            "granularities": [[128, 128, 1]],
            "tensors_to_retain": [[]],
            "traversal_orders": [None],
            "subgraph_latencies": [3686.4]
        }
        out1, _ = run_evaluator(PROBLEM_1, sol_separate)
        out2, _ = run_evaluator(PROBLEM_1, sol_fused)
        assert float(out1) > float(out2), "Fusion should reduce total latency"

    def test_retention_reduces_latency(self):
        """Retaining a tensor should reduce latency when it avoids a reload."""
        sol_no_retain = {
            "subgraphs": [[0], [1], [2]],
            "granularities": [[128, 128, 1], [128, 128, 1], [128, 128, 1]],
            "tensors_to_retain": [[], [], []],
            "traversal_orders": [None, None, None],
            "subgraph_latencies": [3686.4, 3686.4, 5324.8]
        }
        sol_retain = {
            "subgraphs": [[0], [1, 2]],
            "granularities": [[128, 128, 1], [128, 128, 1]],
            "tensors_to_retain": [[1], []],
            "traversal_orders": [None, None],
            "subgraph_latencies": [1638.4, 3000]
        }
        out1, _ = run_evaluator(PROBLEM_3, sol_no_retain)
        out2, _ = run_evaluator(PROBLEM_3, sol_retain)
        assert float(out1) > float(out2), "Retention should reduce total latency"

    def test_transition_cost_scales_with_subgraphs(self):
        """More subgraphs means more transition costs."""
        sol_1sg = {
            "subgraphs": [[0, 1]],
            "granularities": [[128, 128, 1]],
            "tensors_to_retain": [[]],
            "traversal_orders": [None],
            "subgraph_latencies": [3686.4]
        }
        sol_2sg = {
            "subgraphs": [[0], [1]],
            "granularities": [[128, 128, 1], [128, 128, 1]],
            "tensors_to_retain": [[], []],
            "traversal_orders": [None, None],
            "subgraph_latencies": [3686.4, 3686.4]
        }
        out1, _ = run_evaluator(PROBLEM_1, sol_1sg)
        out2, _ = run_evaluator(PROBLEM_1, sol_2sg)
        lat1 = float(out1)
        lat2 = float(out2)
        # 2 subgraphs adds 1 transition cost (100), plus extra memory transfers
        assert lat2 - lat1 >= 100, "Two subgraphs should cost at least one transition_cost more"

    def test_asymmetric_bandwidth_direction(self):
        """Write bandwidth (8) is slower than read bandwidth (10), so eviction dominates reads."""
        # For a single pointwise op: read=16384/10=1638.4, write=16384/8=2048.0
        # mem_time = 1638.4 + 2048.0 = 3686.4 (not 2*1638.4=3276.8 with symmetric bw=10)
        solution = {
            "subgraphs": [[0]],
            "granularities": [[128, 128, 1]],
            "tensors_to_retain": [[]],
            "traversal_orders": [None],
            "subgraph_latencies": [3686.4]
        }
        out, rc = run_evaluator(PROBLEM_1, solution)
        assert rc == 0
        lat = float(out)
        # If bandwidth were symmetric at 10, result would be 3276.8
        # With asymmetric (read=10, write=8), result should be 3686.4
        assert abs(lat - 3686.4) < 0.01, f"Expected 3686.4 with asymmetric bandwidth, got {lat}"
