#!/usr/bin/env python3
"""Tests for QPE strategy audit and comparison outputs."""

import json
import os

import numpy as np
import pytest

import qpe_toolbox.estimation as qpe
from qpe_toolbox.hamiltonian import do_dmrg, heisenberg_hamiltonian

# ---------------------------------------------------------------------------
# Precompute reference values (shared across tests)
# ---------------------------------------------------------------------------
H4 = heisenberg_hamiltonian(4)
E0_4, psi0_4 = do_dmrg(H4)
weights_4, lmb_4, L_4, mL_4 = qpe.get_lcu_weights(H4)
eigenvalues_4 = sorted(np.linalg.eigvalsh(H4.to_dense()).tolist())

H2 = heisenberg_hamiltonian(2)
E0_2, _psi0_2 = do_dmrg(H2)
lmb_2 = sum([abs(P[0]) for P in H2.terms])


def _load(filename):
    path = os.path.join("/app/results", filename)
    with open(path) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Test 1: Hamiltonian eigenvalue spectrum
# ---------------------------------------------------------------------------
def test_spectrum():
    data = _load("spectrum.json")

    assert data["n_qubits"] == 4
    assert data["n_terms"] == H4.n_terms

    # Full eigenvalue spectrum must match dense diagonalization
    assert len(data["eigenvalues"]) == 2**4
    assert np.allclose(data["eigenvalues"], eigenvalues_4, atol=1e-10)

    # DMRG ground energy
    assert abs(data["ground_energy_dmrg"] - E0_4) < 1e-8


# ---------------------------------------------------------------------------
# Test 2: LCU decomposition parameters and oracle verification
# ---------------------------------------------------------------------------
def test_lcu_parameters():
    data = _load("lcu_parameters.json")

    # LCU decomposition parameters
    assert abs(data["lambda_norm"] - lmb_4) < 1e-10
    assert data["n_lcu_terms"] == L_4
    assert data["n_auxiliary_qubits"] == mL_4
    assert np.allclose(data["weights"], weights_4, atol=1e-10)

    # Oracle algebraic property verification
    assert data["select_is_unitary"] is True
    assert data["reflection_is_involution"] is True

    # SELECT energy ratio: <psi0|<L| SELECT |L>|psi0> = E0 / lambda
    assert abs(data["select_energy_ratio"] - E0_4 / lmb_4) < 1e-6


# ---------------------------------------------------------------------------
# Test 3: Corrected error bounds (key diagnostic: should differ from initial)
# ---------------------------------------------------------------------------
def test_corrected_bounds():
    data = _load("corrected_bounds.json")

    for m_ph in [2, 3, 4, 5, 6, 7, 8]:
        key = str(m_ph)
        assert key in data, f"Missing entry for m_ph={m_ph}"

        # LCU error bound must match library's estimate_lcu_error
        expected_lcu = qpe.estimate_lcu_error(m_ph, E0_4, lmb_4)
        assert abs(data[key]["lcu_error"] - expected_lcu) < 1e-12, (
            f"m_ph={m_ph}: lcu_error {data[key]['lcu_error']} != {expected_lcu}"
        )

        # Trotter resolution: size_interval / 2^m_ph
        expected_trotter = 2.0 / (2**m_ph)
        assert abs(data[key]["trotter_resolution"] - expected_trotter) < 1e-12

    # Verify corrected bounds are TIGHTER than the initial wrong bounds
    # (the initial analysis omitted the sqrt(1-(E0/lmb)^2) factor)
    initial_wrong_bound_m4 = lmb_4 * 2 * np.pi / 2**4
    corrected_bound_m4 = data["4"]["lcu_error"]
    assert corrected_bound_m4 < initial_wrong_bound_m4, (
        "Corrected LCU bound should be tighter than the initial simplified bound"
    )


# ---------------------------------------------------------------------------
# Test 4: Gate counts (verified against library test suite values)
# ---------------------------------------------------------------------------
def test_gate_counts():
    data = _load("gate_counts.json")

    # Heisenberg-4, n_phase=2, n_trotter_steps=2, trotter_order=1 (default)
    assert data["1qb"] == 540
    assert data["2qb"] == 199
    assert data["3+qb"] == 108
    assert data["total_entangling"] == 307  # 199 + 108


# ---------------------------------------------------------------------------
# Test 5: QPE validation on 2-qubit system (corrected energy extraction)
# ---------------------------------------------------------------------------
def test_qpe_validation():
    data = _load("qpe_validation.json")

    # Verify lambda and ground energy for 2-qubit system
    assert abs(data["lambda_norm"] - lmb_2) < 1e-10
    assert abs(data["ground_energy"] - E0_2) < 1e-8

    # Verify theta -> energy conversion uses correct formula
    energy_from_theta = qpe.get_energy_from_lcu_walk_phase(data["theta"], lmb_2)
    assert abs(energy_from_theta - data["energy"]) < 1e-10

    # The corrected energy must be close to E0 (unlike the buggy sin-based one)
    assert abs(data["energy"] - E0_2) < 0.5, (
        f"Corrected energy {data['energy']} should be close to E0={E0_2}"
    )

    # Verify error bound formula
    delta_e = qpe.estimate_lcu_error(2, E0_2, lmb_2)
    assert abs(data["error_bound"] - delta_e) < 1e-10

    # Verify energy is within error bound
    assert data["energy_matches"] is True


# ---------------------------------------------------------------------------
# Test 6: Recommendation (method comparison for target precision)
# ---------------------------------------------------------------------------
def test_recommendation():
    data = _load("recommendation.json")

    # Compute expected minimum phase qubits for LCU
    expected_lcu_min = None
    for m in range(2, 9):
        if qpe.estimate_lcu_error(m, E0_4, lmb_4) < 0.8:
            expected_lcu_min = m
            break

    assert data["lcu_min_phase_qubits"] == expected_lcu_min, (
        f"LCU min phase qubits: got {data['lcu_min_phase_qubits']}, "
        f"expected {expected_lcu_min}"
    )

    # Compute expected minimum phase qubits for Trotter (size_interval=2)
    expected_trotter_min = None
    for m in range(1, 9):
        if 2.0 / (2**m) < 0.8:
            expected_trotter_min = m
            break

    assert data["trotter_min_phase_qubits"] == expected_trotter_min, (
        f"Trotter min phase qubits: got {data['trotter_min_phase_qubits']}, "
        f"expected {expected_trotter_min}"
    )

    # Must include a method recommendation and justification
    assert "recommended_method" in data
    assert isinstance(data["recommended_method"], str)
    assert len(data["recommended_method"]) > 0

    assert "justification" in data
    assert isinstance(data["justification"], str)
    assert len(data["justification"]) > 10
