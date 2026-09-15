"""Tests for the QEC analysis pipeline output.

"""

import json
import math
import os

import pytest

IDEAL_T = math.sin(math.pi / 8) ** 2  # ~0.14645
IDEAL_T2 = 0.5


@pytest.fixture
def results():
    path = "/app/results.json"
    assert os.path.exists(path), "results.json not found at /app/results.json"
    with open(path) as f:
        data = json.load(f)
    return data


# ---- Circuit structural properties ----

class TestCircuitProperties:
    def test_num_qubits(self, results):
        assert results["circuit_properties"]["num_qubits"] == 7, (
            "Steane [[7,1,3]] code must use exactly 7 qubits"
        )

    def test_num_measurements(self, results):
        assert results["circuit_properties"]["num_measurements"] == 7, (
            "All 7 data qubits must be measured"
        )

    def test_num_detectors(self, results):
        assert results["circuit_properties"]["num_detectors"] == 3, (
            "Steane code with single measurement round needs 3 X-type stabilizer detectors"
        )

    def test_num_observables(self, results):
        assert results["circuit_properties"]["num_observables"] == 1, (
            "Single logical qubit requires exactly 1 observable"
        )

    def test_not_clifford(self, results):
        assert results["circuit_properties"]["is_clifford"] is False, (
            "Circuit with T gate must not be Clifford"
        )

    def test_has_t_gates(self, results):
        assert results["circuit_properties"]["t_count"] >= 1, (
            "Circuit must contain at least one T gate"
        )


# ---- Noiseless sampling ----

class TestNoiselessAnalysis:
    def test_observable_rate_near_ideal(self, results):
        rate = results["noiseless_analysis"]["observable_flip_rate"]
        assert abs(rate - IDEAL_T) < 0.02, (
            f"Noiseless observable rate {rate:.4f} deviates too far from "
            f"ideal sin^2(pi/8) = {IDEAL_T:.4f}"
        )

    def test_detectors_silent(self, results):
        det_rate = results["noiseless_analysis"]["detector_firing_rate"]
        assert det_rate == 0.0, (
            f"Noiseless circuit should have zero detector events, got rate {det_rate}"
        )

    def test_ideal_rate_reported(self, results):
        ideal = results["noiseless_analysis"]["ideal_rate"]
        assert abs(ideal - IDEAL_T) < 1e-6, (
            f"Reported ideal rate {ideal} doesn't match sin^2(pi/8)"
        )


# ---- T vs R_Z equivalence ----

class TestEquivalence:
    def test_t_rz_rates_match(self, results):
        eq = results["equivalence_check"]
        t_rate = eq["t_observable_rate"]
        rz_rate = eq["rz_observable_rate"]
        diff = abs(t_rate - rz_rate)
        assert diff < 0.02, (
            f"T gate rate ({t_rate:.4f}) and R_Z(0.25) rate ({rz_rate:.4f}) "
            f"differ by {diff:.4f}, should be equivalent"
        )


# ---- Detector error model ----

class TestDEM:
    def test_has_mechanisms(self, results):
        n = results["dem_analysis"]["num_error_mechanisms"]
        assert n >= 3, (
            f"DEM should have at least 3 error mechanisms, got {n}"
        )

    def test_positive_total_probability(self, results):
        total = results["dem_analysis"]["total_error_probability"]
        assert total > 0, "Total error probability must be positive"

    def test_mechanism_weight_bounded(self, results):
        w = results["dem_analysis"]["max_mechanism_weight"]
        assert w <= 4, (
            f"Max error mechanism weight {w} exceeds bound of 4 "
            f"(detectors + observables per mechanism)"
        )


# ---- Noisy sampling and decoding ----

class TestNoisySampling:
    def test_detectors_fire(self, results):
        rate = results["noisy_analysis"]["detector_firing_rate"]
        assert rate > 0, (
            "Noisy circuit must produce some non-zero detector events"
        )

    def test_decoder_not_harmful(self, results):
        noisy = results["noisy_analysis"]
        decoded_dev = noisy["decoded_deviation_from_ideal"]
        raw_dev = noisy["raw_deviation_from_ideal"]
        assert decoded_dev <= raw_dev + 0.005, (
            f"Decoder should not significantly degrade observable rate: "
            f"decoded_deviation={decoded_dev:.4f}, raw_deviation={raw_dev:.4f}"
        )

    def test_post_selection_reasonable(self, results):
        ps_rate = results["noisy_analysis"]["post_selected_observable_flip_rate"]
        if ps_rate is not None:
            assert abs(ps_rate - IDEAL_T) < 0.03, (
                f"Post-selected rate {ps_rate:.4f} too far from ideal {IDEAL_T:.4f}"
            )

    def test_physical_error_rate_recorded(self, results):
        p = results["noisy_analysis"]["physical_error_rate"]
        assert 0 < p < 1, f"Physical error rate {p} must be in (0, 1)"


# ---- Dual T-gate analysis ----

class TestDualT:
    def test_rate_near_half(self, results):
        rate = results["dual_t_analysis"]["noiseless_observable_flip_rate"]
        assert abs(rate - IDEAL_T2) < 0.02, (
            f"Dual-T observable rate {rate:.4f} deviates too far from "
            f"ideal 0.5 (since T^2 = S, H*S*|+> gives P(1)=0.5)"
        )

    def test_ideal_rate_reported(self, results):
        ideal = results["dual_t_analysis"]["ideal_rate"]
        assert abs(ideal - IDEAL_T2) < 1e-6, (
            f"Reported dual-T ideal rate {ideal} doesn't match 0.5"
        )
