"""

Tests for the quantum program analysis pipeline.
Reference implementations use numpy/scipy to independently compute expected values.
"""

import json
import os
import re
import subprocess
import numpy as np
from scipy.linalg import expm
import pytest

ATOL_VEC = 1e-8
ATOL_SCALAR = 1e-6

# ====================== Reference Gate Matrices ======================

I2 = np.eye(2, dtype=complex)
PAULI_X = np.array([[0, 1], [1, 0]], dtype=complex)
PAULI_Y = np.array([[0, -1j], [1j, 0]], dtype=complex)
PAULI_Z = np.array([[1, 0], [0, -1]], dtype=complex)
PAULIS = {"I": I2, "X": PAULI_X, "Y": PAULI_Y, "Z": PAULI_Z}

H_GATE = np.array([[1, 1], [1, -1]], dtype=complex) / np.sqrt(2)
X_GATE = PAULI_X.copy()


def gate_Ry(theta):
    c, s = np.cos(theta / 2), np.sin(theta / 2)
    return np.array([[c, -s], [s, c]], dtype=complex)


def gate_Rz(theta):
    return np.array(
        [[np.exp(-1j * theta / 2), 0], [0, np.exp(1j * theta / 2)]], dtype=complex
    )


# ====================== Reference Operators ======================


def _full_single_gate(gate_matrix, qubit, n_qubits):
    """Build full 2^n x 2^n operator for a single-qubit gate.

    Convention: index = sum(q_k * 2^k), qubit 0 is LSB.
    Kronecker product ordering: kron(P_{n-1}, kron(P_{n-2}, ... kron(P_1, P_0)))
    so that P_k acts on qubit k.
    """
    ops = [I2] * n_qubits
    ops[qubit] = gate_matrix
    result = ops[0]
    for k in range(1, n_qubits):
        result = np.kron(ops[k], result)
    return result


def _cnot_matrix(control, target, n_qubits):
    dim = 2 ** n_qubits
    M = np.zeros((dim, dim), dtype=complex)
    for i in range(dim):
        if (i >> control) & 1:
            j = i ^ (1 << target)
        else:
            j = i
        M[j, i] = 1
    return M


def _cz_matrix(q1, q2, n_qubits):
    dim = 2 ** n_qubits
    M = np.eye(dim, dtype=complex)
    for i in range(dim):
        if ((i >> q1) & 1) and ((i >> q2) & 1):
            M[i, i] = -1
    return M


# ====================== Hardcoded Circuits ======================

CIRCUIT_A_GATES = [
    {"type": "H", "qubit": 0},
    {"type": "CNOT", "control": 0, "target": 1},
    {"type": "Ry", "qubit": 2, "angle": 1.0471975511965976},
    {"type": "CNOT", "control": 2, "target": 3},
    {"type": "CZ", "qubits": [1, 2]},
    {"type": "Rz", "qubit": 0, "angle": 0.7853981633974483},
    {"type": "H", "qubit": 3},
    {"type": "CNOT", "control": 3, "target": 0},
    {"type": "Ry", "qubit": 1, "angle": 2.356194490192345},
    {"type": "CZ", "qubits": [0, 2]},
]

GHZ4_GATES = [
    {"type": "H", "qubit": 0},
    {"type": "CNOT", "control": 0, "target": 1},
    {"type": "CNOT", "control": 1, "target": 2},
    {"type": "CNOT", "control": 2, "target": 3},
]

CHAIN6_GATES = [
    {"type": "H", "qubit": 0},
    {"type": "CNOT", "control": 0, "target": 3},
    {"type": "H", "qubit": 1},
    {"type": "CNOT", "control": 1, "target": 4},
    {"type": "H", "qubit": 2},
    {"type": "CNOT", "control": 2, "target": 5},
    {"type": "Ry", "qubit": 0, "angle": 0.9272952180016122},
    {"type": "CNOT", "control": 0, "target": 1},
]

INIT_PREP_GATES = [
    {"type": "H", "qubit": 0},
    {"type": "H", "qubit": 2},
]

HAMILTONIAN_TERMS = [
    {"coeff": -1.0, "pauli": "ZZII"},
    {"coeff": -1.0, "pauli": "IZZI"},
    {"coeff": -1.0, "pauli": "IIZZ"},
    {"coeff": -1.0, "pauli": "ZIIZ"},
    {"coeff": -0.5, "pauli": "XIII"},
    {"coeff": -0.5, "pauli": "IXII"},
    {"coeff": -0.5, "pauli": "IIXI"},
    {"coeff": -0.5, "pauli": "IIIX"},
    {"coeff": 0.25, "pauli": "YYII"},
    {"coeff": 0.25, "pauli": "IIYY"},
    {"coeff": -0.1, "pauli": "XZZX"},
]


# ====================== Reference Simulation ======================


def _apply_gate(state, gate_desc, n_qubits):
    gtype = gate_desc["type"]
    if gtype == "H":
        op = _full_single_gate(H_GATE, gate_desc["qubit"], n_qubits)
    elif gtype == "X":
        op = _full_single_gate(X_GATE, gate_desc["qubit"], n_qubits)
    elif gtype == "Ry":
        op = _full_single_gate(gate_Ry(gate_desc["angle"]), gate_desc["qubit"], n_qubits)
    elif gtype == "Rz":
        op = _full_single_gate(gate_Rz(gate_desc["angle"]), gate_desc["qubit"], n_qubits)
    elif gtype == "CNOT":
        op = _cnot_matrix(gate_desc["control"], gate_desc["target"], n_qubits)
    elif gtype == "CZ":
        op = _cz_matrix(gate_desc["qubits"][0], gate_desc["qubits"][1], n_qubits)
    else:
        raise ValueError(f"Unknown gate: {gtype}")
    return op @ state


def ref_simulate(gates, n_qubits, initial_state=None):
    dim = 2 ** n_qubits
    if initial_state is None:
        state = np.zeros(dim, dtype=complex)
        state[0] = 1.0
    else:
        state = initial_state.copy()
    for g in gates:
        state = _apply_gate(state, g, n_qubits)
    return state


def ref_pauli_matrix(pauli_str, n_qubits):
    ops = [PAULIS[c] for c in pauli_str]
    result = ops[0]
    for k in range(1, n_qubits):
        result = np.kron(ops[k], result)
    return result


def ref_partial_trace(state_vec, n_qubits, keep_qubits):
    psi = state_vec.reshape([2] * n_qubits)
    keep_axes = sorted([n_qubits - 1 - q for q in keep_qubits])
    trace_axes = sorted(
        [n_qubits - 1 - q for q in range(n_qubits) if q not in keep_qubits]
    )
    psi = np.transpose(psi, keep_axes + trace_axes)
    n_keep = len(keep_qubits)
    n_trace = n_qubits - n_keep
    psi = psi.reshape(2 ** n_keep, 2 ** n_trace)
    return psi @ psi.conj().T


def ref_entropy(rho):
    eigenvalues = np.linalg.eigvalsh(rho)
    eigenvalues = eigenvalues[eigenvalues > 1e-15]
    return float(-np.sum(eigenvalues * np.log(eigenvalues)))


# ====================== Helper Functions ======================


def _state_from_pairs(pairs):
    return np.array([complex(r, im) for r, im in pairs])


def _assert_states_equal(actual, expected, atol=ATOL_VEC):
    idx = np.argmax(np.abs(expected))
    if np.abs(expected[idx]) > 1e-10 and np.abs(actual[idx]) > 1e-10:
        phase = actual[idx] / expected[idx]
        if abs(abs(phase) - 1.0) < 1e-6:
            actual_adj = actual * (expected[idx] / actual[idx])
            np.testing.assert_allclose(actual_adj, expected, atol=atol)
            return
    np.testing.assert_allclose(actual, expected, atol=atol)


# ====================== Fixtures ======================


@pytest.fixture(scope="module")
def results():
    with open("/app/results.json") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def spec():
    with open("/app/spec.json") as f:
        return json.load(f)


# ====================== Task 1: Simulate ======================


class TestSimulate:
    def test_state_vector(self, results):
        expected = ref_simulate(CIRCUIT_A_GATES, 4)
        actual = _state_from_pairs(results["simulate"]["state_vector"])
        _assert_states_equal(actual, expected)

    def test_normalization(self, results):
        sv = _state_from_pairs(results["simulate"]["state_vector"])
        norm_sq = float(np.sum(np.abs(sv) ** 2))
        assert abs(norm_sq - 1.0) < ATOL_SCALAR, f"Not normalized: |psi|^2 = {norm_sq}"

    def test_length(self, results):
        sv = results["simulate"]["state_vector"]
        assert len(sv) == 16, f"Expected 16 amplitudes for 4 qubits, got {len(sv)}"


# ====================== Task 2: Spectral Transform ======================


class TestSpectralTransform:
    BASIS_STATES = [
        (3, 5),   # 3 qubits, j=5
        (4, 6),   # 4 qubits, j=6
        (5, 19),  # 5 qubits, j=19
    ]

    @pytest.mark.parametrize("idx", [0, 1, 2])
    def test_transform_output(self, results, idx):
        n, j = self.BASIS_STATES[idx]
        N = 2 ** n
        expected = np.array(
            [np.exp(2j * np.pi * j * k / N) / np.sqrt(N) for k in range(N)]
        )
        actual = _state_from_pairs(results["spectral_transform"]["outputs"][idx])
        _assert_states_equal(actual, expected)

    @pytest.mark.parametrize("idx", [0, 1, 2])
    def test_normalization(self, results, idx):
        sv = _state_from_pairs(results["spectral_transform"]["outputs"][idx])
        norm_sq = float(np.sum(np.abs(sv) ** 2))
        assert abs(norm_sq - 1.0) < ATOL_SCALAR

    @pytest.mark.parametrize("idx", [0, 1, 2])
    def test_length(self, results, idx):
        n, _ = self.BASIS_STATES[idx]
        N = 2 ** n
        sv = results["spectral_transform"]["outputs"][idx]
        assert len(sv) == N, f"Expected {N} amplitudes, got {len(sv)}"


# ====================== Task 3: Subsystem Entropy ======================


class TestSubsystemEntropy:
    @pytest.mark.parametrize(
        "idx,gates,n,keep",
        [
            (0, GHZ4_GATES, 4, [0, 1]),
            (1, CHAIN6_GATES, 6, [0, 1, 2]),
        ],
    )
    def test_entropy_value(self, results, idx, gates, n, keep):
        state = ref_simulate(gates, n)
        rho_A = ref_partial_trace(state, n, keep)
        expected_S = ref_entropy(rho_A)
        actual_S = results["subsystem_entropy"]["entropies"][idx]
        assert abs(actual_S - expected_S) < ATOL_SCALAR, (
            f"Entropy mismatch: expected {expected_S:.10f}, got {actual_S}"
        )

    def test_ghz_entropy_analytical(self, results):
        """GHZ state entropy should be ln(2) for any non-trivial bipartition."""
        actual_S = results["subsystem_entropy"]["entropies"][0]
        expected_S = np.log(2)
        assert abs(actual_S - expected_S) < ATOL_SCALAR, (
            f"Expected entropy ln(2)={expected_S:.10f}, got {actual_S}"
        )

    @pytest.mark.parametrize("idx", [0, 1])
    def test_entropy_nonnegative(self, results, idx):
        S = results["subsystem_entropy"]["entropies"][idx]
        assert S >= -ATOL_SCALAR, f"Entropy should be non-negative, got {S}"


# ====================== Task 4: Hamiltonian Analysis ======================


class TestHamiltonianAnalysis:
    def _build_H(self):
        n = 4
        dim = 16
        H = np.zeros((dim, dim), dtype=complex)
        for term in HAMILTONIAN_TERMS:
            H += term["coeff"] * ref_pauli_matrix(term["pauli"], n)
        return H

    def test_hermitian(self):
        H = self._build_H()
        np.testing.assert_allclose(H, H.conj().T, atol=1e-14)

    def test_min_eigenvalue(self, results):
        H = self._build_H()
        eigenvalues = np.linalg.eigvalsh(H)
        expected_E0 = float(eigenvalues[0])
        actual_E0 = results["hamiltonian_analysis"]["min_eigenvalue"]
        assert abs(actual_E0 - expected_E0) < ATOL_SCALAR, (
            f"Min eigenvalue mismatch: expected {expected_E0:.10f}, got {actual_E0}"
        )

    def test_evolved_expectation(self, results):
        H = self._build_H()
        n = 4
        init_state = ref_simulate(INIT_PREP_GATES, n)
        t = 1.5
        U = expm(-1j * H * t)
        evolved = U @ init_state
        obs = ref_pauli_matrix("ZIII", n)
        expected_val = float(np.real(evolved.conj() @ obs @ evolved))
        actual_val = results["hamiltonian_analysis"]["evolved_expectation"]
        assert abs(actual_val - expected_val) < ATOL_SCALAR, (
            f"Expectation mismatch: expected {expected_val:.10f}, got {actual_val}"
        )

    def test_expectation_bounded(self, results):
        val = results["hamiltonian_analysis"]["evolved_expectation"]
        assert -1.0 - ATOL_SCALAR <= val <= 1.0 + ATOL_SCALAR, (
            f"<Z> = {val} is out of bounds [-1, 1]"
        )


# ====================== Task 5: Topology Analysis ======================


class TestTopologyAnalysis:
    # circuit_a.quil two-qubit gates: CNOT 0 1, CNOT 2 3, CZ 1 2, CNOT 3 0, CZ 0 2
    EXPECTED_INTERACTION_EDGES = {(0, 1), (0, 2), (0, 3), (1, 2), (2, 3)}
    # topology.dot: 0--1, 1--2, 2--3, 0--3
    EXPECTED_TOPOLOGY_EDGES = {(0, 1), (0, 3), (1, 2), (2, 3)}
    EXPECTED_COMPATIBLE = EXPECTED_INTERACTION_EDGES & EXPECTED_TOPOLOGY_EDGES

    def test_interaction_edge_count(self, results):
        actual = results["topology_analysis"]["interaction_edges"]
        expected = len(self.EXPECTED_INTERACTION_EDGES)
        assert actual == expected, (
            f"Expected {expected} interaction edges, got {actual}"
        )

    def test_topology_edge_count(self, results):
        actual = results["topology_analysis"]["topology_edges"]
        expected = len(self.EXPECTED_TOPOLOGY_EDGES)
        assert actual == expected, (
            f"Expected {expected} topology edges, got {actual}"
        )

    def test_compatible_edge_count(self, results):
        actual = results["topology_analysis"]["compatible_edges"]
        expected = len(self.EXPECTED_COMPATIBLE)
        assert actual == expected, (
            f"Expected {expected} compatible edges, got {actual}"
        )

    def test_not_directly_executable(self, results):
        assert results["topology_analysis"]["directly_executable"] is False, (
            "Circuit should NOT be directly executable on this topology"
        )

    def test_dot_file_exists(self):
        path = "/app/graphs/interaction_circuit_a.dot"
        assert os.path.exists(path), f"DOT file not found at {path}"

    def test_dot_file_valid_graphviz(self):
        result = subprocess.run(
            ["dot", "-Tsvg", "/app/graphs/interaction_circuit_a.dot"],
            capture_output=True,
        )
        assert result.returncode == 0, (
            f"DOT file failed graphviz validation: {result.stderr.decode()}"
        )

    def test_dot_file_edges(self):
        with open("/app/graphs/interaction_circuit_a.dot") as f:
            content = f.read()
        edges = set()
        for match in re.finditer(r'"?(\d+)"?\s*--\s*"?(\d+)"?', content):
            a, b = int(match.group(1)), int(match.group(2))
            edges.add((min(a, b), max(a, b)))
        assert edges == self.EXPECTED_INTERACTION_EDGES, (
            f"Expected edges {self.EXPECTED_INTERACTION_EDGES}, got {edges}"
        )

    def test_dot_file_has_all_qubits(self):
        with open("/app/graphs/interaction_circuit_a.dot") as f:
            content = f.read()
        for q in range(4):
            assert str(q) in content, f"Qubit {q} not found in DOT file"
