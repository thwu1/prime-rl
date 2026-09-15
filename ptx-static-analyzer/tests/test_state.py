
"""Tests for PTX kernel static analyzer.

Verifies CFG construction, register liveness (iterative dataflow),
register pressure, dependency analysis, critical path, and ILP
across two hand-written PTX kernels and one compiler-generated kernel.
"""

import subprocess
import json
import pytest


def run_analyzer(ptx_file):
    """Run the PTX analyzer and return parsed JSON output."""
    result = subprocess.run(
        ["python3", "/app/ptx_analyzer.py", ptx_file],
        capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, (
        f"Analyzer exited with code {result.returncode}.\n"
        f"stderr: {result.stderr}\nstdout: {result.stdout}"
    )
    return json.loads(result.stdout)


# ── vecadd.ptx ──────────────────────────────────────────────────────
# 3 BBs: BB0 (entry + conditional skip), BB_COMPUTE (vector add), BB_EXIT (ret)
# Linear flow with one conditional branch.

class TestVecaddStructure:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.r = run_analyzer("/app/kernels/vecadd.ptx")

    def test_kernel_name(self):
        assert self.r["kernel_name"] == "vecadd"

    def test_num_basic_blocks(self):
        assert self.r["num_basic_blocks"] == 3

    def test_cfg_edges(self):
        edges = set(tuple(e) for e in self.r["cfg_edges"])
        expected = {
            ("BB0", "BB_EXIT"),
            ("BB0", "BB_COMPUTE"),
            ("BB_COMPUTE", "BB_EXIT"),
        }
        assert edges == expected

    def test_bb0_instruction_count(self):
        assert self.r["basic_blocks"]["BB0"]["num_instructions"] == 10

    def test_bb_compute_instruction_count(self):
        assert self.r["basic_blocks"]["BB_COMPUTE"]["num_instructions"] == 8

    def test_bb_exit_instruction_count(self):
        assert self.r["basic_blocks"]["BB_EXIT"]["num_instructions"] == 1


class TestVecaddLiveness:
    """Liveness for vecadd — no loops, single-pass convergence expected."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.r = run_analyzer("/app/kernels/vecadd.ptx")

    def test_bb0_live_in_empty(self):
        # Entry block: all registers are defined here, none flow in.
        assert sorted(self.r["basic_blocks"]["BB0"]["live_in"]) == []

    def test_bb0_live_out(self):
        # %r1 (global index), %rd0/%rd1/%rd2 (pointers) flow to BB_COMPUTE.
        assert sorted(self.r["basic_blocks"]["BB0"]["live_out"]) == [
            "%r1", "%rd0", "%rd1", "%rd2"
        ]

    def test_bb_compute_live_in(self):
        assert sorted(self.r["basic_blocks"]["BB_COMPUTE"]["live_in"]) == [
            "%r1", "%rd0", "%rd1", "%rd2"
        ]

    def test_bb_compute_live_out_empty(self):
        # No registers flow out of the compute block (all consumed locally).
        assert sorted(self.r["basic_blocks"]["BB_COMPUTE"]["live_out"]) == []

    def test_bb_exit_live_in_empty(self):
        assert sorted(self.r["basic_blocks"]["BB_EXIT"]["live_in"]) == []

    def test_bb_exit_live_out_empty(self):
        assert sorted(self.r["basic_blocks"]["BB_EXIT"]["live_out"]) == []


class TestVecaddPressure:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.r = run_analyzer("/app/kernels/vecadd.ptx")

    def test_bb0_pressure(self):
        # Peak at mad instruction: %rd0-%rd2, %r0-%r3 = 7 regs live.
        assert self.r["basic_blocks"]["BB0"]["max_register_pressure"] == 7

    def test_bb_compute_pressure(self):
        # Peak at add.u64 %rd6: %rd0-%rd3 still live or %rd3-%rd5 + incoming.
        assert self.r["basic_blocks"]["BB_COMPUTE"]["max_register_pressure"] == 4

    def test_bb_exit_pressure(self):
        assert self.r["basic_blocks"]["BB_EXIT"]["max_register_pressure"] == 0


class TestVecaddCriticalPath:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.r = run_analyzer("/app/kernels/vecadd.ptx")

    def test_bb0_critical_path(self):
        # Longest chain: mov %r1 -> mad %r1 -> setp %p0 -> @%p0 bra = 4
        assert self.r["basic_blocks"]["BB0"]["critical_path_length"] == 4

    def test_bb0_ilp(self):
        # 10 instructions / 4 critical path = 2.5
        assert abs(self.r["basic_blocks"]["BB0"]["ilp"] - 2.5) < 0.01

    def test_bb_compute_critical_path(self):
        # mul -> add %rd4 -> ld %f0 -> add %f2 -> st = 5
        # (or mul -> add %rd5 -> ld %f1 -> add %f2 -> st = 5)
        assert self.r["basic_blocks"]["BB_COMPUTE"]["critical_path_length"] == 5

    def test_bb_compute_ilp(self):
        # 8 / 5 = 1.6
        assert abs(self.r["basic_blocks"]["BB_COMPUTE"]["ilp"] - 1.6) < 0.01

    def test_bb_exit_critical_path(self):
        # Single ret instruction.
        assert self.r["basic_blocks"]["BB_EXIT"]["critical_path_length"] == 1


# ── reduce.ptx ──────────────────────────────────────────────────────
# 6 BBs with a loop: BB_ENTRY -> BB_LOOP_HEAD <-> BB_LOOP_BODY
#                                BB_LOOP_HEAD -> BB_DONE -> BB_STORE -> BB_EXIT
# The loop back-edge requires iterative dataflow convergence for liveness.

class TestReduceStructure:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.r = run_analyzer("/app/kernels/reduce.ptx")

    def test_kernel_name(self):
        assert self.r["kernel_name"] == "reduce_sum"

    def test_num_basic_blocks(self):
        assert self.r["num_basic_blocks"] == 6

    def test_cfg_edges(self):
        edges = set(tuple(e) for e in self.r["cfg_edges"])
        expected = {
            ("BB_ENTRY", "BB_LOOP_HEAD"),
            ("BB_LOOP_HEAD", "BB_DONE"),
            ("BB_LOOP_HEAD", "BB_LOOP_BODY"),
            ("BB_LOOP_BODY", "BB_LOOP_HEAD"),
            ("BB_DONE", "BB_EXIT"),
            ("BB_DONE", "BB_STORE"),
            ("BB_STORE", "BB_EXIT"),
        }
        assert edges == expected

    def test_bb_entry_instruction_count(self):
        assert self.r["basic_blocks"]["BB_ENTRY"]["num_instructions"] == 6

    def test_bb_loop_head_instruction_count(self):
        assert self.r["basic_blocks"]["BB_LOOP_HEAD"]["num_instructions"] == 2

    def test_bb_loop_body_instruction_count(self):
        assert self.r["basic_blocks"]["BB_LOOP_BODY"]["num_instructions"] == 6

    def test_bb_done_instruction_count(self):
        assert self.r["basic_blocks"]["BB_DONE"]["num_instructions"] == 2

    def test_bb_store_instruction_count(self):
        assert self.r["basic_blocks"]["BB_STORE"]["num_instructions"] == 1

    def test_bb_exit_instruction_count(self):
        assert self.r["basic_blocks"]["BB_EXIT"]["num_instructions"] == 1


class TestReduceLiveness:
    """Liveness for reduce — the loop requires iterative convergence.

    After one pass, BB_LOOP_BODY.live_in would only contain {%r2, %rd0, %f0}.
    The back-edge propagates %r0, %r1, %rd1 through BB_LOOP_HEAD into
    BB_LOOP_BODY, requiring a second iteration to reach the fixed point.
    """

    @pytest.fixture(autouse=True)
    def setup(self):
        self.r = run_analyzer("/app/kernels/reduce.ptx")

    def test_entry_live_in_empty(self):
        assert sorted(self.r["basic_blocks"]["BB_ENTRY"]["live_in"]) == []

    def test_entry_live_out(self):
        assert sorted(self.r["basic_blocks"]["BB_ENTRY"]["live_out"]) == [
            "%f0", "%r0", "%r1", "%r2", "%rd0", "%rd1"
        ]

    def test_loop_head_live_in(self):
        # All 6 registers propagated from entry and loop body.
        assert sorted(self.r["basic_blocks"]["BB_LOOP_HEAD"]["live_in"]) == [
            "%f0", "%r0", "%r1", "%r2", "%rd0", "%rd1"
        ]

    def test_loop_head_live_out(self):
        assert sorted(self.r["basic_blocks"]["BB_LOOP_HEAD"]["live_out"]) == [
            "%f0", "%r0", "%r1", "%r2", "%rd0", "%rd1"
        ]

    def test_loop_body_live_in(self):
        # Critical test: without iterative convergence, %r0, %r1, %rd1
        # would be missing. These propagate through the loop back-edge.
        assert sorted(self.r["basic_blocks"]["BB_LOOP_BODY"]["live_in"]) == [
            "%f0", "%r0", "%r1", "%r2", "%rd0", "%rd1"
        ]

    def test_loop_body_live_out(self):
        assert sorted(self.r["basic_blocks"]["BB_LOOP_BODY"]["live_out"]) == [
            "%f0", "%r0", "%r1", "%r2", "%rd0", "%rd1"
        ]

    def test_done_live_in(self):
        # Only %r1 (tid), %rd1 (output ptr), %f0 (accumulated result).
        assert sorted(self.r["basic_blocks"]["BB_DONE"]["live_in"]) == [
            "%f0", "%r1", "%rd1"
        ]

    def test_done_live_out(self):
        assert sorted(self.r["basic_blocks"]["BB_DONE"]["live_out"]) == [
            "%f0", "%rd1"
        ]

    def test_store_live_in(self):
        assert sorted(self.r["basic_blocks"]["BB_STORE"]["live_in"]) == [
            "%f0", "%rd1"
        ]

    def test_store_live_out_empty(self):
        assert sorted(self.r["basic_blocks"]["BB_STORE"]["live_out"]) == []

    def test_exit_live_in_empty(self):
        assert sorted(self.r["basic_blocks"]["BB_EXIT"]["live_in"]) == []


class TestReducePressure:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.r = run_analyzer("/app/kernels/reduce.ptx")

    def test_entry_pressure(self):
        # All 6 registers defined; live_out has 6 regs, peak at the end = 6.
        assert self.r["basic_blocks"]["BB_ENTRY"]["max_register_pressure"] == 6

    def test_loop_head_pressure(self):
        # 6 pass-through regs + %p0 at branch point = 7.
        assert self.r["basic_blocks"]["BB_LOOP_HEAD"]["max_register_pressure"] == 7

    def test_loop_body_pressure(self):
        # 6 pass-through + temporary %rd2/%rd3/%f1 at peak = 7.
        assert self.r["basic_blocks"]["BB_LOOP_BODY"]["max_register_pressure"] == 7

    def test_done_pressure(self):
        # 2 pass-through + %r1 use + %p1 = peak 3.
        assert self.r["basic_blocks"]["BB_DONE"]["max_register_pressure"] == 3

    def test_store_pressure(self):
        assert self.r["basic_blocks"]["BB_STORE"]["max_register_pressure"] == 2

    def test_exit_pressure(self):
        assert self.r["basic_blocks"]["BB_EXIT"]["max_register_pressure"] == 0


class TestReduceCriticalPath:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.r = run_analyzer("/app/kernels/reduce.ptx")

    def test_entry_all_independent(self):
        # 6 independent ld.param/mov instructions — no RAW deps.
        assert self.r["basic_blocks"]["BB_ENTRY"]["critical_path_length"] == 1

    def test_entry_ilp(self):
        # 6 / 1 = 6.0 — all instructions can issue in parallel.
        assert abs(self.r["basic_blocks"]["BB_ENTRY"]["ilp"] - 6.0) < 0.01

    def test_loop_head_critical_path(self):
        # setp -> @%p0 bra = 2
        assert self.r["basic_blocks"]["BB_LOOP_HEAD"]["critical_path_length"] == 2

    def test_loop_body_critical_path(self):
        # mul %rd2 -> add %rd3 -> ld %f1 -> add %f0 = 4
        assert self.r["basic_blocks"]["BB_LOOP_BODY"]["critical_path_length"] == 4

    def test_loop_body_ilp(self):
        # 6 / 4 = 1.5
        assert abs(self.r["basic_blocks"]["BB_LOOP_BODY"]["ilp"] - 1.5) < 0.01

    def test_done_critical_path(self):
        assert self.r["basic_blocks"]["BB_DONE"]["critical_path_length"] == 2

    def test_store_critical_path(self):
        assert self.r["basic_blocks"]["BB_STORE"]["critical_path_length"] == 1


# ── matmul (compiler-generated PTX from LLVM IR) ────────────────────
# Compiled from matmul.ll using llc-18 --march=nvptx64 --mcpu=sm_80.
# Tests verify the analyzer handles compiler-generated PTX correctly.
# Checks structural invariants rather than exact values since llc output
# format may differ from hand-written PTX.

class TestMatmulCompilerGenerated:
    """Tests for compiler-generated PTX from LLVM IR."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.r = run_analyzer("/app/kernels/matmul.ptx")

    def test_kernel_name(self):
        assert self.r["kernel_name"] == "matmul"

    def test_num_basic_blocks(self):
        # LLVM IR has 6 blocks; llc may merge some but structure requires >= 4
        assert self.r["num_basic_blocks"] >= 4

    def test_has_cfg_edges(self):
        assert len(self.r["cfg_edges"]) >= 4

    def test_cfg_has_loop(self):
        """Matmul kernel has a loop — CFG must contain a cycle."""
        edge_set = {(a, b) for a, b in (tuple(e) for e in self.r["cfg_edges"])}
        has_cycle = any((b, a) in edge_set for a, b in edge_set)
        assert has_cycle, "CFG should contain a back-edge (loop)"

    def test_all_blocks_have_required_fields(self):
        required = {"num_instructions", "live_in", "live_out",
                     "max_register_pressure", "critical_path_length", "ilp"}
        for name, bb in self.r["basic_blocks"].items():
            missing = required - set(bb.keys())
            assert not missing, f"Block {name} missing fields: {missing}"

    def test_some_block_empty_live_in(self):
        """Entry block should have empty live_in."""
        assert any(
            bb["live_in"] == [] for bb in self.r["basic_blocks"].values()
        )

    def test_block_with_empty_live_out(self):
        """Exit block (ret) should have empty live_out."""
        assert any(
            bb["live_out"] == [] for bb in self.r["basic_blocks"].values()
        )

    def test_register_naming_convention(self):
        """All register names should follow PTX %prefix convention."""
        for bb in self.r["basic_blocks"].values():
            for reg in bb["live_in"] + bb["live_out"]:
                assert reg.startswith("%"), f"Invalid register name: {reg}"

    def test_pressure_non_negative(self):
        for bb in self.r["basic_blocks"].values():
            assert bb["max_register_pressure"] >= 0

    def test_nontrivial_pressure_exists(self):
        """At least one block should have significant register pressure."""
        assert any(
            bb["max_register_pressure"] >= 4
            for bb in self.r["basic_blocks"].values()
        )

    def test_critical_path_positive(self):
        for bb in self.r["basic_blocks"].values():
            if bb["num_instructions"] > 0:
                assert bb["critical_path_length"] >= 1

    def test_nontrivial_critical_path_exists(self):
        """Loop body should have a meaningful dependency chain."""
        assert any(
            bb["critical_path_length"] >= 3
            for bb in self.r["basic_blocks"].values()
        )

    def test_ilp_bounds(self):
        for bb in self.r["basic_blocks"].values():
            if bb["num_instructions"] > 0:
                assert bb["ilp"] >= 1.0
                assert bb["ilp"] <= bb["num_instructions"]

    def test_liveness_sets_are_lists(self):
        """Liveness sets should be sorted lists of strings."""
        for bb in self.r["basic_blocks"].values():
            assert isinstance(bb["live_in"], list)
            assert isinstance(bb["live_out"], list)
            assert bb["live_in"] == sorted(bb["live_in"])
            assert bb["live_out"] == sorted(bb["live_out"])
