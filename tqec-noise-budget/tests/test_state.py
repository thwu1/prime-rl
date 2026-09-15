
"""Tests for surface code noise budget decomposition output."""

import json
import os
import pytest
import stim


@pytest.fixture
def budget_data():
    with open("/app/error_budget.json") as f:
        return json.load(f)


@pytest.fixture
def params():
    with open("/data/circuit_params.json") as f:
        return json.load(f)


class TestOutputExists:
    def test_file_exists(self):
        assert os.path.exists("/app/error_budget.json"), \
            "/app/error_budget.json not found"

    def test_valid_json(self):
        with open("/app/error_budget.json") as f:
            data = json.load(f)
        assert isinstance(data, dict)


class TestJsonStructure:
    def test_top_level_keys(self, budget_data):
        assert "mechanisms" in budget_data, "Missing 'mechanisms' key"
        assert "full_circuit" in budget_data, "Missing 'full_circuit' key"

    def test_mechanism_names(self, budget_data):
        expected = {"gate_noise", "idle_noise", "prep_noise", "meas_noise"}
        actual = set(budget_data["mechanisms"].keys())
        assert actual == expected, \
            "Expected mechanism names {}, got {}".format(expected, actual)

    def test_mechanism_fields(self, budget_data):
        required_fields = {"dem_error_count", "total_error_weight", "budget_fraction"}
        for name, mech in budget_data["mechanisms"].items():
            for field in required_fields:
                assert field in mech, \
                    "Mechanism '{}' missing field '{}'".format(name, field)

    def test_full_circuit_fields(self, budget_data):
        required = [
            "num_qubits_d3", "num_qubits_d5",
            "num_detectors_d3", "num_detectors_d5",
            "num_observables_d3", "num_observables_d5",
            "total_dem_weight_d3", "total_dem_weight_d5",
        ]
        for field in required:
            assert field in budget_data["full_circuit"], \
                "Missing '{}' in full_circuit".format(field)


class TestMechanismValues:
    def test_positive_error_counts(self, budget_data):
        for name, mech in budget_data["mechanisms"].items():
            assert isinstance(mech["dem_error_count"], int), \
                "{}: dem_error_count should be int".format(name)
            assert mech["dem_error_count"] > 0, \
                "{}: dem_error_count should be > 0".format(name)

    def test_positive_error_weights(self, budget_data):
        for name, mech in budget_data["mechanisms"].items():
            assert isinstance(mech["total_error_weight"], (int, float)), \
                "{}: total_error_weight should be numeric".format(name)
            assert mech["total_error_weight"] > 0, \
                "{}: total_error_weight should be > 0".format(name)

    def test_positive_budget_fractions(self, budget_data):
        for name, mech in budget_data["mechanisms"].items():
            assert isinstance(mech["budget_fraction"], (int, float)), \
                "{}: budget_fraction should be numeric".format(name)
            assert mech["budget_fraction"] > 0, \
                "{}: budget_fraction should be > 0".format(name)
            assert mech["budget_fraction"] < 1.0, \
                "{}: budget_fraction should be < 1.0".format(name)


class TestBudgetConsistency:
    def test_fractions_sum_approximately_one(self, budget_data):
        total = sum(
            m["budget_fraction"] for m in budget_data["mechanisms"].values()
        )
        assert 0.5 < total < 1.5, \
            "Budget fractions sum to {:.4f}, expected approximately 1.0".format(total)

    def test_fractions_consistent_with_weights(self, budget_data):
        """budget_fraction should equal total_error_weight / full DEM weight."""
        full_weight = budget_data["full_circuit"]["total_dem_weight_d3"]
        assert full_weight > 0, "Full circuit DEM weight must be positive"
        for name, mech in budget_data["mechanisms"].items():
            expected = mech["total_error_weight"] / full_weight
            actual = mech["budget_fraction"]
            assert abs(actual - expected) < 0.001, \
                "{}: budget_fraction={:.6f} inconsistent with " \
                "weight/full_weight={:.6f}".format(name, actual, expected)

    def test_no_single_mechanism_dominates_entirely(self, budget_data):
        """No single mechanism should account for >90% of total budget."""
        for name, mech in budget_data["mechanisms"].items():
            assert mech["budget_fraction"] < 0.9, \
                "{} accounts for {:.1%} of budget".format(
                    name, mech["budget_fraction"])

    def test_all_mechanisms_nontrivial(self, budget_data):
        """Each mechanism should contribute at least 0.5% of the budget."""
        for name, mech in budget_data["mechanisms"].items():
            assert mech["budget_fraction"] > 0.005, \
                "{} has trivially small contribution: {:.4f}".format(
                    name, mech["budget_fraction"])


class TestCircuitProperties:
    def test_qubit_count_scaling(self, budget_data):
        fc = budget_data["full_circuit"]
        assert fc["num_qubits_d5"] > fc["num_qubits_d3"], \
            "Qubit count should increase with code distance"

    def test_detector_count_scaling(self, budget_data):
        fc = budget_data["full_circuit"]
        assert fc["num_detectors_d5"] > fc["num_detectors_d3"], \
            "Detector count should increase with code distance"

    def test_dem_weight_scaling(self, budget_data):
        fc = budget_data["full_circuit"]
        assert fc["total_dem_weight_d5"] > fc["total_dem_weight_d3"], \
            "Total DEM weight should increase with code distance"

    def test_observable_count_constant(self, budget_data):
        fc = budget_data["full_circuit"]
        assert fc["num_observables_d3"] >= 1, \
            "Memory experiment should have at least 1 observable"
        assert fc["num_observables_d3"] == fc["num_observables_d5"], \
            "Observable count should not change with code distance"

    def test_qubit_count_reasonable(self, budget_data):
        fc = budget_data["full_circuit"]
        assert 10 < fc["num_qubits_d3"] < 200, \
            "Unexpected qubit count at d=3: {}".format(fc["num_qubits_d3"])
        assert fc["num_qubits_d5"] < 500, \
            "Unexpected qubit count at d=5: {}".format(fc["num_qubits_d5"])

    def test_dem_weight_reasonable(self, budget_data):
        fc = budget_data["full_circuit"]
        assert 0.001 < fc["total_dem_weight_d3"] < 100.0, \
            "Unexpected DEM weight at d=3: {}".format(fc["total_dem_weight_d3"])


class TestIndependentVerification:
    """Cross-check results against independently generated stim circuits."""

    def _gen_circuit(self, params, distance, **noise_overrides):
        base = dict(
            after_clifford_depolarization=0,
            before_round_data_depolarization=0,
            after_reset_flip_probability=0,
            before_measure_flip_probability=0,
        )
        base.update(noise_overrides)
        return stim.Circuit.generated(
            params["code_task"],
            rounds=params["rounds"],
            distance=distance,
            **base,
        )

    def _dem_stats(self, circuit):
        dem = circuit.detector_error_model()
        count = 0
        weight = 0.0
        for inst in dem.flattened():
            if inst.type == "error":
                count += 1
                weight += inst.args_copy()[0]
        return count, weight

    def test_full_circuit_properties(self, budget_data, params):
        p = params["noise_level"]
        d3 = params["distances"][0]
        full_d3 = self._gen_circuit(
            params, d3,
            after_clifford_depolarization=p,
            before_round_data_depolarization=p,
            after_reset_flip_probability=p,
            before_measure_flip_probability=p,
        )
        fc = budget_data["full_circuit"]
        assert fc["num_qubits_d3"] == full_d3.num_qubits, \
            "Qubit count mismatch: {} vs {}".format(
                fc["num_qubits_d3"], full_d3.num_qubits)
        assert fc["num_detectors_d3"] == full_d3.num_detectors, \
            "Detector count mismatch: {} vs {}".format(
                fc["num_detectors_d3"], full_d3.num_detectors)
        assert fc["num_observables_d3"] == full_d3.num_observables, \
            "Observable count mismatch"
        _, expected_weight = self._dem_stats(full_d3)
        assert abs(fc["total_dem_weight_d3"] - expected_weight) < 1e-6, \
            "DEM weight mismatch: {:.8f} vs {:.8f}".format(
                fc["total_dem_weight_d3"], expected_weight)

    def test_gate_noise_stats(self, budget_data, params):
        p = params["noise_level"]
        d3 = params["distances"][0]
        iso = self._gen_circuit(params, d3, after_clifford_depolarization=p)
        exp_count, exp_weight = self._dem_stats(iso)
        actual = budget_data["mechanisms"]["gate_noise"]
        assert actual["dem_error_count"] == exp_count, \
            "gate_noise error count: {} vs {}".format(
                actual["dem_error_count"], exp_count)
        assert abs(actual["total_error_weight"] - exp_weight) < 1e-6, \
            "gate_noise weight: {:.8f} vs {:.8f}".format(
                actual["total_error_weight"], exp_weight)

    def test_idle_noise_stats(self, budget_data, params):
        p = params["noise_level"]
        d3 = params["distances"][0]
        iso = self._gen_circuit(params, d3, before_round_data_depolarization=p)
        exp_count, exp_weight = self._dem_stats(iso)
        actual = budget_data["mechanisms"]["idle_noise"]
        assert actual["dem_error_count"] == exp_count, \
            "idle_noise error count: {} vs {}".format(
                actual["dem_error_count"], exp_count)
        assert abs(actual["total_error_weight"] - exp_weight) < 1e-6, \
            "idle_noise weight: {:.8f} vs {:.8f}".format(
                actual["total_error_weight"], exp_weight)

    def test_prep_noise_stats(self, budget_data, params):
        p = params["noise_level"]
        d3 = params["distances"][0]
        iso = self._gen_circuit(params, d3, after_reset_flip_probability=p)
        exp_count, exp_weight = self._dem_stats(iso)
        actual = budget_data["mechanisms"]["prep_noise"]
        assert actual["dem_error_count"] == exp_count, \
            "prep_noise error count: {} vs {}".format(
                actual["dem_error_count"], exp_count)
        assert abs(actual["total_error_weight"] - exp_weight) < 1e-6, \
            "prep_noise weight: {:.8f} vs {:.8f}".format(
                actual["total_error_weight"], exp_weight)

    def test_meas_noise_stats(self, budget_data, params):
        p = params["noise_level"]
        d3 = params["distances"][0]
        iso = self._gen_circuit(params, d3, before_measure_flip_probability=p)
        exp_count, exp_weight = self._dem_stats(iso)
        actual = budget_data["mechanisms"]["meas_noise"]
        assert actual["dem_error_count"] == exp_count, \
            "meas_noise error count: {} vs {}".format(
                actual["dem_error_count"], exp_count)
        assert abs(actual["total_error_weight"] - exp_weight) < 1e-6, \
            "meas_noise weight: {:.8f} vs {:.8f}".format(
                actual["total_error_weight"], exp_weight)
