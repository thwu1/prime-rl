
"""Tests for gradient rematerialization solver.

Verifies correctness of compute_table, reconstruct, and simulate
against golden values and structural invariants. Also verifies that
the C shared library is correctly built and produces correct results.
"""

import sys
import os
import math
import inspect
import ctypes
import pytest

sys.path.insert(0, "/app")

from rematerialization.chain import Chain
from rematerialization.ops import (
    ForwardCheck, ForwardNograd, ForwardEnable, Backward, Loss
)


# ---------------------------------------------------------------------------
# Helper: import solver functions
# ---------------------------------------------------------------------------

def _import_solver():
    from rematerialization.solver import compute_table, reconstruct, simulate
    return compute_table, reconstruct, simulate


# ---------------------------------------------------------------------------
# Test chain fixtures
# ---------------------------------------------------------------------------

def chain1():
    """Length 1, unit sizes."""
    return Chain(
        fw=[1.0], bw=[1.0, 0.0],
        cw=[1, 1], cbw=[1, 1],
        ftmp=[0], btmp=[0, 0],
    )


def chain2():
    """Length 3, heterogeneous sizes and times."""
    return Chain(
        fw=[2.0, 3.0, 1.0], bw=[1.0, 2.0, 1.0, 0.0],
        cw=[2, 3, 1, 2], cbw=[2, 4, 2, 3],
        ftmp=[1, 0, 2], btmp=[0, 1, 0, 0],
    )


def chain3():
    """Length 5, moderate heterogeneity."""
    return Chain(
        fw=[1.0, 2.0, 1.0, 3.0, 2.0],
        bw=[2.0, 1.0, 1.0, 2.0, 1.0, 0.0],
        cw=[1, 2, 1, 3, 2, 1], cbw=[1, 3, 2, 4, 3, 2],
        ftmp=[0, 1, 0, 1, 0], btmp=[1, 0, 1, 0, 1, 0],
    )


def chain4():
    """Length 4, significant temporary memory."""
    return Chain(
        fw=[3.0, 2.0, 4.0, 1.0], bw=[2.0, 3.0, 1.0, 2.0, 0.0],
        cw=[2, 1, 3, 2, 1], cbw=[3, 2, 4, 3, 2],
        ftmp=[2, 1, 3, 0], btmp=[1, 2, 0, 1, 0],
    )


# ---------------------------------------------------------------------------
# Golden values: (chain_func, budget) -> expected_opt
# Computed from reference implementation of the persistent DP.
# ---------------------------------------------------------------------------

GOLDEN_OPT = [
    (chain1, 4, 2.0),
    (chain1, 5, 2.0),
    (chain2, 12, 17.0),
    (chain2, 13, 15.0),
    (chain2, 14, 12.0),
    (chain2, 15, 10.0),
    (chain3, 12, 26.0),
    (chain3, 13, 23.0),
    (chain3, 14, 20.0),
    (chain3, 15, 19.0),
    (chain3, 17, 18.0),
    (chain3, 19, 16.0),
    (chain4, 13, 30.0),
    (chain4, 14, 23.0),
    (chain4, 15, 23.0),
    (chain4, 16, 20.0),
    (chain4, 17, 18.0),
]

# Budgets known to be infeasible
INFEASIBLE = [
    (chain1, 3),
    (chain2, 8),
    (chain2, 10),
    (chain3, 8),
    (chain3, 10),
    (chain4, 10),
    (chain4, 12),
]


# ---------------------------------------------------------------------------
# C Library Tests
# ---------------------------------------------------------------------------

class TestCLibrary:
    """Verify the C shared library is correctly built and functional."""

    def test_so_exists(self):
        assert os.path.exists("/app/rematerialization/dp_core.so"), \
            "dp_core.so must be built at /app/rematerialization/dp_core.so"

    def test_exports_compute_dp(self):
        lib = ctypes.CDLL("/app/rematerialization/dp_core.so")
        fn = lib.compute_dp
        assert fn is not None, "dp_core.so must export compute_dp"

    def _call_c_dp(self, ch, mmax):
        """Helper to call C library directly."""
        lib = ctypes.CDLL("/app/rematerialization/dp_core.so")
        lib.compute_dp.restype = None
        lib.compute_dp.argtypes = [
            ctypes.c_int, ctypes.c_int,
            ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_double),
            ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_int),
        ]

        n = ch.length
        s = n + 1
        total = (mmax + 1) * s * s

        fw_list = list(ch.fweigth) + [0.0]
        bw_list = list(ch.bweigth)
        cw_list = list(ch.cweigth) + [0]
        cbw_list = list(ch.cbweigth) + [0]
        ftmp_list = list(ch.fwd_tmp) + [0]
        btmp_list = list(ch.bwd_tmp)

        fw = (ctypes.c_double * len(fw_list))(*fw_list)
        bw = (ctypes.c_double * len(bw_list))(*bw_list)
        cw = (ctypes.c_int * len(cw_list))(*cw_list)
        cbw = (ctypes.c_int * len(cbw_list))(*cbw_list)
        ftmp = (ctypes.c_int * len(ftmp_list))(*ftmp_list)
        btmp = (ctypes.c_int * len(btmp_list))(*btmp_list)

        opt_arr = (ctypes.c_double * total)()
        wtype_arr = (ctypes.c_int * total)()
        wj_arr = (ctypes.c_int * total)()

        lib.compute_dp(n, mmax, fw, bw, cw, cbw, ftmp, btmp,
                       opt_arr, wtype_arr, wj_arr)
        return opt_arr, s

    @pytest.mark.parametrize("chain_fn, budget, expected", [
        (chain2, 15, 10.0),
        (chain3, 19, 16.0),
        (chain4, 17, 18.0),
    ])
    def test_c_golden_values(self, chain_fn, budget, expected):
        """Directly test C library output against golden values."""
        ch = chain_fn()
        opt_arr, s = self._call_c_dp(ch, budget)
        cmem = budget - ch.cweigth[0]
        idx = cmem * s * s + 0 * s + ch.length
        actual = opt_arr[idx]
        assert abs(actual - expected) < 1e-9, \
            f"C library opt[{cmem}][0][{ch.length}] = {actual}, expected {expected}"

    def test_solver_uses_ctypes(self):
        """Verify solver.py imports and uses ctypes with dp_core."""
        from rematerialization import solver
        source = inspect.getsource(solver)
        assert "ctypes" in source, "solver.py must use ctypes"
        assert "dp_core" in source, "solver.py must reference dp_core"


# ---------------------------------------------------------------------------
# Python API Tests
# ---------------------------------------------------------------------------

class TestImport:
    """Verify that the solver module is importable and has the required API."""

    def test_import_solver(self):
        compute_table, reconstruct, simulate = _import_solver()
        assert callable(compute_table)
        assert callable(reconstruct)
        assert callable(simulate)


class TestComputeTable:
    """Verify DP table correctness against golden values."""

    @pytest.mark.parametrize("chain_fn, budget, expected_opt", GOLDEN_OPT)
    def test_opt_golden(self, chain_fn, budget, expected_opt):
        compute_table, _, _ = _import_solver()
        ch = chain_fn()
        opt, what = compute_table(ch, budget)
        cmem = budget - ch.cweigth[0]
        actual = opt[cmem][0][ch.length]
        assert abs(actual - expected_opt) < 1e-9, (
            f"opt[{cmem}][0][{ch.length}] = {actual}, expected {expected_opt}"
        )

    @pytest.mark.parametrize("chain_fn, budget", INFEASIBLE)
    def test_opt_infeasible(self, chain_fn, budget):
        compute_table, _, _ = _import_solver()
        ch = chain_fn()
        opt, _ = compute_table(ch, budget)
        cmem = budget - ch.cweigth[0]
        val = opt[cmem][0][ch.length]
        assert val == float("inf"), (
            f"Expected inf for budget {budget}, got {val}"
        )

    @pytest.mark.parametrize("chain_fn", [chain1, chain2, chain3, chain4])
    def test_monotonicity(self, chain_fn):
        """opt[m][0][n] must be non-increasing in m."""
        compute_table, _, _ = _import_solver()
        ch = chain_fn()
        budget = 30
        opt, _ = compute_table(ch, budget)
        prev = float("inf")
        for m in range(budget + 1):
            val = opt[m][0].get(ch.length, float("inf"))
            assert val <= prev + 1e-9, (
                f"Monotonicity violation: opt[{m}] = {val} > opt[{m-1}] = {prev}"
            )
            prev = val

    @pytest.mark.parametrize("chain_fn", [chain1, chain2, chain3, chain4])
    def test_converges_to_no_recomputation(self, chain_fn):
        """With large enough budget, makespan = sum(fw) + sum(bw)."""
        compute_table, _, _ = _import_solver()
        ch = chain_fn()
        no_recomp = sum(ch.fweigth) + sum(ch.bweigth)
        budget = 50
        opt, _ = compute_table(ch, budget)
        cmem = budget - ch.cweigth[0]
        actual = opt[cmem][0][ch.length]
        assert abs(actual - no_recomp) < 1e-9, (
            f"At high budget, expected {no_recomp}, got {actual}"
        )

    @pytest.mark.parametrize("chain_fn", [chain1, chain2, chain3, chain4])
    def test_base_case_loss(self, chain_fn):
        """opt[m][n][n] = 0 for large enough m (loss operation)."""
        compute_table, _, _ = _import_solver()
        ch = chain_fn()
        budget = 30
        opt, _ = compute_table(ch, budget)
        n = ch.length
        for m in range(budget + 1):
            val = opt[m][n].get(n, float("inf"))
            if val < float("inf"):
                assert abs(val) < 1e-9, (
                    f"opt[{m}][{n}][{n}] = {val}, expected 0"
                )


class TestReconstruct:
    """Verify sequence reconstruction from DP tables."""

    @pytest.mark.parametrize("chain_fn, budget, expected_opt", GOLDEN_OPT)
    def test_makespan_matches_opt(self, chain_fn, budget, expected_opt):
        compute_table, reconstruct, _ = _import_solver()
        ch = chain_fn()
        opt_table = compute_table(ch, budget)
        cmem = budget - ch.cweigth[0]
        ops = reconstruct(ch, 0, ch.length, cmem, opt_table)

        # Compute makespan
        fw = ch.fweigth + [0]
        bw = ch.bweigth
        mk = 0.0
        for op in ops:
            if isinstance(op, (ForwardCheck, ForwardNograd, ForwardEnable)):
                mk += fw[op.index]
            elif isinstance(op, Backward):
                mk += bw[op.index]
        assert abs(mk - expected_opt) < 1e-9, (
            f"Makespan {mk} != opt {expected_opt}"
        )

    @pytest.mark.parametrize("chain_fn, budget, _", GOLDEN_OPT)
    def test_sequence_covers_all_layers(self, chain_fn, budget, _):
        """The sequence must backward all layers from n-1 down to 0."""
        compute_table, reconstruct, _ = _import_solver()
        ch = chain_fn()
        opt_table = compute_table(ch, budget)
        cmem = budget - ch.cweigth[0]
        ops = reconstruct(ch, 0, ch.length, cmem, opt_table)

        backward_indices = sorted(
            op.index for op in ops if isinstance(op, Backward)
        )
        assert backward_indices == list(range(ch.length)), (
            f"Missing backward ops. Got {backward_indices}, "
            f"expected {list(range(ch.length))}"
        )

    @pytest.mark.parametrize("chain_fn, budget, _", GOLDEN_OPT)
    def test_sequence_has_exactly_one_loss(self, chain_fn, budget, _):
        compute_table, reconstruct, _ = _import_solver()
        ch = chain_fn()
        opt_table = compute_table(ch, budget)
        cmem = budget - ch.cweigth[0]
        ops = reconstruct(ch, 0, ch.length, cmem, opt_table)

        loss_count = sum(1 for op in ops if isinstance(op, Loss))
        assert loss_count == 1, f"Expected 1 Loss, got {loss_count}"


class TestSimulate:
    """Verify memory simulation."""

    @pytest.mark.parametrize("chain_fn, budget, _", GOLDEN_OPT)
    def test_peak_within_budget(self, chain_fn, budget, _):
        compute_table, reconstruct, simulate = _import_solver()
        ch = chain_fn()
        opt_table = compute_table(ch, budget)
        cmem = budget - ch.cweigth[0]
        ops = reconstruct(ch, 0, ch.length, cmem, opt_table)
        peak = simulate(ops, ch)
        assert peak <= budget, (
            f"Peak memory {peak} exceeds budget {budget}"
        )

    @pytest.mark.parametrize("chain_fn", [chain1, chain2, chain3, chain4])
    def test_simulate_no_recomp_sequence(self, chain_fn):
        """Simulate the trivial no-recomputation sequence."""
        _, _, simulate = _import_solver()
        ch = chain_fn()
        ops = []
        for i in range(ch.length):
            ops.append(ForwardEnable(i))
        ops.append(Loss())
        for i in range(ch.length - 1, -1, -1):
            ops.append(Backward(i))
        peak = simulate(ops, ch)
        assert peak > 0

    def test_simulate_invalid_backward_raises(self):
        """Backward without required activations must raise ValueError."""
        _, _, simulate = _import_solver()
        ch = chain1()
        ops = [Backward(0)]  # No xbar_1 or y_1 in memory
        with pytest.raises(ValueError):
            simulate(ops, ch)

    def test_simulate_invalid_forward_raises(self):
        """ForwardNograd without input must raise ValueError."""
        _, _, simulate = _import_solver()
        ch = chain2()
        ops = [ForwardNograd(2)]  # Only x_0 in memory, not x_2
        with pytest.raises(ValueError):
            simulate(ops, ch)


class TestEndToEnd:
    """Full pipeline tests on diverse chains."""

    @pytest.mark.parametrize("chain_fn, budget, expected_opt", GOLDEN_OPT)
    def test_full_pipeline(self, chain_fn, budget, expected_opt):
        """compute_table -> reconstruct -> simulate must be consistent."""
        compute_table, reconstruct, simulate = _import_solver()
        ch = chain_fn()
        opt_table = compute_table(ch, budget)
        opt, _ = opt_table
        cmem = budget - ch.cweigth[0]

        # Opt value
        assert abs(opt[cmem][0][ch.length] - expected_opt) < 1e-9

        # Reconstruct
        ops = reconstruct(ch, 0, ch.length, cmem, opt_table)

        # Makespan
        fw = ch.fweigth + [0]
        bw = ch.bweigth
        mk = sum(
            fw[op.index] if isinstance(op, (ForwardCheck, ForwardNograd, ForwardEnable))
            else bw[op.index] if isinstance(op, Backward)
            else 0
            for op in ops
        )
        assert abs(mk - expected_opt) < 1e-9

        # Simulate
        peak = simulate(ops, ch)
        assert peak <= budget

    def test_chain_length_6_heterogeneous(self):
        """Stress test with a larger heterogeneous chain."""
        compute_table, reconstruct, simulate = _import_solver()
        ch = Chain(
            fw=[2.0, 1.0, 3.0, 2.0, 1.0, 4.0],
            bw=[1.0, 2.0, 1.0, 3.0, 2.0, 1.0, 0.0],
            cw=[1, 2, 3, 1, 2, 1, 2],
            cbw=[2, 3, 4, 2, 3, 2, 3],
            ftmp=[1, 0, 2, 0, 1, 0],
            btmp=[0, 1, 0, 1, 0, 1, 0],
        )
        no_recomp = sum(ch.fweigth) + sum(ch.bweigth)

        # Find minimum feasible budget
        for budget in range(1, 60):
            opt_table = compute_table(ch, budget)
            opt, _ = opt_table
            cmem = budget - ch.cweigth[0]
            if cmem < 0:
                continue
            val = opt[cmem][0][ch.length]
            if val < float("inf"):
                ops = reconstruct(ch, 0, ch.length, cmem, opt_table)
                peak = simulate(ops, ch)
                assert peak <= budget, (
                    f"Peak {peak} > budget {budget}"
                )

                fw = ch.fweigth + [0]
                bw = ch.bweigth
                mk = sum(
                    fw[op.index] if isinstance(op, (ForwardCheck, ForwardNograd, ForwardEnable))
                    else bw[op.index] if isinstance(op, Backward)
                    else 0
                    for op in ops
                )
                assert abs(mk - val) < 1e-9
                break

        # At high budget, should reach no-recomputation
        budget = 50
        opt_table = compute_table(ch, budget)
        opt, _ = opt_table
        cmem = budget - ch.cweigth[0]
        val = opt[cmem][0][ch.length]
        assert abs(val - no_recomp) < 1e-9

    def test_subproblem_consistency(self):
        """For chain3, verify internal DP subproblems are consistent."""
        compute_table, reconstruct, simulate = _import_solver()
        ch = chain3()
        budget = 20
        opt_table = compute_table(ch, budget)
        opt, _ = opt_table

        # Check that various subproblems have finite values at high budget
        cmem = budget - ch.cweigth[0]
        for i in range(ch.length + 1):
            for l in range(i, ch.length + 1):
                val = opt[cmem][i].get(l, float("inf"))
                assert val < float("inf"), (
                    f"opt[{cmem}][{i}][{l}] should be finite at budget {budget}"
                )

    def test_opt_table_structure(self):
        """Verify opt table supports required indexing pattern."""
        compute_table, _, _ = _import_solver()
        ch = chain2()
        budget = 15
        opt, what = compute_table(ch, budget)

        # opt[m][i] should be dict-like mapping l -> value
        for m in range(budget + 1):
            for i in range(ch.length + 1):
                d = opt[m][i]
                assert hasattr(d, '__getitem__'), (
                    f"opt[{m}][{i}] must support __getitem__"
                )
                # Check that the base case exists
                assert i in d, f"opt[{m}][{i}][{i}] must exist"
