
import json
import math
import os

import pytest

RESULTS_FILE = "/app/results.json"
SIN2_PI_8 = math.sin(math.pi / 8) ** 2  # approx 0.14645


@pytest.fixture
def results():
    assert os.path.exists(RESULTS_FILE), f"{RESULTS_FILE} not found"
    with open(RESULTS_FILE) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# 1. Circuit structural properties
# ---------------------------------------------------------------------------

class TestStructure:
    def test_num_qubits(self, results):
        assert results["num_qubits"] == 7, (
            f"Expected 7 qubits for [[7,1,3]] Steane code, got {results['num_qubits']}"
        )

    def test_num_detectors(self, results):
        assert results["num_detectors"] == 3, (
            f"Expected 3 Z-stabilizer detectors, got {results['num_detectors']}"
        )

    def test_num_observables(self, results):
        assert results["num_observables"] == 1, (
            f"Expected 1 logical observable, got {results['num_observables']}"
        )

    def test_tcount(self, results):
        assert results["tcount"] == 1, (
            f"Expected T-count of 1, got {results['tcount']}"
        )


# ---------------------------------------------------------------------------
# 2. Detector error model
# ---------------------------------------------------------------------------

class TestDEM:
    def test_has_errors(self, results):
        assert results["num_dem_errors"] > 0, "DEM should have error mechanisms"

    def test_error_probs_valid(self, results):
        probs = results["dem_error_probs"]
        assert isinstance(probs, list), "dem_error_probs must be a list"
        assert len(probs) == results["num_dem_errors"], (
            f"Length mismatch: {len(probs)} probs vs {results['num_dem_errors']} errors"
        )
        for i, p in enumerate(probs):
            assert 0 < p < 1, f"Error probability {i} out of range: {p}"


# ---------------------------------------------------------------------------
# 3. Noiseless sampling
# ---------------------------------------------------------------------------

class TestNoiseless:
    def test_obs_rate_matches_theory(self, results):
        obs = results["noiseless_obs_rate"]
        assert abs(obs - SIN2_PI_8) < 0.005, (
            f"Noiseless obs rate {obs:.5f} deviates from sin^2(pi/8)={SIN2_PI_8:.5f}"
        )

    def test_zero_detection_rate(self, results):
        assert results["noiseless_det_rate"] == 0.0, (
            f"Noiseless detection rate should be 0.0, got {results['noiseless_det_rate']}"
        )


# ---------------------------------------------------------------------------
# 4. Noisy sampling at p=0.01
# ---------------------------------------------------------------------------

class TestNoisy:
    def test_detection_rate_positive(self, results):
        assert results["noisy_det_rate"] > 0.02, (
            f"Noisy detection rate should be > 0.02, got {results['noisy_det_rate']}"
        )

    def test_raw_obs_in_range(self, results):
        r = results["noisy_raw_obs_rate"]
        assert 0.10 < r < 0.25, (
            f"Noisy raw obs rate {r:.4f} outside expected range (0.10, 0.25)"
        )

    def test_postselection_improves(self, results):
        raw_err = abs(results["noisy_raw_obs_rate"] - SIN2_PI_8)
        postsel_err = abs(results["noisy_postselected_obs_rate"] - SIN2_PI_8)
        assert postsel_err < raw_err, (
            f"Post-selection should reduce error: post-sel={postsel_err:.5f} "
            f"vs raw={raw_err:.5f}"
        )


# ---------------------------------------------------------------------------
# 5. Noise sweep
# ---------------------------------------------------------------------------

class TestSweep:
    def test_length(self, results):
        assert len(results["sweep_results"]) == 5

    def test_noise_values(self, results):
        expected = [0.001, 0.005, 0.01, 0.05, 0.1]
        for entry, ep in zip(results["sweep_results"], expected):
            assert abs(entry["p"] - ep) < 1e-6, (
                f"Expected p={ep}, got {entry['p']}"
            )

    def test_values_in_range(self, results):
        for entry in results["sweep_results"]:
            assert 0 <= entry["postselected_obs_rate"] <= 1
            assert 0 <= entry["detection_rate"] <= 1
            assert 0 < entry["yield"] <= 1
            assert 0 <= entry["physical_obs_rate"] <= 1

    def test_low_noise_near_ideal(self, results):
        lowest = results["sweep_results"][0]  # p=0.001
        err = abs(lowest["postselected_obs_rate"] - SIN2_PI_8)
        assert err < 0.01, (
            f"At p=0.001, post-selected rate should be near ideal; error={err:.5f}"
        )

    def test_detection_increases_with_noise(self, results):
        sweep = results["sweep_results"]
        assert sweep[-1]["detection_rate"] > sweep[0]["detection_rate"], (
            "Detection rate should increase with noise"
        )

    def test_yield_decreases_with_noise(self, results):
        sweep = results["sweep_results"]
        assert sweep[0]["yield"] > sweep[-1]["yield"], (
            "Post-selection yield should decrease with noise"
        )

    def test_physical_obs_present(self, results):
        for entry in results["sweep_results"]:
            assert "physical_obs_rate" in entry, (
                "Each sweep entry must have physical_obs_rate"
            )

    def test_encoding_advantage_at_moderate_noise(self, results):
        """At p=0.01, post-selected logical error should beat physical error."""
        entry = results["sweep_results"][2]  # p=0.01
        logical_err = abs(entry["postselected_obs_rate"] - SIN2_PI_8)
        physical_err = abs(entry["physical_obs_rate"] - SIN2_PI_8)
        assert logical_err < physical_err, (
            f"At p=0.01, logical error ({logical_err:.6f}) should be less than "
            f"physical error ({physical_err:.6f})"
        )
