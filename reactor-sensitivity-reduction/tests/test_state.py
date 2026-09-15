
import os
import json
import csv
import math
import pytest
import numpy as np
import cantera as ct


def read_csv(filepath):
    with open(filepath, "r") as f:
        reader = csv.DictReader(f)
        return list(reader)


def load_json(filepath):
    with open(filepath, "r") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# 1. Ignition Delays
# ---------------------------------------------------------------------------
class TestIgnitionDelays:
    def test_file_exists(self):
        assert os.path.exists("/app/ignition_delays.json")

    def test_all_conditions_present(self):
        data = load_json("/app/ignition_delays.json")
        assert set(data.keys()) == {"A", "B", "C", "D", "E", "F"}

    def test_values_positive_and_reasonable(self):
        data = load_json("/app/ignition_delays.json")
        for cond, val in data.items():
            v = float(val)
            assert 0.001 < v < 500, f"{cond}: {v} ms out of (0.001, 500)"

    def test_higher_temperature_shorter_delay(self):
        data = load_json("/app/ignition_delays.json")
        d = {k: float(v) for k, v in data.items()}
        assert d["A"] > d["B"] > d["C"], "P=1atm Arrhenius ordering violated"
        assert d["D"] > d["E"] > d["F"], "P=10atm Arrhenius ordering violated"

    def test_higher_pressure_shorter_delay(self):
        data = load_json("/app/ignition_delays.json")
        d = {k: float(v) for k, v in data.items()}
        assert d["A"] > d["D"], "1200K pressure ordering violated"
        assert d["B"] > d["E"], "1400K pressure ordering violated"
        assert d["C"] > d["F"], "1600K pressure ordering violated"

    def test_cross_check_condition_e(self):
        """Independently compute ignition delay at 1400K / 10atm."""
        gas = ct.Solution("gri30.yaml")
        gas.set_equivalence_ratio(1.0, "CH4:1", "O2:1, N2:3.76")
        gas.TP = 1400, 10 * ct.one_atm

        r = ct.IdealGasConstPressureReactor(gas)
        sim = ct.ReactorNet([r])

        times, temps = [], []
        while sim.time < 2.0:
            sim.step()
            times.append(sim.time)
            temps.append(r.T)
            if r.T > 2500:
                break

        times = np.array(times)
        temps = np.array(temps)
        dTdt = np.diff(temps) / np.diff(times)
        tau_ref = times[np.argmax(dTdt)] * 1000  # ms

        data = load_json("/app/ignition_delays.json")
        tau_sub = float(data["E"])
        rel = abs(tau_sub - tau_ref) / tau_ref
        assert rel < 0.05, (
            f"Condition E: {tau_sub:.4f} vs ref {tau_ref:.4f} ms ({rel*100:.1f}%)"
        )


# ---------------------------------------------------------------------------
# 2. Flame Temperatures
# ---------------------------------------------------------------------------
class TestFlameTemperatures:
    def test_file_exists(self):
        assert os.path.exists("/app/flame_temperatures.json")

    def test_all_phis_present(self):
        data = load_json("/app/flame_temperatures.json")
        assert set(data.keys()) == {"0.5", "0.7", "0.9", "1.0", "1.2"}

    def test_values_reasonable(self):
        data = load_json("/app/flame_temperatures.json")
        for phi, T in data.items():
            v = float(T)
            assert 1200 < v < 2500, f"phi={phi}: T_ad={v} K out of (1200, 2500)"

    def test_temperature_trend(self):
        """Flame temp increases lean-to-stoichiometric, decreases rich."""
        data = load_json("/app/flame_temperatures.json")
        d = {k: float(v) for k, v in data.items()}
        assert d["0.5"] < d["0.7"] < d["0.9"] < d["1.0"], (
            "Lean-to-stoichiometric increase violated"
        )
        assert d["1.0"] > d["1.2"], "Rich-side decrease violated"

    def test_cross_check_phi_10(self):
        """Independently compute adiabatic flame temperature at phi=1.0."""
        gas = ct.Solution("gri30.yaml")
        gas.TP = 300.0, ct.one_atm
        gas.set_equivalence_ratio(1.0, "CH4:1", "O2:1, N2:3.76")
        gas.equilibrate("HP")
        T_ref = gas.T

        data = load_json("/app/flame_temperatures.json")
        T_sub = float(data["1.0"])
        rel = abs(T_sub - T_ref) / T_ref
        assert rel < 0.001, (
            f"phi=1.0: {T_sub:.2f} vs ref {T_ref:.2f} K ({rel*100:.3f}%)"
        )


# ---------------------------------------------------------------------------
# 3. Ignition Sensitivity
# ---------------------------------------------------------------------------
class TestIgnitionSensitivity:
    def test_file_exists(self):
        assert os.path.exists("/app/ignition_sensitivity.csv")

    def test_row_count(self):
        rows = read_csv("/app/ignition_sensitivity.csv")
        assert len(rows) == 30

    def test_required_columns(self):
        rows = read_csv("/app/ignition_sensitivity.csv")
        for col in ("rank", "reaction_index", "equation", "sensitivity_coefficient"):
            assert col in rows[0], f"Missing column: {col}"

    def test_sorted_descending_magnitude(self):
        rows = read_csv("/app/ignition_sensitivity.csv")
        mags = [abs(float(r["sensitivity_coefficient"])) for r in rows]
        for i in range(len(mags) - 1):
            assert mags[i] >= mags[i + 1] - 1e-10, (
                f"Row {i}: |S|={mags[i]:.6f} < next |S|={mags[i+1]:.6f}"
            )

    def test_both_signs_present(self):
        rows = read_csv("/app/ignition_sensitivity.csv")
        vals = [float(r["sensitivity_coefficient"]) for r in rows]
        assert any(v > 0 for v in vals), "No positive (inhibiting) sensitivities"
        assert any(v < 0 for v in vals), "No negative (promoting) sensitivities"

    def test_values_finite_and_bounded(self):
        rows = read_csv("/app/ignition_sensitivity.csv")
        for r in rows:
            S = float(r["sensitivity_coefficient"])
            assert math.isfinite(S), f"Non-finite sensitivity: {S}"
            assert abs(S) < 10, f"|S|={abs(S):.4f} exceeds 10"


# ---------------------------------------------------------------------------
# 4. Reduced Mechanism
# ---------------------------------------------------------------------------
class TestReducedMechanism:
    def test_yaml_exists(self):
        assert os.path.exists("/app/reduced_mechanism.yaml")

    def test_loads_in_cantera(self):
        gas = ct.Solution("/app/reduced_mechanism.yaml")
        assert gas.n_species > 0
        assert gas.n_reactions > 0

    def test_fewer_than_25_species(self):
        gas = ct.Solution("/app/reduced_mechanism.yaml")
        assert gas.n_species < 25, f"Reduced has {gas.n_species} species, need <25"

    def test_fewer_species_than_full(self):
        gas_full = ct.Solution("gri30.yaml")
        gas_red = ct.Solution("/app/reduced_mechanism.yaml")
        assert gas_red.n_species < gas_full.n_species, (
            f"Reduced {gas_red.n_species} >= full {gas_full.n_species}"
        )

    def test_fewer_reactions_than_full(self):
        gas_full = ct.Solution("gri30.yaml")
        gas_red = ct.Solution("/app/reduced_mechanism.yaml")
        assert gas_red.n_reactions < gas_full.n_reactions

    def test_essential_species_present(self):
        gas = ct.Solution("/app/reduced_mechanism.yaml")
        for sp in ("CH4", "O2", "H2O", "N2", "OH", "H", "O", "CH3"):
            assert sp in gas.species_names, f"Essential species {sp} missing"

    def test_stats_file_exists(self):
        assert os.path.exists("/app/reduced_stats.json")

    def test_stats_consistent_with_yaml(self):
        stats = load_json("/app/reduced_stats.json")
        gas = ct.Solution("/app/reduced_mechanism.yaml")
        assert gas.n_species == stats["n_species"], (
            f"Stats {stats['n_species']} != YAML {gas.n_species} species"
        )
        assert gas.n_reactions == stats["n_reactions"], (
            f"Stats {stats['n_reactions']} != YAML {gas.n_reactions} reactions"
        )


# ---------------------------------------------------------------------------
# 5. Validation - Ignition
# ---------------------------------------------------------------------------
class TestValidationIgnition:
    def test_file_exists(self):
        assert os.path.exists("/app/validation_ignition.csv")

    def test_all_conditions_present(self):
        rows = read_csv("/app/validation_ignition.csv")
        assert len(rows) == 6
        present = {r["condition"] for r in rows}
        assert present == {"A", "B", "C", "D", "E", "F"}

    def test_errors_below_threshold(self):
        rows = read_csv("/app/validation_ignition.csv")
        for r in rows:
            err = float(r["relative_error_percent"])
            assert err < 30.0, (
                f"Ignition {r['condition']}: error {err:.1f}% >= 30%"
            )

    def test_reduced_delays_positive(self):
        rows = read_csv("/app/validation_ignition.csv")
        for r in rows:
            tau = float(r["reduced_delay_ms"])
            assert tau > 0, f"{r['condition']}: non-positive delay {tau}"

    def test_independent_reduced_ignition_e(self):
        """Cross-check one ignition delay with the reduced mechanism."""
        gas = ct.Solution("/app/reduced_mechanism.yaml")
        gas.set_equivalence_ratio(1.0, "CH4:1", "O2:1, N2:3.76")
        gas.TP = 1400, 10 * ct.one_atm

        reactor = ct.IdealGasConstPressureReactor(gas)
        sim = ct.ReactorNet([reactor])
        times, temps = [], []
        while sim.time < 2.0:
            sim.step()
            times.append(sim.time)
            temps.append(reactor.T)
            if reactor.T > 2500:
                break

        times = np.array(times)
        temps = np.array(temps)
        dTdt = np.diff(temps) / np.diff(times)
        tau_test = times[np.argmax(dTdt)] * 1000  # ms

        assert 0.01 < tau_test < 50, (
            f"Reduced at 1400K/10atm: {tau_test:.4f} ms unreasonable"
        )

        rows = read_csv("/app/validation_ignition.csv")
        cond_e = [row for row in rows if row["condition"] == "E"][0]
        tau_csv = float(cond_e["reduced_delay_ms"])
        rel = abs(tau_test - tau_csv) / tau_csv
        assert rel < 0.05, (
            f"Independent: {tau_test:.4f} vs CSV {tau_csv:.4f} ms ({rel*100:.1f}%)"
        )


# ---------------------------------------------------------------------------
# 6. Validation - Flame Temperatures
# ---------------------------------------------------------------------------
class TestValidationFlame:
    def test_file_exists(self):
        assert os.path.exists("/app/validation_flame.csv")

    def test_all_phis_present(self):
        rows = read_csv("/app/validation_flame.csv")
        assert len(rows) == 5
        present = {float(r["equivalence_ratio"]) for r in rows}
        assert present == {0.5, 0.7, 0.9, 1.0, 1.2}

    def test_errors_below_threshold(self):
        rows = read_csv("/app/validation_flame.csv")
        for r in rows:
            err = float(r["absolute_error_K"])
            assert err < 100.0, (
                f"Flame phi={r['equivalence_ratio']}: "
                f"error {err:.1f} K >= 100 K"
            )

    def test_reduced_temps_positive(self):
        rows = read_csv("/app/validation_flame.csv")
        for r in rows:
            T = float(r["reduced_temp_K"])
            assert T > 500, (
                f"phi={r['equivalence_ratio']}: unreasonable temp {T} K"
            )
