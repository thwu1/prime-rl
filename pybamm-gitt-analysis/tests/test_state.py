
"""
Tests for GITT analysis results.
Verifies physical consistency and correctness of the electrochemical analysis.
"""

import json
import os
import math

import pytest


RESULTS_PATH = "/app/results.json"


@pytest.fixture(scope="module")
def results():
    assert os.path.isfile(RESULTS_PATH), (
        f"Results file not found at {RESULTS_PATH}. "
        "The pipeline must write output to /app/results.json."
    )
    with open(RESULTS_PATH) as f:
        data = json.load(f)
    return data


# ── Schema checks ──────────────────────────────────────────────────────


class TestSchema:
    def test_top_level_keys(self, results):
        required = {
            "n_pulses",
            "model_used",
            "pulses",
            "average_resistance_ohm",
            "resistance_trend",
            "total_charge_removed_Ah",
        }
        assert required.issubset(results.keys()), (
            f"Missing top-level keys: {required - results.keys()}"
        )

    def test_n_pulses_value(self, results):
        assert results["n_pulses"] == 8

    def test_pulses_count(self, results):
        assert len(results["pulses"]) == 8

    def test_pulse_keys(self, results):
        required = {
            "pulse_number",
            "v_before_pulse",
            "v_end_pulse",
            "v_after_relaxation",
            "current_A",
            "internal_resistance_ohm",
            "approx_soc",
        }
        for i, p in enumerate(results["pulses"]):
            missing = required - set(p.keys())
            assert not missing, (
                f"Pulse {i + 1} missing keys: {missing}"
            )

    def test_pulse_numbers_sequential(self, results):
        numbers = [p["pulse_number"] for p in results["pulses"]]
        assert numbers == list(range(1, 9))

    def test_model_used_valid(self, results):
        assert isinstance(results["model_used"], str) and len(results["model_used"]) > 0, (
            "model_used must be a non-empty string"
        )
        assert results["model_used"] in ("SPM", "SPMe"), (
            f"model_used must be 'SPM' or 'SPMe', got '{results['model_used']}'"
        )

    def test_resistance_trend_valid(self, results):
        assert results["resistance_trend"] in ("increasing", "decreasing")

    def test_all_values_finite(self, results):
        for p in results["pulses"]:
            for key in [
                "v_before_pulse",
                "v_end_pulse",
                "v_after_relaxation",
                "current_A",
                "internal_resistance_ohm",
                "approx_soc",
            ]:
                assert math.isfinite(p[key]), (
                    f"Pulse {p['pulse_number']}: {key} = {p[key]} is not finite"
                )
        assert math.isfinite(results["average_resistance_ohm"])
        assert math.isfinite(results["total_charge_removed_Ah"])


# ── Voltage physics checks ────────────────────────────────────────────


class TestVoltagePhysics:
    def test_voltages_in_cell_window(self, results):
        """All voltages must lie within the NMC/graphite cell window."""
        for p in results["pulses"]:
            for key in ("v_before_pulse", "v_end_pulse", "v_after_relaxation"):
                v = p[key]
                assert 2.0 < v < 4.3, (
                    f"Pulse {p['pulse_number']}: {key} = {v:.4f} V "
                    f"outside (2.0, 4.3) V window"
                )

    def test_voltage_drops_during_discharge(self, results):
        """V_eq must exceed V_end_pulse (discharge lowers voltage)."""
        for p in results["pulses"]:
            assert p["v_before_pulse"] > p["v_end_pulse"], (
                f"Pulse {p['pulse_number']}: v_before ({p['v_before_pulse']:.4f}) "
                f"should exceed v_end_pulse ({p['v_end_pulse']:.4f})"
            )

    def test_voltage_recovers_during_rest(self, results):
        """Relaxed voltage must exceed end-of-pulse voltage."""
        for p in results["pulses"]:
            assert p["v_after_relaxation"] > p["v_end_pulse"], (
                f"Pulse {p['pulse_number']}: v_relax ({p['v_after_relaxation']:.4f}) "
                f"should exceed v_end_pulse ({p['v_end_pulse']:.4f})"
            )

    def test_voltage_recovery_magnitude(self, results):
        """Voltage must recover meaningfully during rest (>= 20 mV)."""
        for p in results["pulses"]:
            recovery = p["v_after_relaxation"] - p["v_end_pulse"]
            assert recovery > 0.02, (
                f"Pulse {p['pulse_number']}: voltage recovery "
                f"{recovery * 1000:.1f} mV is below 20 mV minimum "
                f"expected for this cell configuration"
            )

    def test_relaxed_voltages_decrease_monotonically(self, results):
        """Relaxed OCV must decrease as SOC decreases."""
        v_relax = [p["v_after_relaxation"] for p in results["pulses"]]
        for i in range(1, len(v_relax)):
            assert v_relax[i] < v_relax[i - 1], (
                f"v_relax[{i}] ({v_relax[i]:.4f}) should be less than "
                f"v_relax[{i - 1}] ({v_relax[i - 1]:.4f})"
            )

    def test_initial_ocv_range(self, results):
        """First pulse's V_eq should be near the fully charged OCV (~4.0-4.25V)."""
        v_init = results["pulses"][0]["v_before_pulse"]
        assert 3.9 < v_init < 4.3, (
            f"Initial OCV {v_init:.4f} V is outside expected (3.9, 4.3) V range"
        )


# ── Resistance checks ─────────────────────────────────────────────────


class TestResistance:
    def test_resistance_positive(self, results):
        for p in results["pulses"]:
            assert p["internal_resistance_ohm"] > 0, (
                f"Pulse {p['pulse_number']}: resistance must be positive"
            )

    def test_resistance_in_physical_range(self, results):
        """Typical Li-ion cell resistance is 1 mOhm to 500 mOhm."""
        for p in results["pulses"]:
            r = p["internal_resistance_ohm"]
            assert 0.001 < r < 0.5, (
                f"Pulse {p['pulse_number']}: R = {r * 1000:.1f} mOhm "
                f"outside [1, 500] mOhm range"
            )

    def test_average_resistance_consistency(self, results):
        """Average resistance must equal the mean of individual values."""
        r_vals = [p["internal_resistance_ohm"] for p in results["pulses"]]
        expected_avg = sum(r_vals) / len(r_vals)
        assert abs(results["average_resistance_ohm"] - expected_avg) < 1e-4, (
            f"Average R ({results['average_resistance_ohm']:.6f}) does not match "
            f"computed mean ({expected_avg:.6f})"
        )


# ── Current and charge checks ─────────────────────────────────────────


class TestCurrentAndCharge:
    def test_current_c_rate(self, results):
        """Current should be approximately C/3 for a ~5 Ah cell."""
        for p in results["pulses"]:
            assert 1.0 < p["current_A"] < 3.0, (
                f"Pulse {p['pulse_number']}: I = {p['current_A']:.3f} A "
                f"outside expected C/3 range for a ~5 Ah cell"
            )

    def test_total_charge_in_range(self, results):
        """Total charge should be in a physically reasonable range."""
        q = results["total_charge_removed_Ah"]
        assert 0.5 < q < 3.0, (
            f"Total charge {q:.3f} Ah outside expected range"
        )

    def test_total_charge_consistent_with_pulses(self, results):
        """Total charge should approximately equal sum of per-pulse charges."""
        pulse_charge_sum = sum(
            p["current_A"] * 300 / 3600 for p in results["pulses"]
        )
        q = results["total_charge_removed_Ah"]
        assert abs(q - pulse_charge_sum) / max(pulse_charge_sum, 1e-10) < 0.05, (
            f"Total charge {q:.4f} differs from per-pulse sum {pulse_charge_sum:.4f} "
            f"by more than 5%"
        )


# ── SOC checks ─────────────────────────────────────────────────────────


class TestSOC:
    def test_soc_in_range(self, results):
        for p in results["pulses"]:
            assert 0.0 <= p["approx_soc"] <= 1.0, (
                f"Pulse {p['pulse_number']}: SOC = {p['approx_soc']:.4f} "
                f"outside [0, 1]"
            )

    def test_soc_decreases_monotonically(self, results):
        socs = [p["approx_soc"] for p in results["pulses"]]
        for i in range(1, len(socs)):
            assert socs[i] < socs[i - 1], (
                f"SOC[{i}] ({socs[i]:.4f}) should be less than "
                f"SOC[{i - 1}] ({socs[i - 1]:.4f})"
            )

    def test_first_soc_near_unity(self, results):
        """After one pulse, SOC should still be high (> 0.9)."""
        assert results["pulses"][0]["approx_soc"] > 0.9

    def test_last_soc_reasonable(self, results):
        """After 8 pulses, SOC should still be reasonably high."""
        last_soc = results["pulses"][-1]["approx_soc"]
        assert 0.5 < last_soc < 0.95, (
            f"Final SOC {last_soc:.4f} is outside expected range"
        )
