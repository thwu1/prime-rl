"""Tests for the Steane code T-gate analysis pipeline.

"""

import json
import math
import os

import pytest

RESULTS_PATH = "/app/results.json"


@pytest.fixture
def results():
    """Load results from the analysis pipeline."""
    assert os.path.exists(RESULTS_PATH), f"Results file not found at {RESULTS_PATH}"
    with open(RESULTS_PATH) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------

class TestResultsSchema:
    """Verify the results JSON has the required structure."""

    def test_top_level_keys(self, results):
        assert "circuit" in results
        assert "noiseless" in results
        assert "noisy" in results

    def test_circuit_keys(self, results):
        for key in ["num_qubits", "num_measurements", "num_detectors",
                     "num_observables", "t_count"]:
            assert key in results["circuit"], f"Missing circuit key: {key}"

    def test_noiseless_keys(self, results):
        assert "observable_rate" in results["noiseless"]

    def test_noisy_entry_keys(self, results):
        required = ["p", "num_dem_mechanisms", "num_l0_flipping_mechanisms",
                     "raw_obs_rate", "detection_event_rate",
                     "post_selected_obs_rate", "post_selection_yield"]
        for entry in results["noisy"]:
            for key in required:
                assert key in entry, f"Missing noisy key: {key}"


# ---------------------------------------------------------------------------
# Circuit structure (exact checks)
# ---------------------------------------------------------------------------

class TestCircuitStructure:
    """Verify the circuit has the correct [[7,1,3]] Steane code structure."""

    def test_num_qubits(self, results):
        assert results["circuit"]["num_qubits"] == 7

    def test_num_measurements(self, results):
        assert results["circuit"]["num_measurements"] == 7

    def test_num_detectors(self, results):
        assert results["circuit"]["num_detectors"] == 3

    def test_num_observables(self, results):
        assert results["circuit"]["num_observables"] == 1

    def test_t_count(self, results):
        assert results["circuit"]["t_count"] == 1


# ---------------------------------------------------------------------------
# Noiseless behaviour (statistical)
# ---------------------------------------------------------------------------

class TestNoiselessBehavior:
    """Verify the noiseless circuit produces correct quantum statistics."""

    def test_observable_rate_matches_theory(self, results):
        """The noiseless observable rate should be sin^2(pi/8) ~ 0.1464."""
        expected = math.sin(math.pi / 8) ** 2
        actual = results["noiseless"]["observable_rate"]
        assert abs(actual - expected) < 0.015, (
            f"Noiseless observable rate {actual:.4f} deviates from "
            f"sin^2(pi/8) = {expected:.4f} by more than 0.015"
        )


# ---------------------------------------------------------------------------
# Noisy analysis (physical-reasonableness checks)
# ---------------------------------------------------------------------------

class TestNoisyAnalysis:
    """Verify the noisy analysis produces physically reasonable results."""

    def test_at_least_five_noise_levels(self, results):
        assert len(results["noisy"]) >= 5

    def test_noise_levels_sorted(self, results):
        ps = [e["p"] for e in results["noisy"]]
        assert ps == sorted(ps), "Noisy entries must be sorted by p"

    def test_dem_has_mechanisms(self, results):
        for entry in results["noisy"]:
            assert entry["num_dem_mechanisms"] >= 1, (
                f"DEM at p={entry['p']} has no error mechanisms"
            )

    def test_some_mechanisms_flip_observable(self, results):
        for entry in results["noisy"]:
            assert entry["num_l0_flipping_mechanisms"] >= 1, (
                f"No L0-flipping mechanisms at p={entry['p']}"
            )

    def test_l0_flipping_bounded_by_total(self, results):
        for entry in results["noisy"]:
            assert entry["num_l0_flipping_mechanisms"] <= entry["num_dem_mechanisms"]

    def test_detection_rate_increases_with_noise(self, results):
        noisy = sorted(results["noisy"], key=lambda x: x["p"])
        assert noisy[-1]["detection_event_rate"] > noisy[0]["detection_event_rate"], (
            "Detection event rate should increase with physical error rate"
        )

    def test_post_selection_yield_decreases_with_noise(self, results):
        noisy = sorted(results["noisy"], key=lambda x: x["p"])
        assert noisy[-1]["post_selection_yield"] < noisy[0]["post_selection_yield"], (
            "Post-selection yield should decrease with noise"
        )

    def test_post_selection_improves_fidelity(self, results):
        """At moderate noise, post-selection should improve accuracy."""
        ideal = math.sin(math.pi / 8) ** 2
        moderate = [e for e in results["noisy"] if 0.005 <= e["p"] <= 0.05]
        assert len(moderate) > 0, "No entries in moderate noise range"
        for entry in moderate:
            if entry["post_selection_yield"] < 0.05:
                continue  # too few post-selected samples for reliable stat
            if entry["post_selected_obs_rate"] is None:
                continue
            raw_dev = abs(entry["raw_obs_rate"] - ideal)
            ps_dev = abs(entry["post_selected_obs_rate"] - ideal)
            assert ps_dev < raw_dev + 0.02, (
                f"Post-selection did not improve fidelity at p={entry['p']}: "
                f"raw_dev={raw_dev:.4f}, ps_dev={ps_dev:.4f}"
            )

    def test_high_noise_deviates_from_ideal(self, results):
        """At the highest noise level, raw obs rate should deviate noticeably."""
        ideal = math.sin(math.pi / 8) ** 2
        noisy = sorted(results["noisy"], key=lambda x: x["p"])
        high = noisy[-1]
        assert abs(high["raw_obs_rate"] - ideal) > 0.01, (
            f"Raw obs rate at p={high['p']} should deviate from ideal"
        )

    def test_low_noise_near_noiseless(self, results):
        """At very low noise the raw obs rate should still be close to ideal."""
        ideal = math.sin(math.pi / 8) ** 2
        low = [e for e in results["noisy"] if e["p"] <= 0.002]
        for entry in low:
            assert abs(entry["raw_obs_rate"] - ideal) < 0.03, (
                f"Raw obs rate at p={entry['p']} deviates too much from ideal"
            )

    def test_valid_probability_ranges(self, results):
        """All rates should be valid probabilities in [0, 1]."""
        for entry in results["noisy"]:
            assert 0 <= entry["raw_obs_rate"] <= 1
            assert 0 <= entry["detection_event_rate"] <= 1
            assert 0 <= entry["post_selection_yield"] <= 1
            if entry["post_selected_obs_rate"] is not None:
                assert 0 <= entry["post_selected_obs_rate"] <= 1

    def test_detection_rate_positive_everywhere(self, results):
        """Even at low noise, there should be some detection events."""
        for entry in results["noisy"]:
            assert entry["detection_event_rate"] > 0, (
                f"Expected nonzero detection rate at p={entry['p']}"
            )
