
"""Tests for quantum circuit T-count optimization pipeline.

Verifies that optimized QASM circuits in /app/results/ are unitarily
equivalent to originals in /app/benchmarks/ and meet T-count targets.
"""

import json
import os

import numpy as np
import pytest
import pyzx as zx


BENCHMARKS_DIR = "/app/benchmarks"
RESULTS_DIR = "/app/results"
TARGETS_FILE = "/app/targets.json"

BENCHMARK_NAMES = ["bench_a.qasm", "bench_b.qasm", "bench_c.qasm",
                   "bench_d.qasm", "bench_e.qasm"]


def _load_targets():
    with open(TARGETS_FILE) as f:
        return json.load(f)


def _unitaries_equivalent(U, V, tol=1e-6):
    """True iff U == e^{i theta} V for some global phase theta."""
    if U.shape != V.shape:
        return False
    if np.allclose(U, V, atol=tol):
        return True
    for i in range(U.shape[0]):
        for j in range(U.shape[1]):
            if abs(V[i, j]) > tol:
                ratio = U[i, j] / V[i, j]
                return np.allclose(U, ratio * V, atol=tol)
    return np.allclose(U, 0, atol=tol)


def _count_non_clifford(circ):
    """Count non-Clifford rotation gates in a pyzx Circuit."""
    count = 0
    for gate in circ.gates:
        if hasattr(gate, "phase"):
            p = float(gate.phase) % 2.0
            if not any(abs(p - c) < 1e-6 for c in [0.0, 0.5, 1.0, 1.5]):
                count += 1
    return count


# -------------------------------------------------------------------
# Result file existence
# -------------------------------------------------------------------

class TestResultsExist:

    def test_results_dir_exists(self):
        assert os.path.isdir(RESULTS_DIR), f"{RESULTS_DIR} directory missing"

    @pytest.mark.parametrize("name", BENCHMARK_NAMES)
    def test_result_file_exists(self, name):
        path = os.path.join(RESULTS_DIR, name)
        assert os.path.isfile(path), f"Missing optimized circuit: {path}"


# -------------------------------------------------------------------
# Unitary equivalence
# -------------------------------------------------------------------

class TestUnitaryEquivalence:

    @pytest.mark.parametrize("name", BENCHMARK_NAMES)
    def test_unitary_matches(self, name):
        orig_path = os.path.join(BENCHMARKS_DIR, name)
        opt_path = os.path.join(RESULTS_DIR, name)
        if not os.path.isfile(opt_path):
            pytest.fail(f"Result file missing: {opt_path}")

        orig_circ = zx.Circuit.from_qasm_file(orig_path)
        opt_circ = zx.Circuit.from_qasm_file(opt_path)

        U_orig = orig_circ.to_matrix()
        U_opt = opt_circ.to_matrix()

        assert _unitaries_equivalent(U_orig, U_opt), (
            f"{name}: optimized circuit is NOT unitarily equivalent to original"
        )


# -------------------------------------------------------------------
# T-count targets
# -------------------------------------------------------------------

class TestTCountTargets:

    @pytest.mark.parametrize("name", BENCHMARK_NAMES)
    def test_meets_target(self, name):
        targets = _load_targets()
        opt_path = os.path.join(RESULTS_DIR, name)
        if not os.path.isfile(opt_path):
            pytest.fail(f"Result file missing: {opt_path}")

        opt_circ = zx.Circuit.from_qasm_file(opt_path)
        t_count = _count_non_clifford(opt_circ)
        target = targets[name]

        assert t_count <= target, (
            f"{name}: non-Clifford count {t_count} exceeds target {target}"
        )


# -------------------------------------------------------------------
# Qubit preservation
# -------------------------------------------------------------------

class TestQubitPreservation:

    @pytest.mark.parametrize("name", BENCHMARK_NAMES)
    def test_qubit_count_unchanged(self, name):
        orig_path = os.path.join(BENCHMARKS_DIR, name)
        opt_path = os.path.join(RESULTS_DIR, name)
        if not os.path.isfile(opt_path):
            pytest.skip(f"Result file missing: {opt_path}")

        orig_circ = zx.Circuit.from_qasm_file(orig_path)
        opt_circ = zx.Circuit.from_qasm_file(opt_path)

        assert orig_circ.qubits == opt_circ.qubits, (
            f"{name}: qubit count changed {orig_circ.qubits} -> {opt_circ.qubits}"
        )


# -------------------------------------------------------------------
# Valid QASM output
# -------------------------------------------------------------------

class TestValidQASM:

    @pytest.mark.parametrize("name", BENCHMARK_NAMES)
    def test_parseable_qasm(self, name):
        """Optimized output must be valid QASM that pyzx can parse."""
        opt_path = os.path.join(RESULTS_DIR, name)
        if not os.path.isfile(opt_path):
            pytest.skip(f"Result file missing: {opt_path}")

        try:
            circ = zx.Circuit.from_qasm_file(opt_path)
        except Exception as e:
            pytest.fail(f"{name}: pyzx could not parse output QASM: {e}")

        assert circ.qubits > 0, f"{name}: parsed circuit has 0 qubits"
        assert len(circ.gates) > 0, f"{name}: parsed circuit has 0 gates"
