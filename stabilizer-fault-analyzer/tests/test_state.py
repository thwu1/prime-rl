
"""
Tests for the fault propagation analyzer.

All expected values were computed by exhaustive manual Heisenberg-picture
Pauli tracking through each circuit's suffix gates using the standard
Clifford conjugation rules:
    H: X<->Z, Y->Y (up to phase)
    S: X->Y, Y->X (up to phase), Z->Z
    CX(c,t): X_c -> X_c*X_t, Z_t -> Z_c*Z_t, X_t and Z_c unchanged
"""

import sys
import pytest

sys.path.insert(0, "/app")

from ft_analyzer import propagate_fault, compute_ft_score


# ---------------------------------------------------------------------------
# Unit tests: single-gate Pauli propagation
# ---------------------------------------------------------------------------

class TestSingleGatePropagation:
    """Verify Heisenberg-picture conjugation through individual Clifford gates."""

    def test_h_x_to_z(self):
        assert propagate_fault("H 0", 0, 0, "X", 1) == "Z"

    def test_h_z_to_x(self):
        assert propagate_fault("H 0", 0, 0, "Z", 1) == "X"

    def test_h_y_to_y(self):
        assert propagate_fault("H 0", 0, 0, "Y", 1) == "Y"

    def test_s_x_to_y(self):
        assert propagate_fault("S 0", 0, 0, "X", 1) == "Y"

    def test_s_z_to_z(self):
        assert propagate_fault("S 0", 0, 0, "Z", 1) == "Z"

    def test_s_y_to_x(self):
        assert propagate_fault("S 0", 0, 0, "Y", 1) == "X"

    def test_cx_x_control(self):
        """X on CX control spreads to target."""
        assert propagate_fault("CX 0 1", 0, 0, "X", 2) == "XX"

    def test_cx_z_target(self):
        """Z on CX target spreads to control."""
        assert propagate_fault("CX 0 1", 1, 0, "Z", 2) == "ZZ"

    def test_cx_z_control_unchanged(self):
        assert propagate_fault("CX 0 1", 0, 0, "Z", 2) == "ZI"

    def test_cx_x_target_unchanged(self):
        assert propagate_fault("CX 0 1", 1, 0, "X", 2) == "IX"

    def test_cx_y_control(self):
        """Y on control -> Y_c X_t (up to phase)."""
        assert propagate_fault("CX 0 1", 0, 0, "Y", 2) == "YX"

    def test_cx_y_target(self):
        """Y on target -> Z_c Y_t (up to phase)."""
        assert propagate_fault("CX 0 1", 1, 0, "Y", 2) == "ZY"


# ---------------------------------------------------------------------------
# Integration tests: multi-gate fault propagation
# ---------------------------------------------------------------------------

class TestMultiGatePropagation:
    """Verify fault propagation through multi-gate circuits."""

    def test_bell_fault_0_0_x(self):
        """X before H on Bell circuit: X -> H:Z -> CX:Z_0."""
        assert propagate_fault("H 0\nCX 0 1", 0, 0, "X", 2) == "ZI"

    def test_bell_fault_0_0_z(self):
        """Z before H on Bell circuit: Z -> H:X -> CX:X_0 X_1."""
        assert propagate_fault("H 0\nCX 0 1", 0, 0, "Z", 2) == "XX"

    def test_bell_fault_1_1_z(self):
        """Z on qubit 1 after H: Z_1 -> CX:Z_0 Z_1."""
        assert propagate_fault("H 0\nCX 0 1", 1, 1, "Z", 2) == "ZZ"

    def test_bell_fault_after_all(self):
        """Fault after all gates: E = F itself."""
        assert propagate_fault("H 0\nCX 0 1", 0, 2, "X", 2) == "XI"
        assert propagate_fault("H 0\nCX 0 1", 1, 2, "Z", 2) == "IZ"

    def test_phase_fault_0_1_x(self):
        """X after H on phase circuit: X -> S:Y -> CX:Y_0 X_1."""
        assert propagate_fault("H 0\nS 0\nCX 0 1", 0, 1, "X", 2) == "YX"

    def test_phase_fault_0_0_x(self):
        """X before all on phase circuit: X -> H:Z -> S:Z -> CX:Z_0."""
        assert propagate_fault("H 0\nS 0\nCX 0 1", 0, 0, "X", 2) == "ZI"

    def test_phase_fault_0_0_z(self):
        """Z before all on phase circuit: Z -> H:X -> S:Y -> CX:Y_0 X_1."""
        assert propagate_fault("H 0\nS 0\nCX 0 1", 0, 0, "Z", 2) == "YX"

    def test_flagged_fault_0_2_x(self):
        """X between flag CX pair: X_0 -> CX01:X_0 X_1 -> CX02:X_0 X_1 X_2."""
        circ = "H 0\nCX 0 2\nCX 0 1\nCX 0 2"
        assert propagate_fault(circ, 0, 2, "X", 3) == "XXX"

    def test_flagged_fault_1_2_z(self):
        """Z_1 between flag pair: Z_1 -> CX01:Z_0 Z_1 -> CX02:Z_0 Z_1."""
        circ = "H 0\nCX 0 2\nCX 0 1\nCX 0 2"
        assert propagate_fault(circ, 1, 2, "Z", 3) == "ZZI"

    def test_flagged_fault_2_2_z(self):
        """Z_2 between flag pair: Z_2 -> CX01:Z_2 -> CX02:Z_0 Z_2."""
        circ = "H 0\nCX 0 2\nCX 0 1\nCX 0 2"
        assert propagate_fault(circ, 2, 2, "Z", 3) == "ZIZ"

    def test_flagged_fault_0_1_x(self):
        """X on q0 before first CX02: propagates through all 3 suffix gates."""
        circ = "H 0\nCX 0 2\nCX 0 1\nCX 0 2"
        # X0 -> CX02:X0X2 -> CX01:X0X1X2 -> CX02:X0(X2*X2)X1 = X0X1
        assert propagate_fault(circ, 0, 1, "X", 3) == "XXI"

    def test_ghz_fault_0_0_z(self):
        """Z before H on GHZ: Z -> H:X -> CX01:XX -> CX02:XXX."""
        assert propagate_fault("H 0\nCX 0 1\nCX 0 2", 0, 0, "Z", 3) == "XXX"


# ---------------------------------------------------------------------------
# FT score tests
# ---------------------------------------------------------------------------

class TestFTScore:
    """
    Verify compute_ft_score against hand-computed values.

    Each score was determined by exhaustively enumerating all
    n * (m+1) * 3 single-fault locations, propagating each through
    the circuit suffix, and counting faults that are either
    non-dangerous (data weight <= t) or flagged (X/Y on a flag qubit).
    """

    def test_bell_state(self):
        """
        H 0, CX 0 1. data=[0,1], flag=[], d=3, t=1.
        2 qubits, 2 ops -> 18 faults. 10 safe. Score = 10/18.
        """
        score = compute_ft_score("H 0\nCX 0 1", [0, 1], [], 3)
        assert score == pytest.approx(10 / 18, abs=1e-9)

    def test_flagged_circuit(self):
        """
        H 0, CX 0 2, CX 0 1, CX 0 2. data=[0,1], flag=[2], d=3, t=1.
        3 qubits, 4 ops -> 45 faults. 35 safe. Score = 35/45 = 7/9.
        """
        circ = "H 0\nCX 0 2\nCX 0 1\nCX 0 2"
        score = compute_ft_score(circ, [0, 1], [2], 3)
        assert score == pytest.approx(35 / 45, abs=1e-9)

    def test_ghz_prep(self):
        """
        H 0, CX 0 1, CX 0 2. data=[0,1,2], flag=[], d=3, t=1.
        3 qubits, 3 ops -> 36 faults. 20 safe. Score = 20/36 = 5/9.
        """
        score = compute_ft_score("H 0\nCX 0 1\nCX 0 2", [0, 1, 2], [], 3)
        assert score == pytest.approx(20 / 36, abs=1e-9)

    def test_phase_circuit(self):
        """
        H 0, S 0, CX 0 1. data=[0,1], flag=[], d=3, t=1.
        2 qubits, 3 ops -> 24 faults. 12 safe. Score = 12/24 = 0.5.
        """
        score = compute_ft_score("H 0\nS 0\nCX 0 1", [0, 1], [], 3)
        assert score == pytest.approx(12 / 24, abs=1e-9)

    def test_ft_score_increases_with_flags(self):
        """Adding flag qubits should improve or maintain the FT score."""
        circ_noflag = "H 0\nCX 0 1"
        circ_flagged = "H 0\nCX 0 2\nCX 0 1\nCX 0 2"
        score_noflag = compute_ft_score(circ_noflag, [0, 1], [], 3)
        score_flagged = compute_ft_score(circ_flagged, [0, 1], [2], 3)
        assert score_flagged > score_noflag

    def test_trivial_identity_circuit(self):
        """
        Single qubit identity (no gates). m=0, n=1, 3 faults.
        All E = F (weight 1), t=1 for d=3. All safe. Score = 1.0.
        """
        score = compute_ft_score("", [0], [], 3)
        # With 0 gates, if implementation handles empty circuit, score = 1.0
        # This tests edge case handling
        # Actually stim.Circuit("") has 0 qubits, so 0 faults -> score = 1.0
        assert score == pytest.approx(1.0, abs=1e-9)

    def test_d2_all_dangerous(self):
        """
        With d=2 (t=0), all non-trivial errors are dangerous.
        H 0, CX 0 1. Only faults producing weight-0 errors are safe.
        No flag qubits, all faults produce weight >= 1. Score = 0.
        """
        score = compute_ft_score("H 0\nCX 0 1", [0, 1], [], 2)
        assert score == pytest.approx(0.0, abs=1e-9)


# ---------------------------------------------------------------------------
# Edge cases and packed instruction handling
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """Test handling of packed Stim instructions and other edge cases."""

    def test_packed_cx_instruction(self):
        """CX 0 1 2 3 should be treated as two separate CX gates."""
        # Fault on qubit 2 at layer 0: should propagate through
        # CX(0,1) then CX(2,3).
        # X on q2 -> CX(0,1): unchanged -> CX(2,3): X2 X3.
        result = propagate_fault("CX 0 1 2 3", 2, 0, "X", 4)
        assert result == "IIXX"

    def test_packed_cx_control_spread(self):
        """CX 0 1 2 3: X on q0 at layer 0 -> CX(0,1):X0X1 -> CX(2,3):X0X1."""
        result = propagate_fault("CX 0 1 2 3", 0, 0, "X", 4)
        assert result == "XXII"

    def test_fault_at_final_boundary(self):
        """Fault at j=m (after all gates) should return the fault itself."""
        circ = "H 0\nS 0\nCX 0 1"
        assert propagate_fault(circ, 0, 3, "X", 2) == "XI"
        assert propagate_fault(circ, 0, 3, "Y", 2) == "YI"
        assert propagate_fault(circ, 1, 3, "Z", 2) == "IZ"
