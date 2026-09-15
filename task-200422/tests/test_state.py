"""Tests for rotated surface code QEC performance evaluation."""

import json
import math
import os

import pytest
import stim

NOISE_PARAMS = {
    'after_clifford_depolarization': 1e-3,
    'before_measure_flip_probability': 2e-3,
    'after_reset_flip_probability': 1e-3,
    'before_round_data_depolarization': 1e-3,
}
DISTANCES = [3, 5, 7]


@pytest.fixture
def results():
    with open('/app/results.json') as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------

class TestResultsSchema:
    def test_file_exists(self):
        assert os.path.exists('/app/results.json'), \
            "Results file not found at /app/results.json"

    def test_valid_json(self, results):
        assert isinstance(results, dict)

    def test_required_top_level_keys(self, results):
        required = [
            'noise_model', 'distances', 'exponential_fit',
            'lambda_suppression_factor', 'projected_distance_for_1e12',
            'projected_physical_qubits',
        ]
        for key in required:
            assert key in results, f"Missing top-level key: {key}"

    def test_all_distances_present(self, results):
        for d in DISTANCES:
            assert str(d) in results['distances'], \
                f"Distance {d} not in results"

    def test_distance_entry_keys(self, results):
        required = [
            'rounds', 'num_qubits', 'num_detectors', 'num_observables',
            'shots', 'logical_errors', 'per_shot_error_rate',
            'per_round_error_rate',
        ]
        for d in DISTANCES:
            entry = results['distances'][str(d)]
            for key in required:
                assert key in entry, f"d={d}: missing key '{key}'"

    def test_fit_keys(self, results):
        required = ['slope', 'intercept', 'r_squared']
        for key in required:
            assert key in results['exponential_fit'], \
                f"Missing exponential_fit key: {key}"


# ---------------------------------------------------------------------------
# Noise model verification
# ---------------------------------------------------------------------------

class TestNoiseModel:
    def test_after_clifford_depolarization(self, results):
        val = results['noise_model']['after_clifford_depolarization']
        assert abs(val - 1e-3) < 1e-10, \
            f"after_clifford_depolarization should be 1e-3, got {val}"

    def test_before_measure_flip_probability(self, results):
        val = results['noise_model']['before_measure_flip_probability']
        assert abs(val - 2e-3) < 1e-10, \
            f"before_measure_flip_probability should be 2e-3, got {val}"

    def test_after_reset_flip_probability(self, results):
        val = results['noise_model']['after_reset_flip_probability']
        assert abs(val - 1e-3) < 1e-10, \
            f"after_reset_flip_probability should be 1e-3, got {val}"

    def test_before_round_data_depolarization(self, results):
        val = results['noise_model']['before_round_data_depolarization']
        assert abs(val - 1e-3) < 1e-10, \
            f"before_round_data_depolarization should be 1e-3, got {val}"


# ---------------------------------------------------------------------------
# Circuit properties – independently verified via Stim
# ---------------------------------------------------------------------------

class TestCircuitProperties:
    """Construct identical circuits and verify reported metadata matches."""

    def _build_circuit(self, d):
        return stim.Circuit.generated(
            "surface_code:rotated_memory_z",
            distance=d,
            rounds=3 * d,
            **NOISE_PARAMS,
        )

    def test_num_qubits(self, results):
        for d in DISTANCES:
            expected = self._build_circuit(d).num_qubits
            actual = results['distances'][str(d)]['num_qubits']
            assert actual == expected, \
                f"d={d}: num_qubits got {actual}, expected {expected}"

    def test_num_detectors(self, results):
        for d in DISTANCES:
            expected = self._build_circuit(d).num_detectors
            actual = results['distances'][str(d)]['num_detectors']
            assert actual == expected, \
                f"d={d}: num_detectors got {actual}, expected {expected}"

    def test_num_observables(self, results):
        for d in DISTANCES:
            expected = self._build_circuit(d).num_observables
            actual = results['distances'][str(d)]['num_observables']
            assert actual == expected, \
                f"d={d}: num_observables got {actual}, expected {expected}"

    def test_rounds_correct(self, results):
        for d in DISTANCES:
            assert results['distances'][str(d)]['rounds'] == 3 * d

    def test_single_observable(self, results):
        """Surface code memory experiment has exactly 1 logical observable."""
        for d in DISTANCES:
            assert results['distances'][str(d)]['num_observables'] == 1


# ---------------------------------------------------------------------------
# Error rate sanity checks
# ---------------------------------------------------------------------------

class TestErrorRates:
    def test_positive(self, results):
        for d in DISTANCES:
            entry = results['distances'][str(d)]
            assert entry['per_shot_error_rate'] > 0, \
                f"d={d}: per_shot_error_rate must be > 0"
            assert entry['per_round_error_rate'] > 0, \
                f"d={d}: per_round_error_rate must be > 0"

    def test_below_half(self, results):
        for d in DISTANCES:
            entry = results['distances'][str(d)]
            assert entry['per_shot_error_rate'] < 0.5, \
                f"d={d}: per_shot_error_rate must be < 0.5"
            assert entry['per_round_error_rate'] < 0.5, \
                f"d={d}: per_round_error_rate must be < 0.5"

    def test_not_near_half(self, results):
        """Rates near 0.5 suggest a broken decoder."""
        for d in DISTANCES:
            assert results['distances'][str(d)]['per_shot_error_rate'] < 0.4, \
                f"d={d}: rate near 0.5 suggests random guessing"

    def test_monotonically_decreasing(self, results):
        """Below threshold, per-round error rate must decrease with distance."""
        rates = [
            results['distances'][str(d)]['per_round_error_rate']
            for d in DISTANCES
        ]
        for i in range(len(rates) - 1):
            assert rates[i] > rates[i + 1], (
                f"Per-round rate should decrease: d={DISTANCES[i]} "
                f"({rates[i]:.6f}) >= d={DISTANCES[i+1]} ({rates[i+1]:.6f})"
            )

    def test_per_round_less_than_per_shot(self, results):
        """Per-round rate is always less than per-shot rate (multiple rounds)."""
        for d in DISTANCES:
            entry = results['distances'][str(d)]
            assert entry['per_round_error_rate'] < entry['per_shot_error_rate'], \
                f"d={d}: per_round must be < per_shot"

    def test_sufficient_shots(self, results):
        for d in DISTANCES:
            assert results['distances'][str(d)]['shots'] >= 100000, \
                f"d={d}: need at least 100,000 shots"

    def test_logical_errors_nonneg(self, results):
        for d in DISTANCES:
            assert results['distances'][str(d)]['logical_errors'] >= 0

    def test_d3_has_measurable_errors(self, results):
        """At this noise level, d=3 with 100K shots should see many errors."""
        assert results['distances']['3']['logical_errors'] > 10, \
            "d=3: suspiciously few errors"

    def test_per_round_conversion_consistency(self, results):
        """per_shot and per_round must be related by the correct formula.

        The probabilistic conversion is:
            p_shot = 1 - (1 - p_round)^rounds

        Naive linear division (p_round = p_shot / rounds) produces a
        systematic deviation that this test catches.
        """
        for d in DISTANCES:
            entry = results['distances'][str(d)]
            ps = entry['per_shot_error_rate']
            pr = entry['per_round_error_rate']
            rounds = entry['rounds']
            reconstructed = 1 - (1 - pr) ** rounds
            assert abs(ps - reconstructed) < ps * 0.01 + 1e-10, (
                f"d={d}: per_shot={ps:.8f} inconsistent with "
                f"1-(1-per_round)^rounds={reconstructed:.8f}"
            )


# ---------------------------------------------------------------------------
# Error suppression and fit quality
# ---------------------------------------------------------------------------

class TestSuppression:
    def test_lambda_above_threshold(self, results):
        """Below threshold with these noise rates, Lambda must clearly exceed 1."""
        lam = results['lambda_suppression_factor']
        assert lam > 2.0, \
            f"Lambda={lam:.4f} must be > 2 for this noise level"

    def test_lambda_reasonable(self, results):
        lam = results['lambda_suppression_factor']
        assert lam < 500, f"Lambda={lam:.4f} unreasonably large"

    def test_fit_r_squared(self, results):
        r_sq = results['exponential_fit']['r_squared']
        assert r_sq > 0.9, f"R²={r_sq:.4f} < 0.9: poor exponential fit"

    def test_slope_negative(self, results):
        """Slope must be negative (error rate decreases with distance)."""
        assert results['exponential_fit']['slope'] < 0, \
            "Slope should be negative"

    def test_slope_magnitude(self, results):
        """Log-space slope should have magnitude consistent with error suppression.

        A slope close to zero suggests fitting in linear space rather
        than the correct log-linear model.
        """
        slope = results['exponential_fit']['slope']
        assert slope < -0.5, (
            f"Slope {slope:.6f} too close to zero — "
            f"check that the fit is performed in log space"
        )


# ---------------------------------------------------------------------------
# Distance & qubit projection
# ---------------------------------------------------------------------------

class TestProjection:
    def test_distance_is_integer(self, results):
        d = results['projected_distance_for_1e12']
        assert isinstance(d, int), \
            f"Projected distance must be int, got {type(d)}"

    def test_distance_is_odd(self, results):
        d = results['projected_distance_for_1e12']
        assert d % 2 == 1, f"Projected distance {d} must be odd"

    def test_distance_exceeds_sampled(self, results):
        d = results['projected_distance_for_1e12']
        assert d > max(DISTANCES), \
            f"Projected distance {d} should exceed largest sampled distance"

    def test_distance_not_absurd(self, results):
        d = results['projected_distance_for_1e12']
        assert d < 100, f"Projected distance {d} unreasonably large"

    def test_qubits_formula(self, results):
        d = results['projected_distance_for_1e12']
        expected = 2 * d * d - 1
        actual = results['projected_physical_qubits']
        assert actual == expected, \
            f"Physical qubits should be 2*d²-1={expected}, got {actual}"

    def test_qubits_is_integer(self, results):
        q = results['projected_physical_qubits']
        assert isinstance(q, int), \
            f"Projected qubits must be int, got {type(q)}"
