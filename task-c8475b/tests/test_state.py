"""
Tests for Battery Model Fidelity Analysis.
Verifies structure, physical plausibility, self-consistency, and cross-
validates against independent PyBaMM computation.
"""

import json
import os
import subprocess

import numpy as np
import pytest


@pytest.fixture(scope="session")
def results():
    """Run the agent's analysis script and load the results."""
    os.environ["PYBAMM_DISABLE_TELEMETRY"] = "true"
    _cfg = os.path.expanduser("~/.config/pybamm")
    os.makedirs(_cfg, exist_ok=True)
    with open(os.path.join(_cfg, "config.yml"), "w") as fh:
        fh.write("pybamm:\n  enable_telemetry: false\n")

    result = subprocess.run(
        ["python3", "/app/model_fidelity.py"],
        capture_output=True,
        text=True,
        timeout=480,
        cwd="/app",
    )
    assert result.returncode == 0, (
        f"model_fidelity.py failed (exit {result.returncode}).\n"
        f"STDERR (last 3000 chars):\n{result.stderr[-3000:]}\n"
        f"STDOUT (last 1000 chars):\n{result.stdout[-1000:]}"
    )
    assert os.path.exists("/app/results.json"), "results.json was not created"
    with open("/app/results.json") as fh:
        return json.load(fh)


EXPECTED_RATES = ["C/20", "C/5", "C/2", "1C", "2C", "3C"]
RATE_FIELDS = [
    "spm_capacity_Ah",
    "spme_capacity_Ah",
    "max_voltage_error_mV",
    "rms_voltage_error_mV",
    "capacity_diff_pct",
]
RATE_NUMERIC = {
    "C/20": 0.05, "C/5": 0.2, "C/2": 0.5,
    "1C": 1.0, "2C": 2.0, "3C": 3.0,
}


# ─── Structure ───────────────────────────────────────────────────────────────


class TestStructure:
    def test_top_level_keys(self, results):
        required = {
            "discharge_comparison",
            "ica_peaks",
            "critical_crate",
            "voltage_decomposition_1C_50pct",
            "energy_1C",
        }
        for key in required:
            assert key in results, f"Missing top-level key: {key}"

    def test_all_crates_present(self, results):
        for rate in EXPECTED_RATES:
            assert rate in results["discharge_comparison"], f"Missing C-rate: {rate}"

    def test_discharge_fields_present(self, results):
        for rate in EXPECTED_RATES:
            data = results["discharge_comparison"][rate]
            for field in RATE_FIELDS:
                assert field in data, f"Missing field '{field}' for rate {rate}"
                assert isinstance(data[field], (int, float)), (
                    f"Field '{field}' for {rate} is not numeric"
                )

    def test_ica_structure(self, results):
        ica = results["ica_peaks"]
        for model in ["spm", "spme"]:
            assert model in ica, f"Missing ICA model key: {model}"
            assert "peak_voltages_V" in ica[model]
            assert isinstance(ica[model]["peak_voltages_V"], list)

    def test_critical_crate_type(self, results):
        val = results["critical_crate"]
        assert val is None or isinstance(val, (int, float)), (
            "critical_crate must be a float or null"
        )

    def test_voltage_decomposition_keys(self, results):
        vd = results["voltage_decomposition_1C_50pct"]
        for key in ["ocv_V", "terminal_voltage_V", "total_overpotential_mV"]:
            assert key in vd, f"Missing '{key}' in voltage_decomposition"
            assert isinstance(vd[key], (int, float)), f"{key} is not numeric"

    def test_energy_1c_keys(self, results):
        eng = results["energy_1C"]
        for key in ["spm_energy_Wh", "spme_energy_Wh", "energy_difference_pct"]:
            assert key in eng, f"Missing '{key}' in energy_1C"
            assert isinstance(eng[key], (int, float)), f"{key} is not numeric"


# ─── Physical plausibility ───────────────────────────────────────────────────


class TestPhysicalBounds:
    def test_capacity_range(self, results):
        """Chen2020 is a ~5 Ah cell.  SPM delivers 1-6 Ah at any rate.
        SPMe may hit the voltage cutoff much earlier at 3C due to
        electrolyte-concentration limitations, so we allow > 0.05 Ah there."""
        for rate in EXPECTED_RATES:
            d = results["discharge_comparison"][rate]
            # SPM ignores electrolyte effects, so capacity stays high
            assert 1.0 < d["spm_capacity_Ah"] <= 6.0, (
                f"SPM capacity {d['spm_capacity_Ah']} out of range at {rate}"
            )
            # SPMe can produce very low capacity at extreme C-rates
            min_spme = 0.05 if rate == "3C" else 1.0
            assert min_spme < d["spme_capacity_Ah"] <= 6.0, (
                f"SPMe capacity {d['spme_capacity_Ah']} out of range at {rate}"
            )

    def test_low_rate_capacity_near_nominal(self, results):
        """At C/20, delivered capacity should be close to nominal ~5 Ah."""
        d = results["discharge_comparison"]["C/20"]
        assert abs(d["spm_capacity_Ah"] - 5.0) < 0.6
        assert abs(d["spme_capacity_Ah"] - 5.0) < 0.6

    def test_voltage_errors_nonnegative(self, results):
        for rate in EXPECTED_RATES:
            d = results["discharge_comparison"][rate]
            assert d["max_voltage_error_mV"] >= 0
            assert d["rms_voltage_error_mV"] >= 0

    def test_low_rate_model_agreement(self, results):
        """At C/20, SPM and SPMe should agree closely (< 5 mV RMS)."""
        d = results["discharge_comparison"]["C/20"]
        assert d["rms_voltage_error_mV"] < 5.0, (
            f"SPM/SPMe should agree at C/20 but RMS error = "
            f"{d['rms_voltage_error_mV']} mV"
        )

    def test_capacity_diff_nonnegative(self, results):
        for rate in EXPECTED_RATES:
            assert results["discharge_comparison"][rate]["capacity_diff_pct"] >= 0

    def test_ica_peak_voltages_in_window(self, results):
        for model in ["spm", "spme"]:
            for v in results["ica_peaks"][model]["peak_voltages_V"]:
                assert 2.5 <= v <= 4.2, (
                    f"ICA peak voltage {v} V outside cell window for {model}"
                )

    def test_ocv_at_50pct(self, results):
        """OCV at 50% DOD for NMC/graphite should be ~3.4–3.9 V."""
        vd = results["voltage_decomposition_1C_50pct"]
        assert 3.2 < vd["ocv_V"] < 4.0, (
            f"OCV {vd['ocv_V']} V at 50% DOD outside expected range"
        )

    def test_terminal_voltage_range(self, results):
        vd = results["voltage_decomposition_1C_50pct"]
        assert 2.5 < vd["terminal_voltage_V"] < 4.2

    def test_overpotential_positive(self, results):
        """During discharge OCV > terminal voltage, so overpotential > 0."""
        vd = results["voltage_decomposition_1C_50pct"]
        assert vd["total_overpotential_mV"] > 0

    def test_overpotential_reasonable(self, results):
        """Total overpotential at 1C should be 5–500 mV."""
        vd = results["voltage_decomposition_1C_50pct"]
        assert 5 < vd["total_overpotential_mV"] < 500

    def test_energy_positive(self, results):
        eng = results["energy_1C"]
        assert eng["spm_energy_Wh"] > 0
        assert eng["spme_energy_Wh"] > 0

    def test_energy_range(self, results):
        """Energy at 1C for a ~5 Ah, ~3.5 V cell should be 10–25 Wh."""
        eng = results["energy_1C"]
        for key in ["spm_energy_Wh", "spme_energy_Wh"]:
            assert 10 < eng[key] < 25, f"{key}={eng[key]} outside plausible range"


# ─── Self-consistency ────────────────────────────────────────────────────────


class TestSelfConsistency:
    def test_error_increases_with_rate(self, results):
        """RMS voltage error at 3C should exceed error at C/20."""
        err_lo = results["discharge_comparison"]["C/20"]["rms_voltage_error_mV"]
        err_hi = results["discharge_comparison"]["3C"]["rms_voltage_error_mV"]
        assert err_hi > err_lo

    def test_capacity_decreases_with_rate(self, results):
        """SPMe capacity should decrease from C/20 to 2C (3C may be
        anomalously low due to model limitations, so we compare to 2C)."""
        cap_lo = results["discharge_comparison"]["C/20"]["spme_capacity_Ah"]
        cap_2c = results["discharge_comparison"]["2C"]["spme_capacity_Ah"]
        assert cap_lo > cap_2c

    def test_max_error_geq_rms_error(self, results):
        for rate in EXPECTED_RATES:
            d = results["discharge_comparison"][rate]
            assert d["max_voltage_error_mV"] >= d["rms_voltage_error_mV"] - 0.1

    def test_critical_crate_consistent(self, results):
        """If a critical C-rate is reported, verify it matches the error data."""
        critical = results["critical_crate"]
        if critical is not None:
            found = False
            for rate_name in EXPECTED_RATES:
                if abs(RATE_NUMERIC[rate_name] - critical) < 0.01:
                    rms = results["discharge_comparison"][rate_name][
                        "rms_voltage_error_mV"
                    ]
                    assert rms > 10.0
                    found = True
                    break
            assert found, f"Critical C-rate {critical} doesn't match any tested rate"

            for rate_name in EXPECTED_RATES:
                if RATE_NUMERIC[rate_name] < critical - 0.001:
                    rms = results["discharge_comparison"][rate_name][
                        "rms_voltage_error_mV"
                    ]
                    assert rms <= 10.0
        else:
            for rate_name in EXPECTED_RATES:
                rms = results["discharge_comparison"][rate_name][
                    "rms_voltage_error_mV"
                ]
                assert rms <= 10.0

    def test_ica_peaks_detected(self, results):
        """Both models should identify at least one ICA peak at C/20."""
        for model in ["spm", "spme"]:
            peaks = results["ica_peaks"][model]["peak_voltages_V"]
            assert len(peaks) >= 1, f"No ICA peaks found for {model}"

    def test_energy_models_close(self, results):
        """SPM and SPMe energies at 1C should differ by less than 10%."""
        eng = results["energy_1C"]
        assert eng["energy_difference_pct"] < 10.0

    def test_ocv_above_terminal(self, results):
        """OCV should be above terminal voltage during discharge."""
        vd = results["voltage_decomposition_1C_50pct"]
        assert vd["ocv_V"] > vd["terminal_voltage_V"]


# ─── Cross-check: reference 1C capacity via independent computation ─────────


class TestReferenceCheck:
    def _run_reference_discharge(self, model_class, c_rate=1.0):
        """Run an independent galvanostatic discharge using PyBaMM."""
        import pybamm

        pybamm.set_logging_level("WARNING")
        model = model_class()
        param = pybamm.ParameterValues("Chen2020")
        cap_nom = param["Nominal cell capacity [A.h]"]
        param["Current function [A]"] = cap_nom * c_rate

        sim = pybamm.Simulation(model, parameter_values=param)
        t_end = 3600.0 / c_rate * 1.5
        sol = sim.solve(np.linspace(0, t_end, 300))
        return float(
            np.asarray(sol["Discharge capacity [A.h]"].entries).flatten()[-1]
        )

    def test_spme_1c_capacity_reference(self, results):
        """Independent 1C SPMe discharge must match reported capacity."""
        import pybamm

        ref_cap = self._run_reference_discharge(pybamm.lithium_ion.SPMe, 1.0)
        agent_cap = results["discharge_comparison"]["1C"]["spme_capacity_Ah"]
        rel_err = abs(agent_cap - ref_cap) / ref_cap
        assert rel_err < 0.05, (
            f"1C SPMe capacity mismatch: ref={ref_cap:.4f}, "
            f"agent={agent_cap:.4f} ({rel_err*100:.1f}%)"
        )

    def test_spm_1c_capacity_reference(self, results):
        """Independent 1C SPM discharge must match reported capacity."""
        import pybamm

        ref_cap = self._run_reference_discharge(pybamm.lithium_ion.SPM, 1.0)
        agent_cap = results["discharge_comparison"]["1C"]["spm_capacity_Ah"]
        rel_err = abs(agent_cap - ref_cap) / ref_cap
        assert rel_err < 0.05, (
            f"1C SPM capacity mismatch: ref={ref_cap:.4f}, "
            f"agent={agent_cap:.4f} ({rel_err*100:.1f}%)"
        )
