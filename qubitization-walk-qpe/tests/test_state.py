"""
Tests for the qubitization-based QPE framework.

Verifies mathematical invariants of the LCU walk operator construction
and QPE energy extraction across three Hamiltonian systems.
"""

import sys
sys.path.insert(0, "/app")

import numpy as np
import pytest
import json
import os

from qubitization import (
    pauli_to_matrix,
    pauli_string_to_matrix,
    build_hamiltonian,
    lcu_decompose,
    build_prepare_unitary,
    build_select_operator,
    build_reflection_operator,
    build_walk_operator,
    eigenphase_to_energy,
    simulate_qpe,
    compute_min_phase_bits,
)

# ---------------------------------------------------------------------------
# Test system definitions
# ---------------------------------------------------------------------------

HEISENBERG_2 = {
    "n_qubits": 2,
    "terms": [
        {"coeff": 0.25, "paulis": "XX"},
        {"coeff": 0.25, "paulis": "YY"},
        {"coeff": 0.25, "paulis": "ZZ"},
    ],
}

MIXED_SIGNS = {
    "n_qubits": 2,
    "terms": [
        {"coeff": 0.5, "paulis": "ZZ"},
        {"coeff": -0.3, "paulis": "XI"},
        {"coeff": 0.4, "paulis": "IX"},
        {"coeff": -0.2, "paulis": "YY"},
    ],
}

HEISENBERG_3 = {
    "n_qubits": 3,
    "terms": [
        {"coeff": 0.25, "paulis": "XXI"},
        {"coeff": 0.25, "paulis": "YYI"},
        {"coeff": 0.25, "paulis": "ZZI"},
        {"coeff": 0.25, "paulis": "IXX"},
        {"coeff": 0.25, "paulis": "IYY"},
        {"coeff": 0.25, "paulis": "IZZ"},
    ],
}

ALL_SYSTEMS = [
    ("heisenberg_2", HEISENBERG_2),
    ("mixed_signs", MIXED_SIGNS),
    ("heisenberg_3", HEISENBERG_3),
]


# ---------------------------------------------------------------------------
# I. Pauli algebra
# ---------------------------------------------------------------------------

class TestPauliMatrices:
    def test_single_paulis(self):
        I = np.eye(2)
        X = np.array([[0, 1], [1, 0]], dtype=complex)
        Y = np.array([[0, -1j], [1j, 0]], dtype=complex)
        Z = np.array([[1, 0], [0, -1]], dtype=complex)

        assert np.allclose(pauli_to_matrix("I"), I)
        assert np.allclose(pauli_to_matrix("X"), X)
        assert np.allclose(pauli_to_matrix("Y"), Y)
        assert np.allclose(pauli_to_matrix("Z"), Z)

    def test_pauli_string_tensor_product(self):
        X = np.array([[0, 1], [1, 0]], dtype=complex)
        Y = np.array([[0, -1j], [1j, 0]], dtype=complex)
        Z = np.array([[1, 0], [0, -1]], dtype=complex)
        I = np.eye(2, dtype=complex)

        assert np.allclose(pauli_string_to_matrix("XX"), np.kron(X, X))
        assert np.allclose(pauli_string_to_matrix("ZZ"), np.kron(Z, Z))
        assert np.allclose(pauli_string_to_matrix("XI"), np.kron(X, I))
        assert np.allclose(
            pauli_string_to_matrix("YYI"), np.kron(np.kron(Y, Y), I)
        )

    def test_pauli_string_self_inverse(self):
        """Every Pauli string P satisfies P^2 = I."""
        for paulis in ["XX", "YY", "ZZ", "XI", "IX", "XXI", "IYY"]:
            P = pauli_string_to_matrix(paulis)
            assert np.allclose(P @ P, np.eye(P.shape[0]), atol=1e-12)


# ---------------------------------------------------------------------------
# II. Hamiltonian construction
# ---------------------------------------------------------------------------

class TestHamiltonianConstruction:
    def test_heisenberg_2_eigenvalues(self):
        """2-qubit Heisenberg: eigenvalues = [-3/4, 1/4, 1/4, 1/4]."""
        H = build_hamiltonian(HEISENBERG_2["terms"], 2)
        evals = np.sort(np.linalg.eigvalsh(H))
        expected = np.array([-0.75, 0.25, 0.25, 0.25])
        assert np.allclose(evals, expected, atol=1e-12)

    def test_hermiticity(self):
        for name, system in ALL_SYSTEMS:
            H = build_hamiltonian(system["terms"], system["n_qubits"])
            assert np.allclose(H, H.conj().T, atol=1e-12), f"{name}: not Hermitian"

    def test_heisenberg_3_ground_energy(self):
        """3-qubit open Heisenberg chain ground state energy is -1.0."""
        H = build_hamiltonian(HEISENBERG_3["terms"], 3)
        E0 = np.min(np.linalg.eigvalsh(H))
        assert np.isclose(E0, -1.0, atol=1e-10)


# ---------------------------------------------------------------------------
# III. LCU decomposition
# ---------------------------------------------------------------------------

class TestLCUDecomposition:
    def test_heisenberg_2_parameters(self):
        weights, signs, lmb, L, m_L = lcu_decompose(HEISENBERG_2["terms"])
        assert np.isclose(lmb, 0.75)
        assert L == 3
        assert m_L == 2
        assert len(weights) == 4  # padded to 2^2
        assert weights[3] == 0.0  # padding
        assert np.all(signs[:3] == 1.0)

    def test_mixed_signs_parameters(self):
        weights, signs, lmb, L, m_L = lcu_decompose(MIXED_SIGNS["terms"])
        assert np.isclose(lmb, 1.4)
        assert L == 4
        assert m_L == 2
        assert len(weights) == 4
        expected_signs = np.array([1.0, -1.0, 1.0, -1.0])
        assert np.allclose(signs[:4], expected_signs)

    def test_heisenberg_3_parameters(self):
        weights, signs, lmb, L, m_L = lcu_decompose(HEISENBERG_3["terms"])
        assert np.isclose(lmb, 1.5)
        assert L == 6
        assert m_L == 3
        assert len(weights) == 8  # padded to 2^3

    def test_weights_positive(self):
        for name, system in ALL_SYSTEMS:
            weights, _, _, _, _ = lcu_decompose(system["terms"])
            assert np.all(weights >= 0), f"{name}: negative weights"


# ---------------------------------------------------------------------------
# IV. PREPARE oracle
# ---------------------------------------------------------------------------

class TestPrepareOracle:
    @pytest.mark.parametrize("name,system", ALL_SYSTEMS)
    def test_unitarity(self, name, system):
        weights, _, lmb, _, m_L = lcu_decompose(system["terms"])
        V = build_prepare_unitary(weights, lmb)
        dim = 2 ** m_L
        assert np.allclose(V @ V.conj().T, np.eye(dim), atol=1e-10), \
            f"{name}: V V^dag != I"
        assert np.allclose(V.conj().T @ V, np.eye(dim), atol=1e-10), \
            f"{name}: V^dag V != I"

    @pytest.mark.parametrize("name,system", ALL_SYSTEMS)
    def test_correct_state(self, name, system):
        """V|0> must equal |L> = sum_l sqrt(w_l / lambda) |l> (up to global phase)."""
        weights, _, lmb, _, m_L = lcu_decompose(system["terms"])
        V = build_prepare_unitary(weights, lmb)
        dim = 2 ** m_L

        e0 = np.zeros(dim, dtype=complex)
        e0[0] = 1.0
        L_state = V @ e0

        expected = np.sqrt(weights / lmb).astype(complex)
        overlap = abs(np.dot(L_state.conj(), expected))
        assert np.isclose(overlap, 1.0, atol=1e-10), \
            f"{name}: |<L_actual|L_expected>| = {overlap}"


# ---------------------------------------------------------------------------
# V. SELECT oracle
# ---------------------------------------------------------------------------

class TestSelectOracle:
    @pytest.mark.parametrize("name,system", ALL_SYSTEMS)
    def test_self_inverse(self, name, system):
        """SELECT^2 = I (each block is a signed Pauli string, hence involutory)."""
        _, _, _, _, m_L = lcu_decompose(system["terms"])
        S = build_select_operator(system["terms"], system["n_qubits"], m_L)
        dim = S.shape[0]
        assert np.allclose(S @ S, np.eye(dim), atol=1e-10), \
            f"{name}: SELECT^2 != I"

    @pytest.mark.parametrize("name,system", ALL_SYSTEMS)
    def test_lcu_relation(self, name, system):
        """<L| tensor I  .  SELECT  .  |L> tensor I  =  H / lambda."""
        weights, _, lmb, _, m_L = lcu_decompose(system["terms"])
        V = build_prepare_unitary(weights, lmb)
        S = build_select_operator(system["terms"], system["n_qubits"], m_L)

        dim_anc = 2 ** m_L
        dim_sys = 2 ** system["n_qubits"]

        e0 = np.zeros(dim_anc, dtype=complex)
        e0[0] = 1.0
        L_state = V @ e0

        # <L|SELECT|L> restricted to the system subspace
        H_over_lmb = np.zeros((dim_sys, dim_sys), dtype=complex)
        for a in range(dim_anc):
            for b in range(dim_anc):
                block = S[a * dim_sys:(a + 1) * dim_sys,
                          b * dim_sys:(b + 1) * dim_sys]
                H_over_lmb += L_state[a].conj() * L_state[b] * block

        H_exact = build_hamiltonian(system["terms"], system["n_qubits"])
        assert np.allclose(H_over_lmb, H_exact / lmb, atol=1e-10), \
            f"{name}: LCU relation <L|S|L> != H/lambda"


# ---------------------------------------------------------------------------
# VI. Walk operator
# ---------------------------------------------------------------------------

class TestWalkOperator:
    @pytest.mark.parametrize("name,system", ALL_SYSTEMS)
    def test_unitarity(self, name, system):
        W, _, _ = build_walk_operator(system["terms"], system["n_qubits"])
        dim = W.shape[0]
        assert np.allclose(W @ W.conj().T, np.eye(dim), atol=1e-10), \
            f"{name}: W W^dag != I"

    @pytest.mark.parametrize("name,system", ALL_SYSTEMS)
    def test_eigenphase_energy_relation(self, name, system):
        """For each H eigenvalue E_k, W has an eigenvalue exp(i * arccos(E_k/lambda))."""
        W, lmb, _ = build_walk_operator(system["terms"], system["n_qubits"])
        H = build_hamiltonian(system["terms"], system["n_qubits"])

        evals_H = np.linalg.eigvalsh(H)
        unique_evals = sorted(set(np.round(evals_H, 8)))

        evals_W = np.linalg.eigvals(W)

        for E_k in unique_evals:
            ratio = np.clip(E_k / lmb, -1.0, 1.0)
            expected_ev = np.exp(1j * np.arccos(ratio))

            min_dist = min(abs(ev - expected_ev) for ev in evals_W)
            assert min_dist < 1e-6, \
                f"{name}: no walk eigenvalue near exp(i*arccos({ratio:.4f})) for E={E_k}"


# ---------------------------------------------------------------------------
# VII. QPE energy extraction
# ---------------------------------------------------------------------------

class TestQPE:
    @staticmethod
    def _prepare_initial_state(system):
        """Build |L>|psi_0> for QPE."""
        terms = system["terms"]
        n_qubits = system["n_qubits"]

        weights, _, lmb, _, m_L = lcu_decompose(terms)
        V = build_prepare_unitary(weights, lmb)

        H = build_hamiltonian(terms, n_qubits)
        _, evecs = np.linalg.eigh(H)
        psi0 = evecs[:, 0]

        dim_anc = 2 ** m_L
        e0 = np.zeros(dim_anc, dtype=complex)
        e0[0] = 1.0
        L_state = V @ e0

        return np.kron(L_state, psi0), np.linalg.eigvalsh(H)[0], lmb

    @pytest.mark.parametrize("name,system", ALL_SYSTEMS)
    def test_ground_energy_extraction(self, name, system):
        """QPE with 6 phase qubits recovers the ground energy within tolerance."""
        W, lmb, _ = build_walk_operator(system["terms"], system["n_qubits"])
        initial_state, E0_exact, _ = self._prepare_initial_state(system)

        n_phase = 6
        probs = simulate_qpe(W, initial_state, n_phase)

        best_m = int(np.argmax(probs))
        theta = best_m / 2 ** n_phase
        E_qpe = eigenphase_to_energy(theta, lmb)

        assert np.isclose(E_qpe, E0_exact, atol=0.1), \
            f"{name}: QPE energy {E_qpe:.6f} != exact {E0_exact:.6f}"

    def test_heisenberg_2_exact_phase(self):
        """
        For 2-qubit Heisenberg the ground-state eigenphase is exactly 0.5
        (arccos(-1) / 2pi), so QPE gives exact energy for any n_phase.
        """
        W, lmb, _ = build_walk_operator(HEISENBERG_2["terms"], 2)
        initial_state, _, _ = self._prepare_initial_state(HEISENBERG_2)

        for n_phase in [2, 4]:
            probs = simulate_qpe(W, initial_state, n_phase)
            best_m = int(np.argmax(probs))
            theta = best_m / 2 ** n_phase
            E_qpe = eigenphase_to_energy(theta, lmb)
            assert np.isclose(E_qpe, -0.75, atol=1e-8), \
                f"n_phase={n_phase}: E_qpe={E_qpe} != -0.75"


# ---------------------------------------------------------------------------
# VIII. Energy formula and resource estimation
# ---------------------------------------------------------------------------

class TestEnergyFormula:
    def test_eigenphase_to_energy_basic(self):
        assert np.isclose(eigenphase_to_energy(0.0, 1.0), 1.0)
        assert np.isclose(eigenphase_to_energy(0.5, 0.75), -0.75)
        assert np.isclose(eigenphase_to_energy(0.25, 2.0), 0.0, atol=1e-12)

    def test_min_phase_bits_degenerate(self):
        # E0/lambda = -1 -> sin factor = 0 -> any n_phase works
        result = compute_min_phase_bits(-0.75, 0.75, 0.01)
        assert 1 <= result <= 3

    def test_min_phase_bits_monotone(self):
        bits_coarse = compute_min_phase_bits(-0.5, 1.0, 0.1)
        bits_fine = compute_min_phase_bits(-0.5, 1.0, 0.01)
        assert bits_fine >= bits_coarse


# ---------------------------------------------------------------------------
# IX. Results file
# ---------------------------------------------------------------------------

class TestResultsFile:
    def test_results_exist(self):
        assert os.path.exists("/app/results.json"), "results.json not found"

    def test_results_structure(self):
        with open("/app/results.json") as f:
            results = json.load(f)

        for sys_name in ["heisenberg_2", "mixed_signs", "heisenberg_3"]:
            assert sys_name in results, f"Missing system: {sys_name}"
            r = results[sys_name]
            for key in ["lambda", "L", "m_L", "ground_energy_exact",
                        "qpe_ground_energy", "min_phase_bits"]:
                assert key in r, f"{sys_name}: missing key '{key}'"

    def test_results_values(self):
        with open("/app/results.json") as f:
            results = json.load(f)

        # Heisenberg-2
        h2 = results["heisenberg_2"]
        assert np.isclose(h2["lambda"], 0.75, atol=1e-10)
        assert h2["L"] == 3
        assert h2["m_L"] == 2
        assert np.isclose(h2["ground_energy_exact"], -0.75, atol=1e-10)
        assert np.isclose(h2["qpe_ground_energy"], -0.75, atol=0.05)

        # Heisenberg-3
        h3 = results["heisenberg_3"]
        assert np.isclose(h3["lambda"], 1.5, atol=1e-10)
        assert h3["L"] == 6
        assert h3["m_L"] == 3
        assert np.isclose(h3["ground_energy_exact"], -1.0, atol=1e-10)
        assert np.isclose(h3["qpe_ground_energy"], -1.0, atol=0.1)

        # Mixed-signs
        ms = results["mixed_signs"]
        assert np.isclose(ms["lambda"], 1.4, atol=1e-10)
        assert ms["L"] == 4
        assert ms["m_L"] == 2
        assert ms["ground_energy_exact"] < 0
        assert np.isclose(ms["qpe_ground_energy"],
                          ms["ground_energy_exact"], atol=0.1)
