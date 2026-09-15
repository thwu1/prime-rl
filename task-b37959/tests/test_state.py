
"""Tests for the Matrix Chain Compiler with BLAS kernel selection."""

import json
import os
import subprocess
import pytest
import numpy as np


RESULTS_PATH = "/app/results.json"
KERNEL_PLAN_PATH = "/app/kernel_plan.json"
BLAS_EVAL_SRC = "/app/blas_eval.c"
BLAS_EVAL_BIN = "/app/blas_eval"

EXPECTED_COSTS = {
    "basic_three_general": 9000,
    "diagonal_savings": 2005000,
    "triangular_propagation": 6000000,
    "transpose_effect": 512000,
    "identity_present": 2500000,
    "all_diagonal": 300,
    "property_critical": 1005100,
    "six_matrix_stress": 23800,
    "nonsquare_transpose": 396000,
    "sym_savings": 2500000,
    "sym_tri_interact": 1000000,
    "sym_transpose": 256000,
    "diag_sym_chain": 2020000,
    "diag_tri_propagation": 377500,
    "upper_lower_collapse": 288000,
    "sym_propagation_trap": 1000000,
    "deep_propagation_chain": 163200,
}

VALID_ROUTINES = {"dgemm", "dsymm", "dtrmm", "ddiagmm", "copy"}


# ---------- helpers for CBLAS reference computation ----------

def init_general(rows, cols):
    total = rows * cols
    return np.array(
        [[(i * cols + j + 1.0) / total for j in range(cols)] for i in range(rows)]
    )


def init_symmetric(n):
    return np.array([[1.0 / (1.0 + abs(i - j)) for j in range(n)] for i in range(n)])


def init_lower_triangular(n):
    return np.array(
        [[(1.0 / (i - j + 1.0) if j <= i else 0.0) for j in range(n)] for i in range(n)]
    )


# ---------- fixtures ----------

@pytest.fixture(scope="module")
def results():
    assert os.path.exists(RESULTS_PATH), (
        f"Results file not found at {RESULTS_PATH}. "
        "The optimizer must write its output to /app/results.json."
    )
    with open(RESULTS_PATH, "r") as f:
        data = json.load(f)
    assert isinstance(data, dict), "results.json must contain a JSON object"
    return data


@pytest.fixture(scope="module")
def kernel_plan():
    assert os.path.exists(KERNEL_PLAN_PATH), (
        f"Kernel plan not found at {KERNEL_PLAN_PATH}."
    )
    with open(KERNEL_PLAN_PATH, "r") as f:
        data = json.load(f)
    assert isinstance(data, dict), "kernel_plan.json must contain a JSON object"
    return data


@pytest.fixture(scope="module")
def blas_output():
    """Compile and run blas_eval.c, return parsed output dict."""
    assert os.path.exists(BLAS_EVAL_SRC), (
        f"CBLAS source not found at {BLAS_EVAL_SRC}."
    )
    comp = subprocess.run(
        ["gcc", "-o", BLAS_EVAL_BIN, BLAS_EVAL_SRC, "-lopenblas", "-lm"],
        capture_output=True, text=True, timeout=60,
    )
    assert comp.returncode == 0, f"Compilation failed:\n{comp.stderr}"

    run = subprocess.run(
        [BLAS_EVAL_BIN], capture_output=True, text=True, timeout=30,
    )
    assert run.returncode == 0, f"Execution failed:\n{run.stderr}"

    values = {}
    for line in run.stdout.strip().split("\n"):
        if "=" in line and line.strip() != "BLAS_EVAL_COMPLETE":
            key, val = line.split("=", 1)
            values[key.strip()] = float(val.strip())
    return values


# ---------- FLOP cost tests ----------

class TestResultsExist:
    def test_results_file_exists(self, results):
        assert results is not None

    def test_all_chains_present(self, results):
        for name in EXPECTED_COSTS:
            assert name in results, f"Missing chain result: {name}"


class TestOriginalChains:
    """Chains with general, diagonal, triangular, and identity properties."""

    def test_basic_three_general(self, results):
        """3 general matrices: classic MCM."""
        assert results["basic_three_general"] == EXPECTED_COSTS["basic_three_general"]

    def test_diagonal_savings(self, results):
        """Diagonal operand yields cost savings via ddiagmm."""
        assert results["diagonal_savings"] == EXPECTED_COSTS["diagonal_savings"]

    def test_triangular_propagation(self, results):
        """3 lower-triangular + general: triangular propagation matters."""
        assert results["triangular_propagation"] == EXPECTED_COSTS["triangular_propagation"]

    def test_transpose_effect(self, results):
        """Transposed upper_triangular becomes lower_triangular."""
        assert results["transpose_effect"] == EXPECTED_COSTS["transpose_effect"]

    def test_identity_present(self, results):
        """Identity contributes 0 cost to multiplication."""
        assert results["identity_present"] == EXPECTED_COSTS["identity_present"]

    def test_all_diagonal(self, results):
        """4 diagonal matrices, each multiply costs k."""
        assert results["all_diagonal"] == EXPECTED_COSTS["all_diagonal"]

    def test_property_critical(self, results):
        """Diagonal intermediate must be tracked for correct cost.
        Property-unaware solver gets 1010000; correct = 1005100."""
        assert results["property_critical"] == EXPECTED_COSTS["property_critical"]

    def test_six_matrix_stress(self, results):
        """6-matrix chain with mixed properties."""
        assert results["six_matrix_stress"] == EXPECTED_COSTS["six_matrix_stress"]

    def test_nonsquare_transpose(self, results):
        """Non-square with transposed upper_triangular."""
        assert results["nonsquare_transpose"] == EXPECTED_COSTS["nonsquare_transpose"]


class TestSymmetricChains:
    """Chains involving symmetric matrices — requires extended cost model."""

    def test_sym_savings(self, results):
        """dsymm costs half of dgemm for symmetric operand."""
        assert results["sym_savings"] == EXPECTED_COSTS["sym_savings"]

    def test_sym_tri_interact(self, results):
        """Triangular and symmetric interaction in a chain."""
        assert results["sym_tri_interact"] == EXPECTED_COSTS["sym_tri_interact"]

    def test_sym_transpose(self, results):
        """Symmetric is transpose-invariant."""
        assert results["sym_transpose"] == EXPECTED_COSTS["sym_transpose"]

    def test_diag_sym_chain(self, results):
        """Diagonal takes priority over symmetric in kernel selection."""
        assert results["diag_sym_chain"] == EXPECTED_COSTS["diag_sym_chain"]

    def test_diag_tri_propagation(self, results):
        """Diagonal preserves triangularity through chain of operations."""
        assert results["diag_tri_propagation"] == EXPECTED_COSTS["diag_tri_propagation"]


class TestDerivedPropagation:
    """Chains testing property propagation rules that must be derived
    from mathematical principles, not provided in the reference document.
    These serve as traps for common derivation errors."""

    def test_upper_lower_collapse(self, results):
        """Cross-kind triangular multiplication: verify correct property
        derivation for upper-triangular times lower-triangular."""
        assert results["upper_lower_collapse"] == EXPECTED_COSTS["upper_lower_collapse"]

    def test_sym_propagation_trap(self, results):
        """Symmetric-symmetric chain: verify correct property derivation
        for products involving multiple symmetric operands. A common
        derivation error produces a different optimum."""
        assert results["sym_propagation_trap"] == EXPECTED_COSTS["sym_propagation_trap"]

    def test_deep_propagation_chain(self, results):
        """5-matrix chain requiring multi-step property tracking through
        alternating diagonal and triangular operations."""
        assert results["deep_propagation_chain"] == EXPECTED_COSTS["deep_propagation_chain"]


class TestKernelPlan:
    """Verify kernel plans have valid structure and routine names."""

    def test_plan_exists(self, kernel_plan):
        assert kernel_plan is not None

    def test_all_chains_have_plans(self, kernel_plan):
        for name in EXPECTED_COSTS:
            assert name in kernel_plan, f"Missing kernel plan: {name}"

    def test_valid_routine_names(self, kernel_plan):
        for name, plan in kernel_plan.items():
            assert isinstance(plan, list), f"{name}: plan must be a list"
            for routine in plan:
                assert routine in VALID_ROUTINES, (
                    f"{name}: invalid routine '{routine}'. "
                    f"Valid: {VALID_ROUTINES}"
                )

    def test_plan_nonempty_for_multmatrix(self, kernel_plan):
        """Chains with 2+ matrices should have at least one routine."""
        for name in EXPECTED_COSTS:
            if name in kernel_plan:
                assert len(kernel_plan[name]) >= 1, (
                    f"{name}: kernel plan must have at least one routine"
                )


class TestBlasCompilation:
    """Verify blas_eval.c compiles and links against OpenBLAS."""

    def test_source_exists(self):
        assert os.path.exists(BLAS_EVAL_SRC), "blas_eval.c not found"

    def test_compiles(self):
        comp = subprocess.run(
            ["gcc", "-o", BLAS_EVAL_BIN, BLAS_EVAL_SRC, "-lopenblas", "-lm"],
            capture_output=True, text=True, timeout=60,
        )
        assert comp.returncode == 0, f"Compilation failed:\n{comp.stderr}"

    def test_uses_cblas(self):
        """Source must contain CBLAS function calls, not raw loops."""
        with open(BLAS_EVAL_SRC) as f:
            src = f.read()
        assert "cblas_dgemm" in src, "blas_eval.c must use cblas_dgemm"
        assert "cblas_dsymm" in src, "blas_eval.c must use cblas_dsymm"
        assert "cblas_dtrmm" in src, "blas_eval.c must use cblas_dtrmm"

    def test_links_openblas(self):
        """Compiled binary must link against openblas."""
        comp = subprocess.run(
            ["gcc", "-o", BLAS_EVAL_BIN, BLAS_EVAL_SRC, "-lopenblas", "-lm"],
            capture_output=True, text=True, timeout=60,
        )
        if comp.returncode != 0:
            pytest.skip("Compilation failed")
        ldd = subprocess.run(
            ["ldd", BLAS_EVAL_BIN], capture_output=True, text=True
        )
        assert "openblas" in ldd.stdout.lower() or "blas" in ldd.stdout.lower(), (
            "Binary does not link against OpenBLAS"
        )


class TestBlasNumerical:
    """Verify CBLAS evaluation produces correct numerical results."""

    def test_blas_basic(self, blas_output):
        """A(4x6)*B(6x3)*C(3x5) using dgemm+dgemm."""
        A = init_general(4, 6)
        B = init_general(6, 3)
        C = init_general(3, 5)
        R = (A @ B) @ C
        expected = np.linalg.norm(R, "fro")
        assert "blas_basic" in blas_output, "Missing blas_basic output"
        assert abs(blas_output["blas_basic"] - expected) < 1e-6, (
            f"blas_basic: expected {expected:.10f}, got {blas_output['blas_basic']:.10f}"
        )

    def test_blas_sym(self, blas_output):
        """S(4x4,sym)*A(4x6)*B(6x3) using dgemm+dsymm."""
        S = init_symmetric(4)
        A = init_general(4, 6)
        B = init_general(6, 3)
        R = S @ (A @ B)
        expected = np.linalg.norm(R, "fro")
        assert "blas_sym" in blas_output, "Missing blas_sym output"
        assert abs(blas_output["blas_sym"] - expected) < 1e-6, (
            f"blas_sym: expected {expected:.10f}, got {blas_output['blas_sym']:.10f}"
        )

    def test_blas_tri(self, blas_output):
        """L(4x4,lower_tri)*S(4x4,sym)*A(4x3) using dsymm+dtrmm."""
        L = init_lower_triangular(4)
        S = init_symmetric(4)
        A = init_general(4, 3)
        R = L @ (S @ A)
        expected = np.linalg.norm(R, "fro")
        assert "blas_tri" in blas_output, "Missing blas_tri output"
        assert abs(blas_output["blas_tri"] - expected) < 1e-6, (
            f"blas_tri: expected {expected:.10f}, got {blas_output['blas_tri']:.10f}"
        )

    def test_complete_marker(self, blas_output):
        """blas_eval must finish with BLAS_EVAL_COMPLETE."""
        assert os.path.exists(BLAS_EVAL_BIN), "Binary not found"
        run = subprocess.run(
            [BLAS_EVAL_BIN], capture_output=True, text=True, timeout=30,
        )
        assert "BLAS_EVAL_COMPLETE" in run.stdout, (
            "Output must end with BLAS_EVAL_COMPLETE"
        )
