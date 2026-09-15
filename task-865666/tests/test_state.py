
"""Tests for the surface code QEC analysis pipeline."""

import json
import math
import os

import stim


DISTANCES = [3, 5, 7]
NOISE_LEVELS = [0.001, 0.002, 0.004, 0.006, 0.008, 0.01]
RESULTS_PATH = "/app/results.json"


def load_results():
    with open(RESULTS_PATH) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Structural tests
# ---------------------------------------------------------------------------

class TestResultsStructure:
    def test_results_file_exists(self):
        assert os.path.isfile(RESULTS_PATH), "results.json not found at /app/results.json"

    def test_results_valid_json(self):
        results = load_results()
        assert isinstance(results, dict)

    def test_required_top_level_keys(self):
        results = load_results()
        for key in ["circuit_metadata", "error_rates", "suppression_factors",
                     "threshold_estimate", "footprint_projection"]:
            assert key in results, f"Missing top-level key: {key}"

    def test_circuit_metadata_completeness(self):
        """All 18 (d, p) configurations must be present."""
        results = load_results()
        meta = results["circuit_metadata"]
        for d in DISTANCES:
            for p in NOISE_LEVELS:
                found = any(
                    v.get("distance") == d and abs(v.get("noise_level", -1) - p) < 1e-10
                    for v in meta.values()
                )
                assert found, f"Missing circuit_metadata for d={d}, p={p}"

    def test_error_rates_completeness(self):
        """All 18 (d, p) configurations must be present."""
        results = load_results()
        rates = results["error_rates"]
        for d in DISTANCES:
            for p in NOISE_LEVELS:
                found = any(
                    v.get("distance") == d and abs(v.get("noise_level", -1) - p) < 1e-10
                    for v in rates.values()
                )
                assert found, f"Missing error_rates for d={d}, p={p}"

    def test_suppression_factors_completeness(self):
        """2 distance pairs x 6 noise levels = 12 entries."""
        results = load_results()
        sf = results["suppression_factors"]
        pairs = [(3, 5), (5, 7)]
        for d_low, d_high in pairs:
            for p in NOISE_LEVELS:
                found = any(
                    v.get("d_low") == d_low
                    and v.get("d_high") == d_high
                    and abs(v.get("noise_level", -1) - p) < 1e-10
                    for v in sf.values()
                )
                assert found, f"Missing suppression_factor for d{d_low}->d{d_high}, p={p}"


# ---------------------------------------------------------------------------
# Deterministic metadata tests
# ---------------------------------------------------------------------------

class TestCircuitMetadata:
    def _generate_circuit(self, d, p):
        return stim.Circuit.generated(
            "surface_code:rotated_memory_z",
            rounds=3 * d,
            distance=d,
            after_clifford_depolarization=p,
            after_reset_flip_probability=p,
            before_measure_flip_probability=p,
            before_round_data_depolarization=p,
        )

    def _find_entry(self, section, d, p):
        results = load_results()
        for v in results[section].values():
            if v.get("distance") == d and abs(v.get("noise_level", -1) - p) < 1e-10:
                return v
        return None

    def test_num_qubits_accuracy(self):
        """num_qubits must exactly match independently generated circuit."""
        for d in DISTANCES:
            p = 0.001  # metadata is noise-independent for structure
            circuit = self._generate_circuit(d, p)
            entry = self._find_entry("circuit_metadata", d, p)
            assert entry is not None
            assert entry["num_qubits"] == circuit.num_qubits, (
                f"d={d}: expected num_qubits={circuit.num_qubits}, got {entry['num_qubits']}"
            )

    def test_num_detectors_accuracy(self):
        for d in DISTANCES:
            p = 0.001
            circuit = self._generate_circuit(d, p)
            entry = self._find_entry("circuit_metadata", d, p)
            assert entry is not None
            assert entry["num_detectors"] == circuit.num_detectors, (
                f"d={d}: expected num_detectors={circuit.num_detectors}, got {entry['num_detectors']}"
            )

    def test_num_observables_is_one(self):
        """Memory experiment always has exactly 1 observable."""
        results = load_results()
        for v in results["circuit_metadata"].values():
            assert v["num_observables"] == 1, (
                f"d={v['distance']}: expected num_observables=1, got {v['num_observables']}"
            )

    def test_num_measurements_accuracy(self):
        for d in DISTANCES:
            p = 0.001
            circuit = self._generate_circuit(d, p)
            entry = self._find_entry("circuit_metadata", d, p)
            assert entry is not None
            assert entry["num_measurements"] == circuit.num_measurements, (
                f"d={d}: expected num_measurements={circuit.num_measurements}, "
                f"got {entry['num_measurements']}"
            )

    def test_shortest_graphlike_error_weight_equals_distance(self):
        """For a distance-d surface code, the shortest graphlike error has weight d."""
        results = load_results()
        for d in DISTANCES:
            found = False
            for v in results["circuit_metadata"].values():
                if v.get("distance") == d:
                    assert v["shortest_graphlike_error_weight"] == d, (
                        f"d={d}: shortest_graphlike_error_weight should be {d}, "
                        f"got {v['shortest_graphlike_error_weight']}"
                    )
                    found = True
                    break
            assert found, f"No metadata entry found for d={d}"


# ---------------------------------------------------------------------------
# Error rate physical constraints
# ---------------------------------------------------------------------------

class TestErrorRates:
    def test_error_rates_in_valid_range(self):
        results = load_results()
        for k, v in results["error_rates"].items():
            ps = v["logical_error_rate_per_shot"]
            pr = v["logical_error_rate_per_round"]
            assert 0 <= ps <= 1.0, f"{k}: per_shot rate {ps} out of [0,1]"
            assert 0 <= pr <= 1.0, f"{k}: per_round rate {pr} out of [0,1]"

    def test_per_round_leq_per_shot(self):
        """Per-round error rate must be <= per-shot rate."""
        results = load_results()
        for k, v in results["error_rates"].items():
            ps = v["logical_error_rate_per_shot"]
            pr = v["logical_error_rate_per_round"]
            assert pr <= ps + 1e-9, (
                f"{k}: per_round ({pr}) should be <= per_shot ({ps})"
            )

    def test_error_rate_monotonic_with_noise(self):
        """For each distance, error rate should generally increase with noise level."""
        results = load_results()
        for d in DISTANCES:
            rates = []
            for v in results["error_rates"].values():
                if v.get("distance") == d:
                    rates.append((v["noise_level"], v["logical_error_rate_per_shot"]))
            rates.sort()
            # Allow small statistical fluctuation (tolerance of 0.03)
            for i in range(len(rates) - 1):
                assert rates[i][1] <= rates[i + 1][1] + 0.03, (
                    f"d={d}: error rate not monotonic - "
                    f"p={rates[i][0]}:{rates[i][1]:.4f} > p={rates[i+1][0]}:{rates[i+1][1]:.4f}"
                )

    def test_minimum_shots(self):
        """Each configuration must have at least 10,000 shots."""
        results = load_results()
        for k, v in results["error_rates"].items():
            assert v["num_shots"] >= 10000, (
                f"{k}: only {v['num_shots']} shots (need >= 10000)"
            )

    def test_per_round_formula_consistency(self):
        """Verify per-round rate is consistent with per-shot via the standard formula."""
        results = load_results()
        for k, v in results["error_rates"].items():
            ps = v["logical_error_rate_per_shot"]
            pr_reported = v["logical_error_rate_per_round"]
            d = v["distance"]
            rounds = 3 * d
            if ps > 0 and ps < 1:
                pr_expected = 1.0 - (1.0 - ps) ** (1.0 / rounds)
                assert abs(pr_reported - pr_expected) < 1e-6 + 0.01 * pr_expected, (
                    f"{k}: per_round mismatch - reported {pr_reported:.6e}, "
                    f"expected {pr_expected:.6e} from formula"
                )


# ---------------------------------------------------------------------------
# Suppression factor tests
# ---------------------------------------------------------------------------

class TestSuppressionFactors:
    def test_lambda_positive(self):
        results = load_results()
        for k, v in results["suppression_factors"].items():
            lam = v["lambda"]
            assert lam > 0, f"{k}: lambda must be positive, got {lam}"

    def test_lambda_above_one_below_threshold(self):
        """At low noise (well below threshold), Lambda should be > 1.
        This is the fundamental property of error correction working."""
        results = load_results()
        for v in results["suppression_factors"].values():
            if v["noise_level"] <= 0.002:
                assert v["lambda"] > 1.0, (
                    f"Lambda should be > 1 below threshold at p={v['noise_level']}, "
                    f"d{v['d_low']}->d{v['d_high']}: got {v['lambda']:.3f}"
                )

    def test_lambda_correct_direction(self):
        """Lambda should generally decrease as noise increases for a given distance pair."""
        results = load_results()
        for d_low, d_high in [(3, 5), (5, 7)]:
            lambdas = []
            for v in results["suppression_factors"].values():
                if v["d_low"] == d_low and v["d_high"] == d_high:
                    lambdas.append((v["noise_level"], v["lambda"]))
            lambdas.sort()
            # At least the first lambda should be larger than the last
            if len(lambdas) >= 2:
                assert lambdas[0][1] > lambdas[-1][1] * 0.5, (
                    f"d{d_low}->d{d_high}: Lambda should decrease with noise. "
                    f"At p={lambdas[0][0]}: {lambdas[0][1]:.2f}, "
                    f"at p={lambdas[-1][0]}: {lambdas[-1][1]:.2f}"
                )


# ---------------------------------------------------------------------------
# Threshold and projection tests
# ---------------------------------------------------------------------------

class TestThresholdAndProjection:
    def test_threshold_is_numeric(self):
        results = load_results()
        t = results["threshold_estimate"]
        assert isinstance(t, (int, float)), f"threshold must be numeric, got {type(t)}"

    def test_threshold_in_expected_range(self):
        """Surface code threshold under circuit-level depolarizing noise
        with MWPM is approximately 0.5-1.1%. Allow generous bounds."""
        results = load_results()
        t = results["threshold_estimate"]
        assert 0.004 <= t <= 0.015, (
            f"Threshold {t:.4f} outside expected range [0.004, 0.015]"
        )

    def test_footprint_projection_structure(self):
        results = load_results()
        fp = results["footprint_projection"]
        assert "noise_level" in fp
        assert "target_error_rate_per_round" in fp
        assert "projected_distance" in fp
        assert "projected_physical_qubits" in fp

    def test_footprint_projection_noise_level(self):
        results = load_results()
        fp = results["footprint_projection"]
        assert abs(fp["noise_level"] - 0.001) < 1e-10, (
            f"Footprint projection should be at p=0.001, got {fp['noise_level']}"
        )

    def test_projected_distance_reasonable(self):
        """Distance needed for 10^-12 error rate at p=0.001 should be 10-40."""
        results = load_results()
        fp = results["footprint_projection"]
        d = fp["projected_distance"]
        assert 10 <= d <= 40, (
            f"Projected distance {d} outside reasonable range [10, 40]"
        )

    def test_projected_qubits_consistent_with_distance(self):
        """projected_physical_qubits should be approximately 2*d^2 - 1."""
        results = load_results()
        fp = results["footprint_projection"]
        d = fp["projected_distance"]
        q = fp["projected_physical_qubits"]
        expected_q = 2 * d ** 2 - 1
        assert abs(q - expected_q) / expected_q < 0.1, (
            f"Qubits {q} inconsistent with distance {d}: expected ~{expected_q:.0f}"
        )
