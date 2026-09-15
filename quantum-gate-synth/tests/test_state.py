
"""Verification tests for quantum circuit synthesis task.

Uses pure numpy for circuit unitary reconstruction — no BQSKit dependency.
"""
import json
import os
import sys
from itertools import permutations

import numpy as np
import pytest

sys.path.insert(0, "/app")
from target_unitary import get_target_unitary

# ---------------------------------------------------------------------------
# Gate matrix definitions (must match instruction specification exactly)
# ---------------------------------------------------------------------------

SX_MATRIX = 0.5 * np.array(
    [[1 + 1j, 1 - 1j], [1 - 1j, 1 + 1j]], dtype=np.complex128
)


def rz_matrix(theta):
    half = theta / 2.0
    return np.array(
        [[np.exp(-1j * half), 0], [0, np.exp(1j * half)]], dtype=np.complex128
    )


def xxplusyy_matrix(theta, beta):
    c = np.cos(theta / 2.0)
    s = np.sin(theta / 2.0)
    eb = np.exp(1j * beta)
    return np.array(
        [
            [1, 0, 0, 0],
            [0, c, 1j * s * eb, 0],
            [0, 1j * s / eb, c, 0],
            [0, 0, 0, 1],
        ],
        dtype=np.complex128,
    )


# ---------------------------------------------------------------------------
# Circuit reconstruction from JSON (big-endian qubit ordering)
# ---------------------------------------------------------------------------

def embed_gate(gate_mat, qubits, num_qubits):
    """Embed a gate matrix into the full n-qubit Hilbert space.

    Uses big-endian convention: qubit 0 is the most significant bit.
    Handles arbitrary qubit orderings (e.g. qubits=[1,0] swaps roles).
    """
    n = num_qubits
    dim = 2 ** n
    nq = len(qubits)
    full = np.zeros((dim, dim), dtype=np.complex128)
    for j in range(dim):
        j_gate = 0
        for k, q in enumerate(qubits):
            bit = (j >> (n - 1 - q)) & 1
            j_gate |= bit << (nq - 1 - k)
        for i_gate in range(2 ** nq):
            val = gate_mat[i_gate, j_gate]
            if abs(val) < 1e-15:
                continue
            i_full = j
            for k, q in enumerate(qubits):
                bit = (i_gate >> (nq - 1 - k)) & 1
                mask = 1 << (n - 1 - q)
                i_full = (i_full & ~mask) | (bit * mask)
            full[i_full, j] += val
    return full


def get_gate_matrix(name, params):
    """Return the unitary matrix for a named gate with given parameters."""
    if name == "rz":
        return rz_matrix(params[0])
    elif name == "sx":
        return SX_MATRIX.copy()
    elif name == "xxplusyy":
        return xxplusyy_matrix(params[0], params[1])
    else:
        raise ValueError(f"Unknown gate: {name}")


def build_circuit_unitary(circuit_data, qubit_perm=None):
    """Reconstruct the full circuit unitary from the JSON gate list."""
    n = circuit_data["num_qubits"]
    dim = 2 ** n
    U = np.eye(dim, dtype=np.complex128)
    for gate_info in circuit_data["gates"]:
        name = gate_info["name"]
        params = gate_info.get("params", [])
        qubits = gate_info["qubits"]
        if qubit_perm is not None:
            qubits = [qubit_perm[q] for q in qubits]
        gate_mat = get_gate_matrix(name, params)
        full = embed_gate(gate_mat, qubits, n)
        U = full @ U
    return U


def process_fidelity(U, V):
    """Hilbert-Schmidt process fidelity: |Tr(U† V)|² / d²."""
    d = U.shape[0]
    return float(np.abs(np.trace(np.conj(U).T @ V)) ** 2 / d ** 2)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ALLOWED_GATES = {"xxplusyy", "rz", "sx"}
ALLOWED_COUPLING = {(0, 1), (1, 0), (1, 2), (2, 1)}
MAX_XXPLUSYY = 25
FIDELITY_THRESHOLD = 1.0 - 1e-6


def load_circuit_json():
    path = "/app/result/circuit.json"
    with open(path) as f:
        return json.load(f)


def load_metrics_json():
    path = "/app/result/metrics.json"
    with open(path) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestOutputFilesExist:
    def test_circuit_json_exists(self):
        assert os.path.exists("/app/result/circuit.json"), (
            "circuit.json not found at /app/result/circuit.json"
        )

    def test_metrics_json_exists(self):
        assert os.path.exists("/app/result/metrics.json"), (
            "metrics.json not found at /app/result/metrics.json"
        )


class TestGateSetCompliance:
    def test_all_gates_native(self):
        data = load_circuit_json()
        for i, gate in enumerate(data["gates"]):
            assert gate["name"] in ALLOWED_GATES, (
                f"Gate {i} uses non-native gate '{gate['name']}'. "
                f"Allowed: {ALLOWED_GATES}"
            )

    def test_rz_has_one_param(self):
        data = load_circuit_json()
        for i, gate in enumerate(data["gates"]):
            if gate["name"] == "rz":
                assert len(gate["params"]) == 1, (
                    f"Gate {i} (rz) should have 1 param, got {len(gate['params'])}"
                )

    def test_xxplusyy_has_two_params(self):
        data = load_circuit_json()
        for i, gate in enumerate(data["gates"]):
            if gate["name"] == "xxplusyy":
                assert len(gate["params"]) == 2, (
                    f"Gate {i} (xxplusyy) should have 2 params, "
                    f"got {len(gate['params'])}"
                )

    def test_sx_has_no_params(self):
        data = load_circuit_json()
        for i, gate in enumerate(data["gates"]):
            if gate["name"] == "sx":
                assert len(gate.get("params", [])) == 0, (
                    f"Gate {i} (sx) should have 0 params"
                )


class TestCouplingConstraints:
    def test_two_qubit_gates_on_coupled_pairs(self):
        data = load_circuit_json()
        for i, gate in enumerate(data["gates"]):
            if len(gate["qubits"]) == 2:
                pair = tuple(gate["qubits"])
                assert pair in ALLOWED_COUPLING, (
                    f"Gate {i} ({gate['name']}) on qubits {pair} violates "
                    f"coupling constraints. Allowed: {ALLOWED_COUPLING}"
                )

    def test_single_qubit_gates_on_valid_qubits(self):
        data = load_circuit_json()
        n = data["num_qubits"]
        for i, gate in enumerate(data["gates"]):
            if len(gate["qubits"]) == 1:
                q = gate["qubits"][0]
                assert 0 <= q < n, (
                    f"Gate {i} on qubit {q} out of range [0, {n})"
                )


class TestGateCount:
    def test_xxplusyy_count_within_limit(self):
        data = load_circuit_json()
        count = sum(1 for g in data["gates"] if g["name"] == "xxplusyy")
        assert count <= MAX_XXPLUSYY, (
            f"XXPlusYY gate count {count} exceeds limit {MAX_XXPLUSYY}"
        )

    def test_circuit_has_gates(self):
        data = load_circuit_json()
        assert len(data["gates"]) > 0, "Circuit has no gates"

    def test_circuit_has_entangling_gates(self):
        data = load_circuit_json()
        count = sum(1 for g in data["gates"] if g["name"] == "xxplusyy")
        assert count > 0, (
            "Circuit has no XXPlusYY gates — cannot implement a "
            "non-trivial 3-qubit unitary without entangling gates"
        )


class TestProcessFidelity:
    def test_fidelity_with_target(self):
        data = load_circuit_json()
        target = get_target_unitary()
        n = data["num_qubits"]
        assert n == 3, f"Expected 3-qubit circuit, got {n} qubits"

        best_fidelity = 0.0
        for perm in permutations(range(n)):
            try:
                U_circuit = build_circuit_unitary(data, qubit_perm=list(perm))
                fid = process_fidelity(target, U_circuit)
                best_fidelity = max(best_fidelity, fid)
            except Exception:
                continue

        assert best_fidelity > FIDELITY_THRESHOLD, (
            f"Best process fidelity {best_fidelity:.10f} is below threshold "
            f"{FIDELITY_THRESHOLD}. Circuit does not implement the target unitary."
        )


class TestMetricsConsistency:
    def test_metrics_has_required_keys(self):
        metrics = load_metrics_json()
        for key in ["xxplusyy_count", "total_gates", "process_fidelity"]:
            assert key in metrics, f"metrics.json missing key '{key}'"

    def test_xxplusyy_count_matches_circuit(self):
        metrics = load_metrics_json()
        data = load_circuit_json()
        actual = sum(1 for g in data["gates"] if g["name"] == "xxplusyy")
        assert metrics["xxplusyy_count"] == actual, (
            f"metrics.json xxplusyy_count ({metrics['xxplusyy_count']}) "
            f"doesn't match actual count ({actual})"
        )

    def test_total_gates_matches_circuit(self):
        metrics = load_metrics_json()
        data = load_circuit_json()
        actual = len(data["gates"])
        assert metrics["total_gates"] == actual, (
            f"metrics.json total_gates ({metrics['total_gates']}) "
            f"doesn't match actual count ({actual})"
        )

    def test_reported_fidelity_reasonable(self):
        metrics = load_metrics_json()
        assert 0.0 <= metrics["process_fidelity"] <= 1.0, (
            f"Reported fidelity {metrics['process_fidelity']} out of [0, 1]"
        )
