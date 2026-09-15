"""Tests for Zero-Noise Extrapolation implementation."""

import sys
sys.path.insert(0, '/app')

import numpy as np
import pytest

from simulator import Gate, simulate, expectation_value
from circuits import (
    ghz_circuit, mirror_circuit, identity_circuit, random_clifford_circuit,
)
from observables import ground_state_projector, z_observable

from zne import (
    fold_global,
    fold_gates,
    richardson_extrapolate,
    polynomial_extrapolate,
    exponential_extrapolate,
    adaptive_extrapolate,
    execute_with_zne,
)


# ---------------------------------------------------------------------------
# Gate folding — global
# ---------------------------------------------------------------------------
class TestFoldGlobal:
    def test_scale_1_preserves_length(self):
        circ = [Gate('H', (0,)), Gate('CNOT', (0, 1))]
        folded = fold_global(circ, 1)
        assert len(folded) == len(circ)

    def test_scale_3_triples_length(self):
        circ = [Gate('H', (0,)), Gate('X', (0,))]
        folded = fold_global(circ, 3)
        assert len(folded) == 3 * len(circ)

    def test_scale_5_quintuples_length(self):
        circ = [Gate('H', (0,)), Gate('T', (0,))]
        folded = fold_global(circ, 5)
        assert len(folded) == 5 * len(circ)

    def test_preserves_unitary_1qubit(self):
        circ = [Gate('H', (0,)), Gate('T', (0,)), Gate('H', (0,))]
        rho_orig = simulate(circ, 1)
        for sf in [3, 5, 7]:
            rho_folded = simulate(fold_global(circ, sf), 1)
            assert np.allclose(rho_orig, rho_folded, atol=1e-10), \
                f"Global fold at scale_factor={sf} changed noiseless state"

    def test_preserves_unitary_2qubit(self):
        circ = [Gate('H', (0,)), Gate('CNOT', (0, 1)), Gate('T', (1,))]
        rho_orig = simulate(circ, 2)
        rho_folded = simulate(fold_global(circ, 3), 2)
        assert np.allclose(rho_orig, rho_folded, atol=1e-10)

    def test_rejects_even(self):
        with pytest.raises(ValueError):
            fold_global([Gate('H', (0,))], 2)

    def test_rejects_zero(self):
        with pytest.raises(ValueError):
            fold_global([Gate('H', (0,))], 0)

    def test_rejects_negative(self):
        with pytest.raises(ValueError):
            fold_global([Gate('H', (0,))], -1)


# ---------------------------------------------------------------------------
# Gate folding — per-gate
# ---------------------------------------------------------------------------
class TestFoldGates:
    def test_scale_1_preserves_length(self):
        circ = [Gate('H', (0,)), Gate('X', (0,))]
        assert len(fold_gates(circ, 1)) == len(circ)

    def test_scale_3_triples_length(self):
        circ = [Gate('H', (0,)), Gate('X', (0,))]
        assert len(fold_gates(circ, 3)) == 3 * len(circ)

    def test_preserves_unitary(self):
        circ = [Gate('H', (0,)), Gate('T', (0,)), Gate('S', (0,))]
        rho_orig = simulate(circ, 1)
        for sf in [3, 5]:
            rho_folded = simulate(fold_gates(circ, sf), 1)
            assert np.allclose(rho_orig, rho_folded, atol=1e-10)

    def test_gate_adjoint_structure(self):
        """T gate folded at scale=3 must produce T · T† · T."""
        circ = [Gate('T', (0,))]
        folded = fold_gates(circ, 3)
        assert len(folded) == 3
        # First and last must be T
        assert folded[0].name == 'T'
        assert folded[2].name == 'T'
        # Middle must be the adjoint of T (check via matrix)
        T_mat = Gate('T', (0,)).matrix()
        mid_mat = folded[1].matrix()
        assert np.allclose(mid_mat, T_mat.conj().T, atol=1e-12), \
            "Middle gate is not T†"

    def test_cnot_folding(self):
        """CNOT is self-adjoint: folding should produce three CNOTs."""
        circ = [Gate('CNOT', (0, 1))]
        folded = fold_gates(circ, 3)
        assert len(folded) == 3
        assert all(g.name == 'CNOT' for g in folded)


# ---------------------------------------------------------------------------
# Richardson extrapolation
# ---------------------------------------------------------------------------
class TestRichardsonExtrapolation:
    def test_exact_linear(self):
        """2 points on a line → exact f(0)."""
        sf = [1.0, 3.0]
        vals = [2.0 - 0.3 * s for s in sf]
        assert abs(richardson_extrapolate(sf, vals) - 2.0) < 1e-10

    def test_exact_quadratic(self):
        """3 points on a parabola → exact f(0)."""
        sf = [1.0, 3.0, 5.0]
        vals = [1.0 - 0.5 * s + 0.1 * s ** 2 for s in sf]
        assert abs(richardson_extrapolate(sf, vals) - 1.0) < 1e-10

    def test_exact_cubic(self):
        """4 points on a cubic → exact f(0)."""
        sf = [1.0, 3.0, 5.0, 7.0]
        vals = [0.5 + 0.2 * s - 0.1 * s ** 2 + 0.01 * s ** 3 for s in sf]
        assert abs(richardson_extrapolate(sf, vals) - 0.5) < 1e-9

    def test_nonstandard_scale_factors(self):
        sf = [1.0, 2.0, 4.0]
        vals = [3.0 - s for s in sf]
        assert abs(richardson_extrapolate(sf, vals) - 3.0) < 1e-10

    def test_length_mismatch_raises(self):
        with pytest.raises(ValueError):
            richardson_extrapolate([1.0, 2.0], [0.5])


# ---------------------------------------------------------------------------
# Polynomial extrapolation
# ---------------------------------------------------------------------------
class TestPolynomialExtrapolation:
    def test_linear_fit(self):
        sf = [1.0, 3.0, 5.0]
        vals = [2.0 - 0.3 * s for s in sf]
        assert abs(polynomial_extrapolate(sf, vals, 1) - 2.0) < 1e-10

    def test_quadratic_fit(self):
        sf = [1.0, 2.0, 3.0, 4.0, 5.0]
        vals = [1.0 - 0.5 * s + 0.1 * s ** 2 for s in sf]
        assert abs(polynomial_extrapolate(sf, vals, 2) - 1.0) < 1e-8

    def test_order_too_high_raises(self):
        with pytest.raises(ValueError):
            polynomial_extrapolate([1.0, 2.0], [0.5, 0.3], 2)


# ---------------------------------------------------------------------------
# Exponential extrapolation
# ---------------------------------------------------------------------------
class TestExponentialExtrapolation:
    def test_known_exponential(self):
        """f(λ) = 0.5 + 0.5·exp(-0.3λ), f(0) = 1.0"""
        sf = [1.0, 2.0, 3.0, 4.0, 5.0]
        vals = [0.5 + 0.5 * np.exp(-0.3 * s) for s in sf]
        result = exponential_extrapolate(sf, vals)
        assert abs(result - 1.0) < 0.02

    def test_with_known_asymptote(self):
        sf = [1.0, 2.0, 3.0, 4.0, 5.0]
        vals = [0.5 + 0.5 * np.exp(-0.3 * s) for s in sf]
        result = exponential_extrapolate(sf, vals, asymptote=0.5)
        assert abs(result - 1.0) < 0.01

    def test_fast_decay(self):
        """f(λ) = 0.2 + 0.8·exp(-0.5λ), f(0) = 1.0"""
        sf = [1.0, 2.0, 3.0, 4.0, 5.0]
        vals = [0.2 + 0.8 * np.exp(-0.5 * s) for s in sf]
        result = exponential_extrapolate(sf, vals)
        assert abs(result - 1.0) < 0.05


# ---------------------------------------------------------------------------
# Adaptive extrapolation
# ---------------------------------------------------------------------------
class TestAdaptiveExtrapolation:
    def test_polynomial_data_selects_polynomial_family(self):
        """Polynomial data should be handled by Richardson or polynomial."""
        sf = [1.0, 2.0, 3.0, 4.0, 5.0]
        vals = [1.0 - 0.5 * s + 0.1 * s ** 2 for s in sf]
        result, method = adaptive_extrapolate(sf, vals)
        assert abs(result - 1.0) < 0.05
        assert method in ('richardson', 'polynomial_1', 'polynomial_2')

    def test_exponential_data_selects_exponential(self):
        """Strongly exponential data should select 'exponential'."""
        sf = [1.0, 2.0, 3.0, 4.0, 5.0]
        vals = [0.5 + 0.5 * np.exp(-0.5 * s) for s in sf]
        result, method = adaptive_extrapolate(sf, vals)
        assert abs(result - 1.0) < 0.1
        assert method == 'exponential'

    def test_returns_valid_method_name(self):
        sf = [1.0, 3.0, 5.0, 7.0, 9.0]
        vals = [0.9, 0.7, 0.55, 0.42, 0.35]
        _, method = adaptive_extrapolate(sf, vals)
        assert method in ('richardson', 'polynomial_1', 'polynomial_2',
                          'exponential')


# ---------------------------------------------------------------------------
# Full ZNE pipeline
# ---------------------------------------------------------------------------
class TestExecuteWithZNE:
    def test_identity_circuit_richardson(self):
        """ZNE with Richardson improves identity-circuit expectation."""
        circ = identity_circuit(1, 5)  # 10 X-X pairs
        obs = ground_state_projector(1)
        noise = 0.03

        ideal = expectation_value(simulate(circ, 1, noise_level=0.0), obs)
        noisy = expectation_value(simulate(circ, 1, noise_level=noise), obs)
        zne_val = execute_with_zne(circ, 1, obs, noise,
                                   scale_factors=[1, 3, 5],
                                   extrapolation='richardson')
        assert abs(ideal - 1.0) < 1e-10, "Sanity: ideal should be 1"
        assert abs(zne_val - ideal) < abs(noisy - ideal), \
            f"ZNE ({zne_val:.6f}) not closer to ideal ({ideal:.6f}) " \
            f"than noisy ({noisy:.6f})"

    def test_mirror_circuit_richardson(self):
        """ZNE on a mirror circuit (implements identity)."""
        base = [Gate('H', (0,)), Gate('T', (0,)), Gate('S', (0,))]
        circ = mirror_circuit(base)
        obs = ground_state_projector(1)
        noise = 0.03

        ideal = expectation_value(simulate(circ, 1, noise_level=0.0), obs)
        noisy = expectation_value(simulate(circ, 1, noise_level=noise), obs)
        zne_val = execute_with_zne(circ, 1, obs, noise,
                                   scale_factors=[1, 3, 5],
                                   extrapolation='richardson')
        assert abs(ideal - 1.0) < 1e-10
        assert abs(zne_val - ideal) < abs(noisy - ideal)

    def test_per_gate_folding(self):
        """ZNE with per-gate folding also improves results."""
        circ = identity_circuit(1, 5)
        obs = ground_state_projector(1)
        noise = 0.03

        ideal = expectation_value(simulate(circ, 1, noise_level=0.0), obs)
        noisy = expectation_value(simulate(circ, 1, noise_level=noise), obs)
        zne_val = execute_with_zne(circ, 1, obs, noise,
                                   scale_factors=[1, 3, 5],
                                   extrapolation='richardson',
                                   fold_method='gates')
        assert abs(zne_val - ideal) < abs(noisy - ideal)

    def test_polynomial_extrapolation_method(self):
        circ = identity_circuit(1, 5)
        obs = ground_state_projector(1)
        noise = 0.03

        ideal = expectation_value(simulate(circ, 1, noise_level=0.0), obs)
        noisy = expectation_value(simulate(circ, 1, noise_level=noise), obs)
        zne_val = execute_with_zne(circ, 1, obs, noise,
                                   scale_factors=[1, 3, 5],
                                   extrapolation='polynomial_2')
        assert abs(zne_val - ideal) < abs(noisy - ideal)

    def test_exponential_extrapolation_method(self):
        circ = identity_circuit(1, 5)
        obs = ground_state_projector(1)
        noise = 0.03

        ideal = expectation_value(simulate(circ, 1, noise_level=0.0), obs)
        noisy = expectation_value(simulate(circ, 1, noise_level=noise), obs)
        zne_val = execute_with_zne(circ, 1, obs, noise,
                                   scale_factors=[1, 3, 5, 7, 9],
                                   extrapolation='exponential')
        assert abs(zne_val - ideal) < abs(noisy - ideal)

    def test_adaptive_extrapolation_method(self):
        circ = identity_circuit(1, 5)
        obs = ground_state_projector(1)
        noise = 0.03

        ideal = expectation_value(simulate(circ, 1, noise_level=0.0), obs)
        noisy = expectation_value(simulate(circ, 1, noise_level=noise), obs)
        zne_val = execute_with_zne(circ, 1, obs, noise,
                                   scale_factors=[1, 3, 5, 7, 9],
                                   extrapolation='adaptive')
        assert abs(zne_val - ideal) < abs(noisy - ideal)

    def test_2qubit_mirror_circuit(self):
        """ZNE works on a 2-qubit mirror circuit."""
        base = [Gate('H', (0,)), Gate('CNOT', (0, 1)), Gate('T', (1,))]
        circ = mirror_circuit(base)
        obs = ground_state_projector(2)
        noise = 0.02

        ideal = expectation_value(simulate(circ, 2, noise_level=0.0), obs)
        noisy = expectation_value(simulate(circ, 2, noise_level=noise), obs)
        zne_val = execute_with_zne(circ, 2, obs, noise,
                                   scale_factors=[1, 3, 5],
                                   extrapolation='richardson',
                                   fold_method='global')
        assert abs(ideal - 1.0) < 1e-10
        assert abs(zne_val - ideal) < abs(noisy - ideal)


# ---------------------------------------------------------------------------
# Observable variety
# ---------------------------------------------------------------------------
class TestObservableVariety:
    def test_z_observable_zne(self):
        """ZNE works with a Z-basis observable."""
        circ = [Gate('RX', (0,), (0.8,))]
        circ = circ + [Gate('X', (0,)), Gate('X', (0,))] * 5  # pad depth
        obs = z_observable(0, 1)
        noise = 0.03

        ideal = expectation_value(simulate(circ, 1, noise_level=0.0), obs)
        noisy = expectation_value(simulate(circ, 1, noise_level=noise), obs)

        if abs(noisy - ideal) > 0.005:
            zne_val = execute_with_zne(circ, 1, obs, noise,
                                       scale_factors=[1, 3, 5],
                                       extrapolation='richardson')
            assert abs(zne_val - ideal) < abs(noisy - ideal)


# ---------------------------------------------------------------------------
# Noise monotonicity (sanity check for folding)
# ---------------------------------------------------------------------------
class TestNoiseMonotonicity:
    def test_more_folding_more_noise(self):
        """Expectation value should degrade with higher scale factor."""
        circ = identity_circuit(1, 5)
        obs = ground_state_projector(1)
        noise = 0.03
        fold_fn = fold_global

        prev_val = 1.0
        for sf in [1, 3, 5, 7]:
            rho = simulate(fold_fn(circ, sf), 1, noise_level=noise)
            val = expectation_value(rho, obs)
            assert val < prev_val + 1e-10, \
                f"Expectation should decrease: sf={sf} gave {val} >= {prev_val}"
            prev_val = val
