
import json
import os
import subprocess
import shutil

import pytest


CRATE_LABELS = ["0.2C", "0.5C", "1C", "1.5C", "2C"]
RESULTS_DIR = "/app/results"


@pytest.fixture(scope="session", autouse=True)
def run_analysis():
    """Clear old results and run the analysis script fresh."""
    if os.path.exists(RESULTS_DIR):
        shutil.rmtree(RESULTS_DIR)
    result = subprocess.run(
        ["python3", "/app/analyze.py"],
        capture_output=True,
        text=True,
        timeout=240,
        cwd="/app",
    )
    assert result.returncode == 0, (
        f"analyze.py failed with exit code {result.returncode}.\n"
        f"STDOUT:\n{result.stdout[-2000:]}\n"
        f"STDERR:\n{result.stderr[-2000:]}"
    )


@pytest.fixture(scope="session")
def rate_data():
    with open(os.path.join(RESULTS_DIR, "rate_capability.json")) as f:
        return json.load(f)


@pytest.fixture(scope="session")
def decomp_data():
    with open(os.path.join(RESULTS_DIR, "voltage_decomposition.json")) as f:
        return json.load(f)


@pytest.fixture(scope="session")
def analysis_data():
    with open(os.path.join(RESULTS_DIR, "analysis.json")) as f:
        return json.load(f)


# ──────────────────────── Structure tests ────────────────────────


class TestOutputStructure:
    def test_rate_capability_file_exists(self):
        assert os.path.isfile(os.path.join(RESULTS_DIR, "rate_capability.json"))

    def test_voltage_decomposition_file_exists(self):
        assert os.path.isfile(
            os.path.join(RESULTS_DIR, "voltage_decomposition.json")
        )

    def test_analysis_file_exists(self):
        assert os.path.isfile(os.path.join(RESULTS_DIR, "analysis.json"))

    def test_rate_capability_keys(self, rate_data):
        for cr in CRATE_LABELS:
            assert cr in rate_data, f"Missing C-rate key: {cr}"
            for key in ["capacity_ah", "energy_wh", "avg_voltage_v", "max_temp_k"]:
                assert key in rate_data[cr], f"Missing key {key} for {cr}"
                assert isinstance(rate_data[cr][key], (int, float)), (
                    f"{key} at {cr} must be numeric, got {type(rate_data[cr][key])}"
                )

    def test_voltage_decomposition_keys(self, decomp_data):
        for cr in CRATE_LABELS:
            assert cr in decomp_data, f"Missing C-rate key: {cr}"
            for key in [
                "reaction_overpotential_v",
                "concentration_overpotential_v",
                "electrolyte_ohmic_v",
                "solid_phase_ohmic_v",
            ]:
                assert key in decomp_data[cr], f"Missing key {key} for {cr}"
                assert isinstance(decomp_data[cr][key], (int, float))

    def test_analysis_keys(self, analysis_data):
        assert "critical_crate" in analysis_data
        assert "peukert_exponent" in analysis_data
        assert "dominant_loss" in analysis_data
        assert isinstance(analysis_data["dominant_loss"], dict)
        for cr in CRATE_LABELS:
            assert cr in analysis_data["dominant_loss"]


# ──────────────────────── Physical constraint tests ────────────────────────


class TestPhysicalConstraints:
    def test_all_values_positive(self, rate_data):
        for cr in CRATE_LABELS:
            for key in ["capacity_ah", "energy_wh", "avg_voltage_v", "max_temp_k"]:
                assert rate_data[cr][key] > 0, f"{key} at {cr} must be positive"

    def test_capacity_decreases_with_crate(self, rate_data):
        caps = [rate_data[cr]["capacity_ah"] for cr in CRATE_LABELS]
        for i in range(len(caps) - 1):
            assert caps[i] > caps[i + 1], (
                f"Capacity must decrease: {CRATE_LABELS[i]}={caps[i]:.4f} "
                f"vs {CRATE_LABELS[i+1]}={caps[i+1]:.4f}"
            )

    def test_energy_decreases_with_crate(self, rate_data):
        energies = [rate_data[cr]["energy_wh"] for cr in CRATE_LABELS]
        for i in range(len(energies) - 1):
            assert energies[i] > energies[i + 1], (
                f"Energy must decrease: {CRATE_LABELS[i]}={energies[i]:.4f} "
                f"vs {CRATE_LABELS[i+1]}={energies[i+1]:.4f}"
            )

    def test_avg_voltage_decreases_with_crate(self, rate_data):
        voltages = [rate_data[cr]["avg_voltage_v"] for cr in CRATE_LABELS]
        for i in range(len(voltages) - 1):
            assert voltages[i] > voltages[i + 1], (
                f"Avg voltage must decrease: {CRATE_LABELS[i]}={voltages[i]:.4f} "
                f"vs {CRATE_LABELS[i+1]}={voltages[i+1]:.4f}"
            )

    def test_temperature_increases_with_crate(self, rate_data):
        temps = [rate_data[cr]["max_temp_k"] for cr in CRATE_LABELS]
        for i in range(len(temps) - 1):
            assert temps[i] < temps[i + 1], (
                f"Max temp must increase: {CRATE_LABELS[i]}={temps[i]:.2f} "
                f"vs {CRATE_LABELS[i+1]}={temps[i+1]:.2f}"
            )

    def test_temperature_above_ambient(self, rate_data):
        """A non-isothermal model must produce temperatures above ambient."""
        for cr in CRATE_LABELS:
            assert rate_data[cr]["max_temp_k"] > 298.15, (
                f"Temperature at {cr} not above ambient — thermal model may be wrong"
            )

    def test_voltage_losses_nonnegative(self, decomp_data):
        for cr in CRATE_LABELS:
            for key in [
                "reaction_overpotential_v",
                "concentration_overpotential_v",
                "electrolyte_ohmic_v",
                "solid_phase_ohmic_v",
            ]:
                assert decomp_data[cr][key] >= 0, (
                    f"{key} at {cr} must be non-negative, got {decomp_data[cr][key]}"
                )

    def test_total_voltage_loss_increases_with_crate(self, decomp_data):
        loss_keys = [
            "reaction_overpotential_v",
            "concentration_overpotential_v",
            "electrolyte_ohmic_v",
            "solid_phase_ohmic_v",
        ]
        totals = [
            sum(decomp_data[cr][k] for k in loss_keys) for cr in CRATE_LABELS
        ]
        for i in range(len(totals) - 1):
            assert totals[i] < totals[i + 1], (
                f"Total voltage loss must increase: {CRATE_LABELS[i]}={totals[i]:.4f} "
                f"vs {CRATE_LABELS[i+1]}={totals[i+1]:.4f}"
            )


# ──────────────────────── Value range tests ────────────────────────


class TestValueRanges:
    def test_capacity_at_low_crate(self, rate_data):
        """Chen2020 (LG M50) is ~5 Ah nominal."""
        cap = rate_data["0.2C"]["capacity_ah"]
        assert 4.5 < cap < 5.5, f"0.2C capacity {cap:.3f} Ah outside expected range"

    def test_capacity_at_high_crate(self, rate_data):
        """2C should still deliver substantial capacity for Chen2020 cell."""
        cap = rate_data["2C"]["capacity_ah"]
        assert 4.0 < cap < 5.5, f"2C capacity {cap:.3f} Ah outside expected range"

    def test_energy_at_low_crate(self, rate_data):
        """Energy at 0.2C should be near nominal (5 Ah * ~3.65 V ~ 18 Wh)."""
        e = rate_data["0.2C"]["energy_wh"]
        assert 15.0 < e < 22.0, f"0.2C energy {e:.3f} Wh outside expected range"

    def test_energy_at_high_crate(self, rate_data):
        e = rate_data["2C"]["energy_wh"]
        assert 12.0 < e < 20.0, f"2C energy {e:.3f} Wh outside expected range"

    def test_temperature_at_low_crate(self, rate_data):
        temp = rate_data["0.2C"]["max_temp_k"]
        assert 298.0 < temp < 310.0, (
            f"0.2C max temp {temp:.2f} K unexpected (should be near ambient)"
        )

    def test_temperature_at_high_crate(self, rate_data):
        temp = rate_data["2C"]["max_temp_k"]
        assert temp > 310.0, f"2C max temp {temp:.2f} K too low for thermal model"
        assert temp < 380.0, f"2C max temp {temp:.2f} K unreasonably high"

    def test_avg_voltage_in_range(self, rate_data):
        for cr in CRATE_LABELS:
            v = rate_data[cr]["avg_voltage_v"]
            assert 2.5 < v < 4.2, f"Avg voltage {v:.3f} V at {cr} out of cell range"

    def test_peukert_exponent_range(self, analysis_data):
        k = analysis_data["peukert_exponent"]
        assert 1.0 < k < 2.0, (
            f"Peukert exponent {k:.4f} outside typical Li-ion range [1.0, 2.0]"
        )


# ──────────────────────── Consistency tests ────────────────────────


class TestConsistency:
    def test_energy_equals_capacity_times_voltage(self, rate_data):
        for cr in CRATE_LABELS:
            d = rate_data[cr]
            expected = d["capacity_ah"] * d["avg_voltage_v"]
            actual = d["energy_wh"]
            rel_err = abs(expected - actual) / actual
            assert rel_err < 0.02, (
                f"Energy inconsistency at {cr}: cap*V={expected:.4f} vs "
                f"energy={actual:.4f} (err={rel_err:.4f})"
            )

    def test_critical_crate_is_valid(self, analysis_data, rate_data):
        crit = analysis_data["critical_crate"]
        assert crit in CRATE_LABELS, f"Invalid critical C-rate: {crit}"
        cap_ref = rate_data["0.2C"]["capacity_ah"]
        cap_crit = rate_data[crit]["capacity_ah"]
        assert cap_crit >= 0.8 * cap_ref, (
            f"Critical C-rate {crit} delivers {cap_crit:.4f} Ah < "
            f"80% of 0.2C ({0.8 * cap_ref:.4f} Ah)"
        )

    def test_critical_crate_is_highest(self, analysis_data, rate_data):
        """No higher tested C-rate should also meet the 80% threshold."""
        crit = analysis_data["critical_crate"]
        crit_idx = CRATE_LABELS.index(crit)
        cap_ref = rate_data["0.2C"]["capacity_ah"]
        for label in CRATE_LABELS[crit_idx + 1 :]:
            cap = rate_data[label]["capacity_ah"]
            assert cap < 0.8 * cap_ref, (
                f"{label} also meets 80% threshold ({cap:.4f} >= "
                f"{0.8 * cap_ref:.4f}) but wasn't chosen as critical"
            )

    def test_dominant_loss_matches_decomposition(self, analysis_data, decomp_data):
        key_map = {
            "reaction_overpotential": "reaction_overpotential_v",
            "concentration_overpotential": "concentration_overpotential_v",
            "electrolyte_ohmic": "electrolyte_ohmic_v",
            "solid_phase_ohmic": "solid_phase_ohmic_v",
        }
        for cr in CRATE_LABELS:
            claimed = analysis_data["dominant_loss"][cr]
            assert claimed in key_map, f"Invalid mechanism name: {claimed}"
            losses = {
                name: decomp_data[cr][vkey] for name, vkey in key_map.items()
            }
            actual_dominant = max(losses, key=losses.get)
            assert claimed == actual_dominant, (
                f"At {cr}, claimed dominant={claimed} "
                f"but actual dominant={actual_dominant} (values: {losses})"
            )

    def test_dominant_loss_valid_names(self, analysis_data):
        valid = {
            "reaction_overpotential",
            "concentration_overpotential",
            "electrolyte_ohmic",
            "solid_phase_ohmic",
        }
        for cr in CRATE_LABELS:
            assert analysis_data["dominant_loss"][cr] in valid


# ──────────────────────── Anti-cheat: independent simulation ────────────────────────


@pytest.fixture(scope="session")
def independent_1c_solution():
    """Run an independent 1C SPMe simulation for cross-checking."""
    import pybamm

    model = pybamm.lithium_ion.SPMe(options={"thermal": "lumped"})
    param = pybamm.ParameterValues("Chen2020")
    param.update({"Ambient temperature [K]": 298.15})

    experiment = pybamm.Experiment(["Discharge at 1C until 2.5 V"])
    sim = pybamm.Simulation(
        model, parameter_values=param, experiment=experiment
    )
    return sim.solve(initial_soc=1.0)


class TestAntiCheat:
    def test_independent_1c_capacity(self, rate_data, independent_1c_solution):
        """Compare capacity against an independent 1C simulation."""
        sol = independent_1c_solution
        Q_ref = float(sol["Discharge capacity [A.h]"].entries[-1])
        Q_agent = rate_data["1C"]["capacity_ah"]

        rel_err = abs(Q_agent - Q_ref) / Q_ref
        assert rel_err < 0.05, (
            f"1C capacity mismatch: agent={Q_agent:.4f}, "
            f"independent={Q_ref:.4f}, rel_err={rel_err:.4f}"
        )

    def test_independent_1c_max_temperature(
        self, rate_data, independent_1c_solution
    ):
        """Compare max temperature against an independent 1C simulation."""
        import numpy as np

        sol = independent_1c_solution

        temp_var = None
        for name in [
            "X-averaged cell temperature [K]",
            "Cell temperature [K]",
            "Volume-averaged cell temperature [K]",
        ]:
            try:
                temp_var = sol[name].entries
                break
            except KeyError:
                continue

        if temp_var is not None:
            T_ref = float(np.max(temp_var))
            T_agent = rate_data["1C"]["max_temp_k"]
            rel_err = abs(T_agent - T_ref) / T_ref
            assert rel_err < 0.05, (
                f"1C max temp mismatch: agent={T_agent:.2f}, "
                f"independent={T_ref:.2f}, rel_err={rel_err:.4f}"
            )

    def test_independent_1c_energy(self, rate_data, independent_1c_solution):
        """Verify energy is in the correct range (Wh, not V*s or V*h)."""
        import numpy as np

        sol = independent_1c_solution
        t = sol["Time [s]"].entries
        V = sol["Terminal voltage [V]"].entries
        I = sol["Current [A]"].entries
        E_ref = float(np.trapezoid(V * np.abs(I), t) / 3600.0)
        E_agent = rate_data["1C"]["energy_wh"]

        rel_err = abs(E_agent - E_ref) / E_ref
        assert rel_err < 0.05, (
            f"1C energy mismatch: agent={E_agent:.4f} Wh, "
            f"independent={E_ref:.4f} Wh, rel_err={rel_err:.4f}"
        )
