"""Tests for battery model characterization results."""

import json
import os
import numpy as np
import pytest


RESULTS_PATH = "/app/results.json"
C_RATES = ["0.5", "1.0", "2.0", "3.0"]
RMSE_RATES = ["1.0", "3.0"]


@pytest.fixture
def results():
    with open(RESULTS_PATH) as f:
        return json.load(f)


# ── Structure tests ──────────────────────────────────────────────────

class TestStructure:
    def test_results_file_exists(self):
        assert os.path.isfile(RESULTS_PATH), "results.json not found at /app/results.json"

    def test_valid_json(self):
        with open(RESULTS_PATH) as f:
            data = json.load(f)
        assert isinstance(data, dict)

    def test_required_top_level_keys(self, results):
        required = [
            "capacities_spm",
            "capacities_dfn",
            "relative_errors_pct",
            "voltage_rmse",
            "max_temperature_rise_3C",
            "electrolyte_conc_range_3C",
        ]
        for key in required:
            assert key in results, f"Missing required key: {key}"

    def test_crate_keys_spm(self, results):
        for cr in C_RATES:
            assert cr in results["capacities_spm"], (
                f"Missing C-rate {cr} in capacities_spm"
            )

    def test_crate_keys_dfn(self, results):
        for cr in C_RATES:
            assert cr in results["capacities_dfn"], (
                f"Missing C-rate {cr} in capacities_dfn"
            )

    def test_crate_keys_errors(self, results):
        for cr in C_RATES:
            assert cr in results["relative_errors_pct"], (
                f"Missing C-rate {cr} in relative_errors_pct"
            )

    def test_rmse_keys(self, results):
        for cr in RMSE_RATES:
            assert cr in results["voltage_rmse"], (
                f"Missing C-rate {cr} in voltage_rmse"
            )


# ── Capacity physics tests ───────────────────────────────────────────

class TestCapacityPhysics:
    def test_capacities_positive(self, results):
        for model in ["capacities_spm", "capacities_dfn"]:
            for cr, cap in results[model].items():
                assert cap > 0, f"{model}[{cr}]: capacity must be positive, got {cap}"

    def test_capacities_in_plausible_range(self, results):
        """Chen2020 models an LG M50 ~5 Ah cell."""
        for model in ["capacities_spm", "capacities_dfn"]:
            for cr, cap in results[model].items():
                assert 2.0 < cap < 6.0, (
                    f"{model}[{cr}]: capacity {cap} Ah outside plausible range (2.0-6.0)"
                )

    def test_dfn_capacity_decreases_with_crate(self, results):
        caps = [results["capacities_dfn"][cr] for cr in C_RATES]
        for i in range(len(caps) - 1):
            assert caps[i] >= caps[i + 1] - 0.05, (
                f"DFN: capacity at {C_RATES[i]}C ({caps[i]:.4f} Ah) should be >= "
                f"capacity at {C_RATES[i+1]}C ({caps[i+1]:.4f} Ah)"
            )

    def test_spm_capacity_decreases_with_crate(self, results):
        caps = [results["capacities_spm"][cr] for cr in C_RATES]
        for i in range(len(caps) - 1):
            assert caps[i] >= caps[i + 1] - 0.05, (
                f"SPM: capacity at {C_RATES[i]}C ({caps[i]:.4f} Ah) should be >= "
                f"capacity at {C_RATES[i+1]}C ({caps[i+1]:.4f} Ah)"
            )

    def test_dfn_1c_capacity_in_expected_range(self, results):
        """DFN 1C capacity should be close to nominal 5 Ah for Chen2020."""
        cap = results["capacities_dfn"]["1.0"]
        assert 4.5 < cap < 5.2, (
            f"DFN 1C capacity {cap:.4f} Ah outside expected range (4.5-5.2)"
        )

    def test_dfn_3c_capacity_notably_reduced(self, results):
        """At 3C, capacity should be notably less than at 0.5C."""
        cap_low = results["capacities_dfn"]["0.5"]
        cap_high = results["capacities_dfn"]["3.0"]
        assert cap_high < cap_low - 0.1, (
            f"DFN 3C ({cap_high:.4f}) should be notably less than 0.5C ({cap_low:.4f})"
        )

    def test_spm_gte_dfn_capacity(self, results):
        """SPM omits electrolyte transport losses, so its capacity should
        be >= DFN capacity (or very close)."""
        for cr in C_RATES:
            spm = results["capacities_spm"][cr]
            dfn = results["capacities_dfn"][cr]
            assert dfn <= spm + 0.05, (
                f"At {cr}C: DFN ({dfn:.4f}) should not exceed SPM ({spm:.4f}) + tolerance"
            )


# ── Relative error tests ────────────────────────────────────────────

class TestRelativeErrors:
    def test_errors_nonnegative(self, results):
        for cr, err in results["relative_errors_pct"].items():
            assert err >= 0, f"Error at {cr}C is negative: {err}"

    def test_errors_match_capacity_formula(self, results):
        """Reported errors must be consistent with |SPM-DFN|/DFN * 100."""
        for cr in C_RATES:
            cap_s = results["capacities_spm"][cr]
            cap_d = results["capacities_dfn"][cr]
            expected = abs(cap_s - cap_d) / cap_d * 100
            actual = results["relative_errors_pct"][cr]
            assert abs(actual - expected) < 0.5, (
                f"At {cr}C: reported error {actual:.4f}% != "
                f"capacity-derived {expected:.4f}%"
            )

    def test_low_crate_models_agree(self, results):
        """SPM and DFN should agree within 2% at 0.5C."""
        err = results["relative_errors_pct"]["0.5"]
        assert err < 2.0, (
            f"0.5C relative error {err:.4f}% exceeds 2% — models should agree at low rates"
        )

    def test_high_crate_greater_divergence(self, results):
        """Error at 3C should exceed error at 0.5C."""
        err_low = results["relative_errors_pct"]["0.5"]
        err_high = results["relative_errors_pct"]["3.0"]
        assert err_high > err_low, (
            f"Error at 3C ({err_high:.4f}%) should exceed error at 0.5C ({err_low:.4f}%)"
        )


# ── Voltage RMSE tests ──────────────────────────────────────────────

class TestVoltageRMSE:
    def test_rmse_positive(self, results):
        for cr, rmse in results["voltage_rmse"].items():
            assert rmse > 0, f"RMSE at {cr}C must be positive, got {rmse}"

    def test_rmse_reasonable_magnitude(self, results):
        """RMSE should not exceed 0.5 V for plausible simulations."""
        for cr, rmse in results["voltage_rmse"].items():
            assert rmse < 0.5, (
                f"RMSE at {cr}C ({rmse:.6f} V) exceeds 0.5 V — implausible"
            )

    def test_rmse_increases_with_crate(self, results):
        rmse_1 = results["voltage_rmse"]["1.0"]
        rmse_3 = results["voltage_rmse"]["3.0"]
        assert rmse_3 > rmse_1, (
            f"RMSE at 3C ({rmse_3:.6f}) should exceed RMSE at 1C ({rmse_1:.6f})"
        )


# ── Thermal tests ────────────────────────────────────────────────────

class TestThermal:
    def test_temperature_rise_significant_at_3c(self, results):
        """At 3C with proper thermal model, cell should heat up above ambient."""
        rise = results["max_temperature_rise_3C"]
        assert rise > 5.0, (
            f"Temperature rise {rise:.2f} C at 3C too low — "
            f"thermal model may be inactive or misconfigured"
        )

    def test_temperature_rise_physically_plausible(self, results):
        rise = results["max_temperature_rise_3C"]
        assert rise < 60.0, (
            f"Temperature rise {rise:.2f} C at 3C implausibly high"
        )


# ── Electrolyte tests ────────────────────────────────────────────────

class TestElectrolyte:
    def test_conc_range_significant_at_3c(self, results):
        """At 3C, DFN should develop a significant electrolyte
        concentration gradient by end of discharge."""
        cr = results["electrolyte_conc_range_3C"]
        assert cr > 50.0, (
            f"Electrolyte concentration range {cr:.1f} mol/m3 too small — "
            f"check extraction timestep and model type"
        )

    def test_conc_range_physically_plausible(self, results):
        cr = results["electrolyte_conc_range_3C"]
        assert cr < 5000.0, (
            f"Electrolyte concentration range {cr:.1f} mol/m3 implausibly large"
        )


# ── Reference simulation spot-checks ─────────────────────────────────

class TestReferenceSimulations:
    def test_dfn_1c_capacity_matches_reference(self, results):
        """Run an independent DFN 1C discharge and verify reported capacity."""
        import pybamm

        model = pybamm.lithium_ion.DFN(options={"thermal": "lumped"})
        param = pybamm.ParameterValues("Chen2020")
        exp = pybamm.Experiment(["Discharge at 1C until 2.5 V"])
        sim = pybamm.Simulation(model, parameter_values=param, experiment=exp)
        sol = sim.solve()
        ref_cap = float(sol["Discharge capacity [A.h]"].entries[-1])

        reported = results["capacities_dfn"]["1.0"]
        rel_diff = abs(ref_cap - reported) / ref_cap * 100
        assert rel_diff < 2.0, (
            f"DFN 1C: reference={ref_cap:.4f}, reported={reported:.4f}, "
            f"diff={rel_diff:.2f}%"
        )

    def test_spm_1c_capacity_matches_reference(self, results):
        """Run an independent SPM 1C discharge and verify reported capacity."""
        import pybamm

        model = pybamm.lithium_ion.SPM(options={"thermal": "lumped"})
        param = pybamm.ParameterValues("Chen2020")
        exp = pybamm.Experiment(["Discharge at 1C until 2.5 V"])
        sim = pybamm.Simulation(model, parameter_values=param, experiment=exp)
        sol = sim.solve()
        ref_cap = float(sol["Discharge capacity [A.h]"].entries[-1])

        reported = results["capacities_spm"]["1.0"]
        rel_diff = abs(ref_cap - reported) / ref_cap * 100
        assert rel_diff < 2.0, (
            f"SPM 1C: reference={ref_cap:.4f}, reported={reported:.4f}, "
            f"diff={rel_diff:.2f}%"
        )

    def test_voltage_rmse_1c_matches_reference(self, results):
        """Run independent RMSE calculation at 1C with proper time alignment."""
        import pybamm

        param = pybamm.ParameterValues("Chen2020")

        model_s = pybamm.lithium_ion.SPM(options={"thermal": "lumped"})
        exp = pybamm.Experiment(["Discharge at 1C until 2.5 V"])
        sim_s = pybamm.Simulation(model_s, parameter_values=param, experiment=exp)
        sol_s = sim_s.solve()

        model_d = pybamm.lithium_ion.DFN(options={"thermal": "lumped"})
        sim_d = pybamm.Simulation(model_d, parameter_values=param, experiment=exp)
        sol_d = sim_d.solve()

        t_end = min(float(sol_s.t[-1]), float(sol_d.t[-1]))
        t_eval = np.linspace(0, t_end, 100)
        v_s = np.asarray(sol_s["Terminal voltage [V]"](t_eval)).flatten()
        v_d = np.asarray(sol_d["Terminal voltage [V]"](t_eval)).flatten()
        ref_rmse = float(np.sqrt(np.mean((v_s - v_d) ** 2)))

        reported = results["voltage_rmse"]["1.0"]
        rel_diff = abs(ref_rmse - reported) / max(ref_rmse, 1e-6) * 100
        assert rel_diff < 40.0, (
            f"RMSE 1C: reference={ref_rmse:.6f}, reported={reported:.6f}, "
            f"diff={rel_diff:.1f}%"
        )
