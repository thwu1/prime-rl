"""
Tests for entanglement distillation simulation engine.

"""
import json
import os
import sys
import pytest
import numpy as np

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def results():
    with open("/app/results.json") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Results file structure tests
# ---------------------------------------------------------------------------

def test_results_file_exists():
    assert os.path.exists("/app/results.json"), "results.json not found at /app/results.json"


def test_results_all_scenarios_present(results):
    for sid in ["D1", "D2", "D3", "D4", "D5"]:
        assert sid in results, f"Missing scenario {sid}"
        assert "fidelity" in results[sid], f"Missing fidelity for {sid}"
        assert "success_probability" in results[sid], f"Missing success_probability for {sid}"


def test_fidelities_in_valid_range(results):
    for sid in ["D1", "D2", "D3", "D4", "D5"]:
        f = results[sid]["fidelity"]
        assert 0 < f <= 1.0, f"{sid}: fidelity {f} not in (0, 1]"


def test_success_probabilities_in_valid_range(results):
    for sid in ["D1", "D2", "D3", "D4", "D5"]:
        p = results[sid]["success_probability"]
        assert 0 < p <= 1.0, f"{sid}: success_probability {p} not in (0, 1]"


# ---------------------------------------------------------------------------
# Threshold tests
# ---------------------------------------------------------------------------

def test_all_fidelities_exceed_thresholds(results):
    thresholds = {"D1": 0.80, "D2": 0.80, "D3": 0.90, "D4": 0.90, "D5": 0.90}
    for sid, thr in thresholds.items():
        f = results[sid]["fidelity"]
        assert f > thr, f"{sid}: fidelity {f:.6f} does not exceed threshold {thr}"


# ---------------------------------------------------------------------------
# D1: Bit-flip only, N=2. Expected: F=0.9, p=0.625
# ---------------------------------------------------------------------------

def test_d1_fidelity(results):
    assert abs(results["D1"]["fidelity"] - 0.9) < 0.005, (
        f"D1 fidelity {results['D1']['fidelity']:.6f} not close to expected 0.9"
    )


def test_d1_success_probability(results):
    assert abs(results["D1"]["success_probability"] - 0.625) < 0.015, (
        f"D1 success_probability {results['D1']['success_probability']:.6f} not close to expected 0.625"
    )


# ---------------------------------------------------------------------------
# D2: Phase-flip only, N=2. Expected: F=0.9, p=0.625
# ---------------------------------------------------------------------------

def test_d2_fidelity(results):
    assert abs(results["D2"]["fidelity"] - 0.9) < 0.005, (
        f"D2 fidelity {results['D2']['fidelity']:.6f} not close to expected 0.9"
    )


def test_d2_success_probability(results):
    assert abs(results["D2"]["success_probability"] - 0.625) < 0.015, (
        f"D2 success_probability {results['D2']['success_probability']:.6f} not close to expected 0.625"
    )


# ---------------------------------------------------------------------------
# D3: Bit-flip only, N=3. Expected: F=27/28≈0.964286, p=7/16=0.4375
# ---------------------------------------------------------------------------

def test_d3_fidelity(results):
    expected = 27.0 / 28.0
    assert abs(results["D3"]["fidelity"] - expected) < 0.005, (
        f"D3 fidelity {results['D3']['fidelity']:.6f} not close to expected {expected:.6f}"
    )


def test_d3_success_probability(results):
    assert abs(results["D3"]["success_probability"] - 0.4375) < 0.015, (
        f"D3 success_probability {results['D3']['success_probability']:.6f} not close to expected 0.4375"
    )


# ---------------------------------------------------------------------------
# D4: Phase-flip only, N=3. Expected: F=27/28≈0.964286, p=7/16=0.4375
# ---------------------------------------------------------------------------

def test_d4_fidelity(results):
    expected = 27.0 / 28.0
    assert abs(results["D4"]["fidelity"] - expected) < 0.005, (
        f"D4 fidelity {results['D4']['fidelity']:.6f} not close to expected {expected:.6f}"
    )


def test_d4_success_probability(results):
    assert abs(results["D4"]["success_probability"] - 0.4375) < 0.015, (
        f"D4 success_probability {results['D4']['success_probability']:.6f} not close to expected 0.4375"
    )


# ---------------------------------------------------------------------------
# D5: Mixed noise px=pz=0.06, N=5.
# Interleaved protocol: F≈0.9319, p≈0.5809
# Sequential 2+2 only achieves F≈0.886 — the agent must discover that
# interleaving phase and bit checks is essential for mixed noise.
# ---------------------------------------------------------------------------

def test_d5_fidelity_above_strong_threshold(results):
    assert results["D5"]["fidelity"] > 0.92, (
        f"D5 fidelity {results['D5']['fidelity']:.6f} should exceed 0.92 "
        f"(requires interleaved phase/bit distillation, not sequential)"
    )


def test_d5_fidelity_near_optimal(results):
    assert abs(results["D5"]["fidelity"] - 0.9319) < 0.015, (
        f"D5 fidelity {results['D5']['fidelity']:.6f} not near optimal ~0.9319"
    )


def test_d5_success_probability_reasonable(results):
    p = results["D5"]["success_probability"]
    assert 0.30 < p < 0.80, (
        f"D5 success_probability {p:.6f} outside reasonable range (0.30, 0.80)"
    )


# ---------------------------------------------------------------------------
# Engine API: construct_bell_pair_dm
# ---------------------------------------------------------------------------

def test_bell_pair_bit_flip_noise():
    sys.path.insert(0, "/app")
    try:
        from engine import construct_bell_pair_dm
    except (ImportError, AttributeError):
        pytest.skip("construct_bell_pair_dm not available")

    rho = construct_bell_pair_dm(0.25, 0.0)
    assert rho.shape == (4, 4), f"Expected shape (4,4), got {rho.shape}"
    assert abs(np.trace(rho) - 1.0) < 1e-8, f"Trace = {np.trace(rho)}, expected 1.0"

    # Eigenvalues must be non-negative (valid density matrix)
    eigvals = np.linalg.eigvalsh(rho)
    assert np.all(eigvals > -1e-10), f"Density matrix has negative eigenvalue: {eigvals}"

    # Fidelity with Phi+ should equal 1-px = 0.75
    phi_plus = np.array([1, 0, 0, 1], dtype=complex) / np.sqrt(2)
    fid = np.real(phi_plus.conj() @ rho @ phi_plus)
    assert abs(fid - 0.75) < 1e-8, f"Fidelity = {fid}, expected 0.75"


def test_bell_pair_perfect():
    sys.path.insert(0, "/app")
    try:
        from engine import construct_bell_pair_dm
    except (ImportError, AttributeError):
        pytest.skip("construct_bell_pair_dm not available")

    rho = construct_bell_pair_dm(0.0, 0.0)
    phi_plus = np.array([1, 0, 0, 1], dtype=complex) / np.sqrt(2)
    fid = np.real(phi_plus.conj() @ rho @ phi_plus)
    assert abs(fid - 1.0) < 1e-8, f"Perfect pair fidelity = {fid}, expected 1.0"


def test_bell_pair_phase_flip_noise():
    sys.path.insert(0, "/app")
    try:
        from engine import construct_bell_pair_dm
    except (ImportError, AttributeError):
        pytest.skip("construct_bell_pair_dm not available")

    rho = construct_bell_pair_dm(0.0, 0.25)
    phi_plus = np.array([1, 0, 0, 1], dtype=complex) / np.sqrt(2)
    fid = np.real(phi_plus.conj() @ rho @ phi_plus)
    assert abs(fid - 0.75) < 1e-8, f"Fidelity = {fid}, expected 0.75"


def test_bell_pair_mixed_noise():
    sys.path.insert(0, "/app")
    try:
        from engine import construct_bell_pair_dm
    except (ImportError, AttributeError):
        pytest.skip("construct_bell_pair_dm not available")

    rho = construct_bell_pair_dm(0.06, 0.06)
    phi_plus = np.array([1, 0, 0, 1], dtype=complex) / np.sqrt(2)
    fid = np.real(phi_plus.conj() @ rho @ phi_plus)
    expected_fid = (1 - 0.06) * (1 - 0.06)  # 0.8836
    assert abs(fid - expected_fid) < 1e-8, f"Fidelity = {fid}, expected {expected_fid}"


# ---------------------------------------------------------------------------
# Engine API: compute_fidelity_phi_plus
# ---------------------------------------------------------------------------

def test_fidelity_perfect_bell_pair():
    sys.path.insert(0, "/app")
    try:
        from engine import compute_fidelity_phi_plus
    except (ImportError, AttributeError):
        pytest.skip("compute_fidelity_phi_plus not available")

    phi_plus_dm = np.array(
        [[1, 0, 0, 1], [0, 0, 0, 0], [0, 0, 0, 0], [1, 0, 0, 1]],
        dtype=complex
    ) / 2.0
    assert abs(compute_fidelity_phi_plus(phi_plus_dm) - 1.0) < 1e-8


def test_fidelity_maximally_mixed():
    sys.path.insert(0, "/app")
    try:
        from engine import compute_fidelity_phi_plus
    except (ImportError, AttributeError):
        pytest.skip("compute_fidelity_phi_plus not available")

    mixed = np.eye(4, dtype=complex) / 4.0
    assert abs(compute_fidelity_phi_plus(mixed) - 0.25) < 1e-8


def test_fidelity_psi_plus():
    sys.path.insert(0, "/app")
    try:
        from engine import compute_fidelity_phi_plus
    except (ImportError, AttributeError):
        pytest.skip("compute_fidelity_phi_plus not available")

    psi_plus = np.array([0, 1, 1, 0], dtype=complex) / np.sqrt(2)
    psi_plus_dm = np.outer(psi_plus, psi_plus.conj())
    assert abs(compute_fidelity_phi_plus(psi_plus_dm)) < 1e-8


# ---------------------------------------------------------------------------
# Engine API: validate_locc
# ---------------------------------------------------------------------------

def test_locc_valid_alice_side():
    sys.path.insert(0, "/app")
    try:
        from engine import validate_locc
    except (ImportError, AttributeError):
        pytest.skip("validate_locc not available")

    assert validate_locc([(0, 1)], 2) is True, "CNOT within Alice should be valid"


def test_locc_valid_bob_side():
    sys.path.insert(0, "/app")
    try:
        from engine import validate_locc
    except (ImportError, AttributeError):
        pytest.skip("validate_locc not available")

    assert validate_locc([(2, 3)], 2) is True, "CNOT within Bob should be valid"


def test_locc_invalid_cross_boundary():
    sys.path.insert(0, "/app")
    try:
        from engine import validate_locc
    except (ImportError, AttributeError):
        pytest.skip("validate_locc not available")

    assert validate_locc([(1, 2)], 2) is False, "CNOT across boundary should be invalid"


def test_locc_invalid_far_cross():
    sys.path.insert(0, "/app")
    try:
        from engine import validate_locc
    except (ImportError, AttributeError):
        pytest.skip("validate_locc not available")

    assert validate_locc([(0, 3)], 2) is False, "CNOT across boundary should be invalid"


def test_locc_single_qubit_always_valid():
    sys.path.insert(0, "/app")
    try:
        from engine import validate_locc
    except (ImportError, AttributeError):
        pytest.skip("validate_locc not available")

    assert validate_locc([(0,), (3,)], 2) is True, "Single-qubit gates always valid"


def test_locc_mixed_valid_invalid():
    sys.path.insert(0, "/app")
    try:
        from engine import validate_locc
    except (ImportError, AttributeError):
        pytest.skip("validate_locc not available")

    # Mix of valid single-qubit + invalid two-qubit
    assert validate_locc([(0,), (1, 2), (3,)], 2) is False


def test_locc_n3_valid():
    sys.path.insert(0, "/app")
    try:
        from engine import validate_locc
    except (ImportError, AttributeError):
        pytest.skip("validate_locc not available")

    # N=3: Alice 0,1,2; Bob 3,4,5
    assert validate_locc([(0, 1), (1, 2), (3, 4), (4, 5)], 3) is True


def test_locc_n3_invalid():
    sys.path.insert(0, "/app")
    try:
        from engine import validate_locc
    except (ImportError, AttributeError):
        pytest.skip("validate_locc not available")

    assert validate_locc([(2, 3)], 3) is False, "Boundary cross at N=3"
