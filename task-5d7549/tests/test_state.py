"""
Verification tests for the quantum circuit compilation pipeline.
Independently validates synthesis correctness, gate counts, and topology compliance.
"""

import json
import os
from itertools import permutations

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def hs_distance(U, V):
    """
    Hilbert-Schmidt distance between two unitaries, accounting for global phase.
    d(U,V) = 1 - |Tr(U^dag V)| / n
    """
    n = U.shape[0]
    return 1.0 - abs(np.trace(U.conj().T @ V)) / n


def min_hs_distance_with_permutations(compiled_U, target_U, n_qubits):
    """
    Find the minimum Hilbert-Schmidt distance over all qubit permutations.
    Tries every possible (input_perm, output_perm) pair to account for
    qubit relabeling introduced by topology-aware routing.
    """
    n = 2 ** n_qubits

    def build_perm_matrix(perm):
        P = np.zeros((n, n), dtype=complex)
        for state in range(n):
            bits = [(state >> (n_qubits - 1 - i)) & 1 for i in range(n_qubits)]
            new_bits = [bits[perm[i]] for i in range(n_qubits)]
            new_state = sum(b << (n_qubits - 1 - i) for i, b in enumerate(new_bits))
            P[new_state, state] = 1.0
        return P

    perm_matrices = [build_perm_matrix(p) for p in permutations(range(n_qubits))]

    min_dist = float("inf")
    for P in perm_matrices:
        for Q in perm_matrices:
            candidate = P @ target_U @ Q
            d = hs_distance(compiled_U, candidate)
            min_dist = min(min_dist, d)
            if min_dist < 1e-10:
                return min_dist
    return min_dist


def get_target_unitaries():
    """Define the target unitaries (must match /app/config.py)."""
    return {
        "iswap": np.array([
            [1, 0, 0, 0],
            [0, 0, 1j, 0],
            [0, 1j, 0, 0],
            [0, 0, 0, 1],
        ], dtype=complex),
        "sqrt_swap": np.array([
            [1, 0, 0, 0],
            [0, (1 + 1j) / 2, (1 - 1j) / 2, 0],
            [0, (1 - 1j) / 2, (1 + 1j) / 2, 0],
            [0, 0, 0, 1],
        ], dtype=complex),
        "magic_basis": (1 / np.sqrt(2)) * np.array([
            [1, 0, 0, 1j],
            [0, 1j, 1, 0],
            [0, 1j, -1, 0],
            [1, 0, 0, -1j],
        ], dtype=complex),
    }


def build_input_circuit_unitary():
    """
    Compute the 16x16 unitary of the 4-qubit input circuit defined in
    /app/input_circuit.qasm:
        H(0), CX(0,1), CX(0,2), CX(0,3), T(1), T(2), T(3),
        CX(1,2), CX(2,3), H(3)
    """
    I2 = np.eye(2, dtype=complex)
    H = np.array([[1, 1], [1, -1]], dtype=complex) / np.sqrt(2)
    T = np.array([[1, 0], [0, np.exp(1j * np.pi / 4)]], dtype=complex)

    def kron_n(*mats):
        result = mats[0]
        for m in mats[1:]:
            result = np.kron(result, m)
        return result

    def single_gate(gate, qubit, n=4):
        mats = [I2] * n
        mats[qubit] = gate
        return kron_n(*mats)

    def cnot_gate(control, target, n=4):
        dim = 2 ** n
        U = np.zeros((dim, dim), dtype=complex)
        for state in range(dim):
            bits = [(state >> (n - 1 - i)) & 1 for i in range(n)]
            if bits[control] == 0:
                U[state, state] = 1.0
            else:
                new_bits = list(bits)
                new_bits[target] ^= 1
                new_state = sum(b << (n - 1 - i) for i, b in enumerate(new_bits))
                U[new_state, state] = 1.0
        return U

    # Build circuit unitary by applying gates left-to-right
    U = np.eye(16, dtype=complex)
    U = single_gate(H, 0) @ U
    U = cnot_gate(0, 1) @ U
    U = cnot_gate(0, 2) @ U
    U = cnot_gate(0, 3) @ U
    U = single_gate(T, 1) @ U
    U = single_gate(T, 2) @ U
    U = single_gate(T, 3) @ U
    U = cnot_gate(1, 2) @ U
    U = cnot_gate(2, 3) @ U
    U = single_gate(H, 3) @ U
    return U


def load_results():
    with open("/app/results.json", "r") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Tests: file existence
# ---------------------------------------------------------------------------

class TestResultsExist:
    def test_results_file_exists(self):
        assert os.path.exists("/app/results.json"), "results.json not found"

    def test_output_directory_exists(self):
        assert os.path.isdir("/app/output"), "output/ directory not found"


# ---------------------------------------------------------------------------
# Tests: JSON schema
# ---------------------------------------------------------------------------

class TestResultsSchema:
    def test_has_unitary_synthesis(self):
        r = load_results()
        assert "unitary_synthesis" in r, "Missing 'unitary_synthesis' key"

    def test_has_circuit_compilation(self):
        r = load_results()
        assert "circuit_compilation" in r, "Missing 'circuit_compilation' key"

    def test_unitary_synthesis_count(self):
        r = load_results()
        assert len(r["unitary_synthesis"]) == 6, (
            f"Expected 6 synthesis entries (3 unitaries x 2 gate sets), "
            f"got {len(r['unitary_synthesis'])}"
        )

    def test_synthesis_entry_fields(self):
        r = load_results()
        required = {
            "target_name", "gate_set", "two_qubit_gate_count",
            "total_gate_count", "hs_distance", "qasm_file",
        }
        for i, entry in enumerate(r["unitary_synthesis"]):
            missing = required - set(entry.keys())
            assert not missing, f"Entry {i} missing fields: {missing}"

    def test_compilation_entry_fields(self):
        r = load_results()
        required = {
            "cnot_count_original", "cnot_count_compiled",
            "hs_distance", "topology_valid", "qasm_file",
        }
        missing = required - set(r["circuit_compilation"].keys())
        assert not missing, f"Compilation entry missing fields: {missing}"


# ---------------------------------------------------------------------------
# Tests: synthesis correctness
# ---------------------------------------------------------------------------

class TestUnitarySynthesis:
    """Verify each synthesised circuit implements its target unitary."""

    @pytest.fixture(scope="class")
    def results(self):
        return load_results()

    @pytest.fixture(scope="class")
    def targets(self):
        return get_target_unitaries()

    def _check_entry(self, results, targets, target_name, gate_set):
        entries = [
            e for e in results["unitary_synthesis"]
            if e["target_name"] == target_name and e["gate_set"] == gate_set
        ]
        assert len(entries) == 1, (
            f"Expected exactly 1 entry for {target_name}/{gate_set}, "
            f"got {len(entries)}"
        )
        entry = entries[0]
        qasm_path = f"/app/{entry['qasm_file']}"
        assert os.path.exists(qasm_path), f"QASM file missing: {qasm_path}"

        from bqskit import Circuit
        circuit = Circuit.from_file(qasm_path)
        computed = circuit.get_unitary().numpy
        target = targets[target_name]
        dist = hs_distance(computed, target)
        assert dist < 1e-4, (
            f"{target_name}/{gate_set}: HS distance {dist:.2e} exceeds 1e-4"
        )

    # --- individual synthesis tests ---

    def test_iswap_cnot_u3(self, results, targets):
        self._check_entry(results, targets, "iswap", "cnot_u3")

    def test_iswap_cz_u3(self, results, targets):
        self._check_entry(results, targets, "iswap", "cz_u3")

    def test_sqrt_swap_cnot_u3(self, results, targets):
        self._check_entry(results, targets, "sqrt_swap", "cnot_u3")

    def test_sqrt_swap_cz_u3(self, results, targets):
        self._check_entry(results, targets, "sqrt_swap", "cz_u3")

    def test_magic_basis_cnot_u3(self, results, targets):
        self._check_entry(results, targets, "magic_basis", "cnot_u3")

    def test_magic_basis_cz_u3(self, results, targets):
        self._check_entry(results, targets, "magic_basis", "cz_u3")

    # --- gate count bounds ---

    def test_two_qubit_gate_upper_bound(self, results):
        """Every 2-qubit unitary is synthesisable with <= 3 two-qubit gates."""
        for entry in results["unitary_synthesis"]:
            assert entry["two_qubit_gate_count"] <= 3, (
                f"{entry['target_name']}/{entry['gate_set']}: "
                f"two-qubit count {entry['two_qubit_gate_count']} exceeds 3"
            )

    def test_two_qubit_count_matches_circuit(self, results):
        """Reported two-qubit count matches the actual QASM circuit."""
        from bqskit import Circuit
        for entry in results["unitary_synthesis"]:
            qasm_path = f"/app/{entry['qasm_file']}"
            if not os.path.exists(qasm_path):
                continue
            circuit = Circuit.from_file(qasm_path)
            actual = sum(1 for op in circuit if op.num_qudits == 2)
            assert actual == entry["two_qubit_gate_count"], (
                f"{entry['target_name']}/{entry['gate_set']}: "
                f"reported {entry['two_qubit_gate_count']}, actual {actual}"
            )

    # --- coverage ---

    def test_covers_all_combinations(self, results):
        combos = {
            (e["target_name"], e["gate_set"])
            for e in results["unitary_synthesis"]
        }
        expected = {
            ("iswap", "cnot_u3"), ("iswap", "cz_u3"),
            ("sqrt_swap", "cnot_u3"), ("sqrt_swap", "cz_u3"),
            ("magic_basis", "cnot_u3"), ("magic_basis", "cz_u3"),
        }
        assert combos == expected, f"Missing combos: {expected - combos}"


# ---------------------------------------------------------------------------
# Tests: 4-qubit circuit compilation
# ---------------------------------------------------------------------------

class TestCircuitCompilation:
    """Verify the compiled 4-qubit circuit."""

    @pytest.fixture(scope="class")
    def results(self):
        return load_results()

    def test_compiled_qasm_exists(self, results):
        qasm_path = f"/app/{results['circuit_compilation']['qasm_file']}"
        assert os.path.exists(qasm_path), f"Compiled QASM missing: {qasm_path}"

    def test_original_cnot_count(self, results):
        """The original circuit has exactly 5 two-qubit gates."""
        assert results["circuit_compilation"]["cnot_count_original"] == 5

    def test_topology_reported_valid(self, results):
        assert results["circuit_compilation"]["topology_valid"] is True

    def test_topology_compliance_independent(self, results):
        """Independently verify every 2-qubit gate respects the linear chain."""
        from bqskit import Circuit
        qasm_path = f"/app/{results['circuit_compilation']['qasm_file']}"
        circuit = Circuit.from_file(qasm_path)
        valid_edges = {(0, 1), (1, 0), (1, 2), (2, 1), (2, 3), (3, 2)}
        for op in circuit:
            if op.num_qudits == 2:
                edge = tuple(op.location)
                assert edge in valid_edges, (
                    f"Two-qubit gate on edge {edge} violates linear topology "
                    f"(allowed: {valid_edges})"
                )

    def test_cnot_count_matches_circuit(self, results):
        """Reported compiled CNOT count matches the actual circuit."""
        from bqskit import Circuit
        qasm_path = f"/app/{results['circuit_compilation']['qasm_file']}"
        circuit = Circuit.from_file(qasm_path)
        actual = sum(1 for op in circuit if op.num_qudits == 2)
        assert actual == results["circuit_compilation"]["cnot_count_compiled"], (
            f"Reported {results['circuit_compilation']['cnot_count_compiled']}, "
            f"actual {actual}"
        )

    def test_compiled_unitary_correctness(self, results):
        """
        The compiled circuit must implement the same unitary as the original,
        up to qubit permutation from routing and global phase.
        """
        from bqskit import Circuit
        qasm_path = f"/app/{results['circuit_compilation']['qasm_file']}"
        compiled_circuit = Circuit.from_file(qasm_path)
        compiled_u = compiled_circuit.get_unitary().numpy

        target_u = build_input_circuit_unitary()

        # Try direct comparison first
        direct_dist = hs_distance(compiled_u, target_u)
        if direct_dist < 1e-3:
            return

        # Account for qubit permutation introduced by routing
        min_dist = min_hs_distance_with_permutations(compiled_u, target_u, 4)
        assert min_dist < 1e-3, (
            f"Compiled circuit unitary does not match original "
            f"(min HS distance over permutations: {min_dist:.2e})"
        )
