
import sys
sys.path.insert(0, "/app")

import json
import numpy as np
import pytest

from engine import (
    Circuit,
    PHI_PLUS, PHI_MINUS, PSI_PLUS, PSI_MINUS,
    initialize_bell_pairs,
    apply_single_qubit_gate,
    apply_two_qubit_gate,
    measure_qubit,
    partial_trace,
    compute_fidelity,
    validate_locc,
    run_distillation,
)


# ── Initialization ──────────────────────────────────────────

class TestInitialization:
    def test_single_pair_pure_phi_plus(self):
        noise = {"phi_plus": 1.0, "psi_plus": 0.0, "phi_minus": 0.0, "psi_minus": 0.0}
        rho = initialize_bell_pairs(1, noise)
        expected = np.outer(PHI_PLUS, PHI_PLUS.conj())
        np.testing.assert_allclose(rho, expected, atol=1e-10)

    def test_single_pair_mixed(self):
        noise = {"phi_plus": 0.75, "psi_plus": 0.25, "phi_minus": 0.0, "psi_minus": 0.0}
        rho = initialize_bell_pairs(1, noise)
        expected = 0.75 * np.outer(PHI_PLUS, PHI_PLUS.conj()) + \
                   0.25 * np.outer(PSI_PLUS, PSI_PLUS.conj())
        np.testing.assert_allclose(rho, expected, atol=1e-10)

    def test_two_pairs_trace_gives_single_pair(self):
        noise = {"phi_plus": 0.7, "psi_plus": 0.3, "phi_minus": 0.0, "psi_minus": 0.0}
        rho = initialize_bell_pairs(2, noise)
        # Pair 1 occupies qubits (1, 2). Trace out pair 0's qubits (0, 3).
        rho_pair1 = partial_trace(rho, [1, 2], 4)
        expected = 0.7 * np.outer(PHI_PLUS, PHI_PLUS.conj()) + \
                   0.3 * np.outer(PSI_PLUS, PSI_PLUS.conj())
        np.testing.assert_allclose(rho_pair1, expected, atol=1e-10)

    def test_density_matrix_properties(self):
        noise = {"phi_plus": 0.6, "psi_plus": 0.2, "phi_minus": 0.1, "psi_minus": 0.1}
        rho = initialize_bell_pairs(2, noise)
        np.testing.assert_allclose(rho, rho.conj().T, atol=1e-10)
        np.testing.assert_allclose(np.trace(rho), 1.0, atol=1e-10)
        eigenvalues = np.linalg.eigvalsh(rho)
        assert np.all(eigenvalues >= -1e-10), f"Negative eigenvalue: {min(eigenvalues)}"

    def test_three_pairs_trace_consistency(self):
        noise = {"phi_plus": 0.65, "psi_plus": 0.15, "phi_minus": 0.15, "psi_minus": 0.05}
        rho = initialize_bell_pairs(3, noise)
        assert rho.shape == (64, 64)
        np.testing.assert_allclose(np.trace(rho), 1.0, atol=1e-10)
        # Output pair is (q2, q3). Trace out q0,q1,q4,q5.
        rho_out = partial_trace(rho, [2, 3], 6)
        expected = (0.65 * np.outer(PHI_PLUS, PHI_PLUS.conj()) +
                    0.15 * np.outer(PSI_PLUS, PSI_PLUS.conj()) +
                    0.15 * np.outer(PHI_MINUS, PHI_MINUS.conj()) +
                    0.05 * np.outer(PSI_MINUS, PSI_MINUS.conj()))
        np.testing.assert_allclose(rho_out, expected, atol=1e-10)


# ── Gate application ────────────────────────────────────────

class TestGates:
    def test_hadamard_transforms_basis(self):
        rho_0 = np.diag([1.0, 0.0]).astype(complex)
        rho_full = np.kron(rho_0, np.eye(2, dtype=complex) / 2)
        rho_h = apply_single_qubit_gate(rho_full, "h", 0, 2)
        rho_q0 = partial_trace(rho_h, [0], 2)
        expected_plus = np.array([[0.5, 0.5], [0.5, 0.5]], dtype=complex)
        np.testing.assert_allclose(rho_q0, expected_plus, atol=1e-10)

    def test_cnot_creates_bell_state(self):
        rho_00 = np.zeros((4, 4), dtype=complex)
        rho_00[0, 0] = 1.0
        rho_h = apply_single_qubit_gate(rho_00, "h", 0, 2)
        rho_bell = apply_two_qubit_gate(rho_h, "cx", 0, 1, 2)
        expected = np.outer(PHI_PLUS, PHI_PLUS.conj())
        np.testing.assert_allclose(rho_bell, expected, atol=1e-10)

    def test_x_gate_flips(self):
        rho_0 = np.diag([1.0, 0.0]).astype(complex)
        rho_x = apply_single_qubit_gate(rho_0, "x", 0, 1)
        expected = np.diag([0.0, 1.0]).astype(complex)
        np.testing.assert_allclose(rho_x, expected, atol=1e-10)

    def test_cnot_nonadjacent(self):
        """CNOT between non-adjacent qubits q0 (ctrl) and q2 (tgt) in 3-qubit system."""
        dim = 8
        rho = np.zeros((dim, dim), dtype=complex)
        rho[4, 4] = 1.0  # |100>
        rho_out = apply_two_qubit_gate(rho, "cx", 0, 2, 3)
        expected = np.zeros((dim, dim), dtype=complex)
        expected[5, 5] = 1.0  # |101> (target q2 flipped)
        np.testing.assert_allclose(rho_out, expected, atol=1e-10)


# ── Measurement ─────────────────────────────────────────────

class TestMeasurement:
    def test_pure_zero(self):
        rho = np.diag([1.0, 0.0]).astype(complex)
        results = measure_qubit(rho, 0, 1)
        assert abs(results[0][0] - 1.0) < 1e-10
        assert abs(results[1][0]) < 1e-10

    def test_superposition(self):
        rho = np.array([[0.5, 0.5], [0.5, 0.5]], dtype=complex)
        results = measure_qubit(rho, 0, 1)
        assert abs(results[0][0] - 0.5) < 1e-10
        assert abs(results[1][0] - 0.5) < 1e-10

    def test_bell_state_measurement(self):
        rho = np.outer(PHI_PLUS, PHI_PLUS.conj())
        results = measure_qubit(rho, 0, 2)
        p0, rho_0 = results[0]
        p1, rho_1 = results[1]
        assert abs(p0 - 0.5) < 1e-10
        assert abs(p1 - 0.5) < 1e-10
        # After measuring q0=0, state is |00>
        np.testing.assert_allclose(rho_0, np.diag([1, 0, 0, 0]).astype(complex), atol=1e-10)


# ── Partial trace ───────────────────────────────────────────

class TestPartialTrace:
    def test_product_state(self):
        rho_a = np.array([[0.7, 0.1], [0.1, 0.3]], dtype=complex)
        rho_b = np.array([[0.6, 0.2], [0.2, 0.4]], dtype=complex)
        rho_ab = np.kron(rho_a, rho_b)
        np.testing.assert_allclose(partial_trace(rho_ab, [0], 2), rho_a, atol=1e-10)
        np.testing.assert_allclose(partial_trace(rho_ab, [1], 2), rho_b, atol=1e-10)

    def test_bell_state_gives_maximally_mixed(self):
        rho_bell = np.outer(PHI_PLUS, PHI_PLUS.conj())
        rho_single = partial_trace(rho_bell, [0], 2)
        np.testing.assert_allclose(rho_single, np.eye(2) / 2, atol=1e-10)

    def test_three_qubit_trace(self):
        rho_a = np.diag([0.8, 0.2]).astype(complex)
        rho_bc = np.outer(PHI_PLUS, PHI_PLUS.conj())
        rho_full = np.kron(rho_a, rho_bc)
        reduced = partial_trace(rho_full, [1, 2], 3)
        np.testing.assert_allclose(reduced, rho_bc, atol=1e-10)


# ── Fidelity ────────────────────────────────────────────────

class TestFidelity:
    def test_phi_plus_is_one(self):
        rho = np.outer(PHI_PLUS, PHI_PLUS.conj())
        assert abs(compute_fidelity(rho) - 1.0) < 1e-10

    def test_psi_plus_is_zero(self):
        rho = np.outer(PSI_PLUS, PSI_PLUS.conj())
        assert abs(compute_fidelity(rho)) < 1e-10

    def test_phi_minus_is_zero(self):
        rho = np.outer(PHI_MINUS, PHI_MINUS.conj())
        assert abs(compute_fidelity(rho)) < 1e-10

    def test_mixed_state(self):
        rho = 0.7 * np.outer(PHI_PLUS, PHI_PLUS.conj()) + \
              0.3 * np.outer(PSI_PLUS, PSI_PLUS.conj())
        assert abs(compute_fidelity(rho) - 0.7) < 1e-10

    def test_four_component_mixture(self):
        rho = (0.5 * np.outer(PHI_PLUS, PHI_PLUS.conj()) +
               0.2 * np.outer(PSI_PLUS, PSI_PLUS.conj()) +
               0.2 * np.outer(PHI_MINUS, PHI_MINUS.conj()) +
               0.1 * np.outer(PSI_MINUS, PSI_MINUS.conj()))
        assert abs(compute_fidelity(rho) - 0.5) < 1e-10


# ── LOCC validation ─────────────────────────────────────────

class TestLOCC:
    def test_valid_same_side_gates(self):
        c = Circuit(4, 3)
        c.add_gate("cx", [0, 1])   # Both Alice (N=2)
        c.add_gate("cx", [2, 3])   # Both Bob
        assert validate_locc(c, 2) is True

    def test_invalid_cross_boundary(self):
        c = Circuit(4, 3)
        c.add_gate("cx", [0, 2])   # Alice q0, Bob q2
        assert validate_locc(c, 2) is False

    def test_invalid_conditional_cross_boundary(self):
        c = Circuit(4, 3)
        c.add_conditional(0, 1, "cx", [1, 2])
        assert validate_locc(c, 2) is False

    def test_single_qubit_always_valid(self):
        c = Circuit(4, 3)
        c.add_gate("h", [0])
        c.add_gate("x", [2])
        c.add_conditional(0, 1, "z", [3])
        assert validate_locc(c, 2) is True

    def test_n3_valid_circuit(self):
        c = Circuit(6, 7)
        c.add_gate("cx", [2, 0])   # Alice: q2->q0
        c.add_gate("cx", [3, 5])   # Bob: q3->q5
        c.add_gate("cx", [2, 1])   # Alice: q2->q1
        c.add_gate("cx", [3, 4])   # Bob: q3->q4
        assert validate_locc(c, 3) is True

    def test_n3_invalid_circuit(self):
        c = Circuit(6, 7)
        c.add_gate("cx", [2, 3])   # q2 is Alice, q3 is Bob for N=3
        assert validate_locc(c, 3) is False


# ── End-to-end distillation (known analytical results) ──────

class TestDistillation:
    def test_d1_bit_flip_n2(self):
        """Bilateral CNOT on bit-flip noise: F_out = F^2/(F^2+(1-F)^2)."""
        c = Circuit(4, 3)
        c.flag_bit = 2
        c.add_gate("cx", [1, 0])
        c.add_gate("cx", [2, 3])
        c.add_measure(0, 0)
        c.add_measure(3, 1)
        c.add_store_xor(2, 0, 1)

        noise = {"phi_plus": 0.75, "psi_plus": 0.25, "phi_minus": 0.0, "psi_minus": 0.0}
        result = run_distillation(c, 2, noise)

        assert abs(result["fidelity"] - 0.9) < 1e-6, \
            f"Expected fidelity 0.9, got {result['fidelity']}"
        assert abs(result["success_probability"] - 0.625) < 1e-6, \
            f"Expected success prob 0.625, got {result['success_probability']}"

    def test_d2_phase_flip_n2(self):
        """Hadamard-rotated bilateral CNOT on phase-flip noise."""
        c = Circuit(4, 3)
        c.flag_bit = 2
        for q in range(4):
            c.add_gate("h", [q])
        c.add_gate("cx", [1, 0])
        c.add_gate("cx", [2, 3])
        c.add_measure(0, 0)
        c.add_measure(3, 1)
        c.add_gate("h", [1])
        c.add_gate("h", [2])
        c.add_store_xor(2, 0, 1)

        noise = {"phi_plus": 0.80, "psi_plus": 0.0, "phi_minus": 0.20, "psi_minus": 0.0}
        result = run_distillation(c, 2, noise)

        expected_f = 0.80 ** 2 / (0.80 ** 2 + 0.20 ** 2)
        assert abs(result["fidelity"] - expected_f) < 1e-4, \
            f"Expected fidelity {expected_f:.6f}, got {result['fidelity']}"
        assert abs(result["success_probability"] - 0.68) < 1e-6, \
            f"Expected success prob 0.68, got {result['success_probability']}"

    def test_d1_bit_flip_n3(self):
        """N=3 recurrence: F_out = F^3/(F^3+(1-F)^3)."""
        c = Circuit(6, 7)
        c.flag_bit = 6
        c.add_gate("cx", [2, 0])
        c.add_gate("cx", [3, 5])
        c.add_gate("cx", [2, 1])
        c.add_gate("cx", [3, 4])
        c.add_measure(0, 0)
        c.add_measure(1, 1)
        c.add_measure(5, 2)
        c.add_measure(4, 3)
        c.add_store_xor(4, 0, 2)
        c.add_store_xor(5, 1, 3)
        c.add_store_or(6, 4, 5)

        noise = {"phi_plus": 0.70, "psi_plus": 0.30, "phi_minus": 0.0, "psi_minus": 0.0}
        result = run_distillation(c, 3, noise)

        expected_f = 0.70 ** 3 / (0.70 ** 3 + 0.30 ** 3)
        expected_p = 0.70 ** 3 + 0.30 ** 3
        assert abs(result["fidelity"] - expected_f) < 1e-4, \
            f"Expected fidelity {expected_f:.6f}, got {result['fidelity']}"
        assert abs(result["success_probability"] - expected_p) < 1e-4, \
            f"Expected success prob {expected_p:.6f}, got {result['success_probability']}"


# ── Scenario solutions ──────────────────────────────────────

class TestScenarioSolutions:
    @pytest.fixture(autouse=True)
    def load_scenarios(self):
        with open("/app/scenarios.json") as f:
            self.scenarios = json.load(f)["scenarios"]

    def _get_circuit(self, scenario_id):
        try:
            from circuits import get_circuit
            return get_circuit(scenario_id)
        except (ImportError, ModuleNotFoundError):
            pytest.skip("circuits.py not found at /app/circuits.py")

    def _run_scenario(self, sid):
        s = next(sc for sc in self.scenarios if sc["id"] == sid)
        circuit = self._get_circuit(sid)
        assert circuit.num_qubits == 2 * s["N"], \
            f"{sid}: circuit has {circuit.num_qubits} qubits, expected {2 * s['N']}"
        assert validate_locc(circuit, s["N"]), \
            f"{sid}: circuit violates LOCC constraints"
        result = run_distillation(circuit, s["N"], s["noise"])
        assert result["fidelity"] >= s["threshold"], \
            f"{sid}: fidelity {result['fidelity']:.6f} < threshold {s['threshold']}"
        assert result["success_probability"] > 0.01, \
            f"{sid}: success probability {result['success_probability']:.6f} too low"

    def test_s1(self):
        self._run_scenario("S1")

    def test_s2(self):
        self._run_scenario("S2")

    def test_s3(self):
        self._run_scenario("S3")

    def test_s4(self):
        self._run_scenario("S4")
