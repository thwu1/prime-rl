"""
Tests for H2/Air Multi-Reactor Kinetics Analysis.
Verifies structure, physical consistency, and domain-specific properties
of the computed results against the run configuration.
"""


import json
import os
import pytest
import numpy as np


@pytest.fixture(scope="module")
def results():
    results_path = "/app/results.json"
    assert os.path.exists(results_path), "results.json not found at /app/results.json"
    with open(results_path) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def config():
    config_path = "/app/config.json"
    assert os.path.exists(config_path), "config.json not found at /app/config.json"
    with open(config_path) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Mechanism discovery tests
# ---------------------------------------------------------------------------
class TestMechanismDiscovery:
    """Verify the solver discovered and reported mechanism structure."""

    def test_n_species_present(self, results):
        assert "mechanism_n_species" in results
        n = results["mechanism_n_species"]
        assert isinstance(n, int) and 5 < n < 100

    def test_n_reactions_present(self, results):
        assert "mechanism_n_reactions" in results
        n = results["mechanism_n_reactions"]
        assert isinstance(n, int) and 10 < n < 500

    def test_sensitivity_count_matches_reactions(self, results):
        """CV sensitivity list length must equal the mechanism reaction count."""
        assert len(results["cv_sensitivity"]) == results["mechanism_n_reactions"]

    def test_psr_sensitivity_count_matches_reactions(self, results):
        """PSR sensitivity list length must equal the mechanism reaction count."""
        assert len(results["psr_sensitivity"]) == results["mechanism_n_reactions"]


# ---------------------------------------------------------------------------
# Structural tests
# ---------------------------------------------------------------------------
class TestJsonStructure:
    """Verify the output JSON has the required keys, types, and consistency
    with the config file."""

    def test_ignition_delays_match_config(self, results, config):
        assert "ignition_delays" in results
        expected = {str(t) for t in config["temperatures_K"]}
        assert set(results["ignition_delays"].keys()) == expected

    def test_peak_temperatures_match_config(self, results, config):
        assert "cv_peak_temperatures" in results
        expected = {str(t) for t in config["temperatures_K"]}
        assert set(results["cv_peak_temperatures"].keys()) == expected

    def test_cv_sensitivity_structure(self, results):
        assert "cv_sensitivity" in results
        assert len(results["cv_sensitivity"]) >= 10
        entry = results["cv_sensitivity"][0]
        assert "index" in entry
        assert "equation" in entry
        assert "sensitivity" in entry

    def test_tau_ext_exists(self, results):
        assert "tau_ext" in results
        assert isinstance(results["tau_ext"], (int, float))

    def test_s_curve_structure(self, results):
        assert "s_curve" in results
        assert len(results["s_curve"]) >= 100
        for point in results["s_curve"]:
            assert len(point) == 2

    def test_psr_sensitivity_structure(self, results):
        assert "psr_sensitivity" in results
        assert len(results["psr_sensitivity"]) >= 10
        for entry in results["psr_sensitivity"]:
            assert "index" in entry
            assert "equation" in entry
            assert "sensitivity" in entry

    def test_spearman_rho_exists(self, results):
        assert "spearman_rho" in results
        assert isinstance(results["spearman_rho"], (int, float))

    def test_top5_lists(self, results):
        assert "top5_cv" in results
        assert "top5_psr" in results
        assert len(results["top5_cv"]) == 5
        assert len(results["top5_psr"]) == 5
        assert all(isinstance(eq, str) for eq in results["top5_cv"])
        assert all(isinstance(eq, str) for eq in results["top5_psr"])


# ---------------------------------------------------------------------------
# Ignition delay tests
# ---------------------------------------------------------------------------
class TestIgnitionDelays:
    """Verify ignition delay time computations are physically consistent."""

    def test_positive_values(self, results):
        for T, tau in results["ignition_delays"].items():
            assert tau > 0, f"Ignition delay at T={T}K must be positive"

    def test_reasonable_range(self, results):
        """H2/air ignition delays at 950-1400 K should be between 1e-9 and 10 s."""
        for T, tau in results["ignition_delays"].items():
            assert 1e-9 < tau < 10.0, (
                f"Ignition delay {tau:.3e}s at T={T}K outside physical range"
            )

    def test_monotonically_decreasing_with_temperature(self, results):
        """Higher initial temperature must give shorter ignition delay."""
        temps = sorted(results["ignition_delays"].keys(), key=int)
        taus = [results["ignition_delays"][t] for t in temps]
        for i in range(len(taus) - 1):
            assert taus[i] > taus[i + 1], (
                f"tau({temps[i]}K)={taus[i]:.3e}s should exceed "
                f"tau({temps[i+1]}K)={taus[i+1]:.3e}s"
            )

    def test_arrhenius_linearity(self, results):
        """ln(tau) vs 1/T should be approximately linear (positive slope)
        above the H2 second-explosion-limit crossover. Temperatures at or
        below 950 K exhibit strongly non-Arrhenius behaviour and are excluded."""
        temps = sorted(results["ignition_delays"].keys(), key=int)
        temps = [t for t in temps if int(t) >= 1000]
        inv_T = np.array([1000.0 / int(t) for t in temps])
        ln_tau = np.array([np.log(results["ignition_delays"][t]) for t in temps])
        p = np.polyfit(inv_T, ln_tau, 1)
        y_pred = np.polyval(p, inv_T)
        ss_res = np.sum((ln_tau - y_pred) ** 2)
        ss_tot = np.sum((ln_tau - ln_tau.mean()) ** 2)
        r2 = 1.0 - ss_res / ss_tot
        assert r2 > 0.90, f"Arrhenius fit R²={r2:.4f} too low (T>=1000K)"
        assert p[0] > 0, f"Slope={p[0]:.2f} should be positive (positive Ea)"

    def test_order_of_magnitude_reference_T(self, results, config):
        """At the reference temperature and 1 atm the H2/air ignition delay
        should be in a reasonable range."""
        T_ref = str(config["sensitivity_reference_T_K"])
        tau = results["ignition_delays"][T_ref]
        assert 1e-6 < tau < 1e-1, f"tau({T_ref}K)={tau:.3e}s outside expected range"

    def test_lowest_temp_crossover_behaviour(self, results, config):
        """The lowest config temperature is near the H2 second explosion limit
        crossover; its ignition delay should be substantially longer than at
        the next higher temperature."""
        temps = sorted(config["temperatures_K"])
        t_low = str(temps[0])
        t_next = str(temps[1])
        tau_low = results["ignition_delays"][t_low]
        tau_next = results["ignition_delays"][t_next]
        assert tau_low > 5 * tau_next, (
            f"tau({t_low}K)={tau_low:.3e}s should be much larger than "
            f"tau({t_next}K)={tau_next:.3e}s near the crossover"
        )


# ---------------------------------------------------------------------------
# Crossover detection tests
# ---------------------------------------------------------------------------
class TestCrossoverDetection:
    """Verify the solver correctly identified the non-Arrhenius crossover."""

    def test_crossover_exists(self, results):
        assert "crossover_temperature" in results
        assert isinstance(results["crossover_temperature"], int)

    def test_crossover_in_config_temps(self, results, config):
        """Crossover temperature must be one of the configured temperatures."""
        assert results["crossover_temperature"] in config["temperatures_K"]

    def test_crossover_below_reference(self, results, config):
        """Crossover must be below the sensitivity reference temperature."""
        assert results["crossover_temperature"] < config["sensitivity_reference_T_K"]

    def test_crossover_shows_anomaly(self, results):
        """At the crossover temperature, ignition delay must be significantly
        longer than at the next higher config temperature."""
        ct_val = results["crossover_temperature"]
        ct_str = str(ct_val)
        temps = sorted(results["ignition_delays"].keys(), key=int)
        idx = temps.index(ct_str)
        assert idx < len(temps) - 1, "Crossover cannot be the highest temperature"
        tau_cross = results["ignition_delays"][ct_str]
        tau_next = results["ignition_delays"][temps[idx + 1]]
        assert tau_cross > 3 * tau_next, (
            f"Ignition delay at crossover {ct_val}K ({tau_cross:.3e}s) "
            f"should be >3x that at {temps[idx + 1]}K ({tau_next:.3e}s)"
        )


# ---------------------------------------------------------------------------
# Peak temperature tests
# ---------------------------------------------------------------------------
class TestPeakTemperatures:
    """Verify constant-volume explosion peak temperatures."""

    def test_reasonable_range(self, results):
        for T, Tp in results["cv_peak_temperatures"].items():
            assert 2000 < Tp < 5000, f"T_peak={Tp:.0f}K at T0={T}K unreasonable"

    def test_generally_increase_with_initial_T(self, results):
        """Peak temperature should roughly increase with T0."""
        temps = sorted(results["cv_peak_temperatures"].keys(), key=int)
        T_peaks = [results["cv_peak_temperatures"][t] for t in temps]
        assert T_peaks[-1] > T_peaks[0], (
            f"T_peak at highest T0={T_peaks[-1]:.0f} should exceed "
            f"T_peak at lowest T0={T_peaks[0]:.0f}"
        )


# ---------------------------------------------------------------------------
# CV sensitivity tests
# ---------------------------------------------------------------------------
class TestCVSensitivity:
    """Verify constant-volume ignition delay sensitivity analysis."""

    def test_sorted_descending_absolute(self, results):
        sens = results["cv_sensitivity"]
        for i in range(len(sens) - 1):
            assert abs(sens[i]["sensitivity"]) >= abs(sens[i + 1]["sensitivity"]) - 1e-10

    def test_chain_branching_in_top5(self, results):
        """The H + O2 chain-branching reaction must appear among the top 5."""
        top5 = [r["equation"] for r in results["cv_sensitivity"][:5]]
        found = any("H + O2" in eq or "O2 + H" in eq for eq in top5)
        assert found, f"H+O2 reaction not in CV top 5: {top5}"

    def test_chain_branching_negative_sensitivity(self, results):
        """Increasing chain-branching rate should decrease ignition delay."""
        for r in results["cv_sensitivity"]:
            eq = r["equation"]
            if ("H + O2" in eq or "O2 + H" in eq) and "HO2" not in eq and "H2O" not in eq:
                assert r["sensitivity"] < 0, (
                    f"Chain-branching '{eq}' should have negative sensitivity, "
                    f"got {r['sensitivity']:.4f}"
                )
                break

    def test_nonzero_sensitivities_exist(self, results):
        """At least 3 reactions should have |sensitivity| > 0.01."""
        count = sum(
            1 for r in results["cv_sensitivity"] if abs(r["sensitivity"]) > 0.01
        )
        assert count >= 3, f"Only {count} reactions with |sens|>0.01"


# ---------------------------------------------------------------------------
# PSR extinction tests
# ---------------------------------------------------------------------------
class TestPSRExtinction:
    """Verify perfectly stirred reactor extinction analysis."""

    def test_tau_ext_positive(self, results):
        assert results["tau_ext"] > 0

    def test_tau_ext_physical_range(self, results):
        """For H2/air at 1 atm, tau_ext should be roughly 1e-7 to 1e-1 s."""
        tau = results["tau_ext"]
        assert 1e-8 < tau < 1.0, f"tau_ext={tau:.3e}s outside expected range"

    def test_s_curve_has_enough_points(self, results):
        assert len(results["s_curve"]) >= 100

    def test_s_curve_hot_branch_temperature(self, results):
        """The hottest S-curve point should approach the adiabatic flame T."""
        s_curve = np.array(results["s_curve"])
        T_max = np.max(s_curve[:, 1])
        assert T_max > 2000, f"S-curve max T={T_max:.0f}K too low"

    def test_s_curve_sorted_descending_tau(self, results):
        s_curve = np.array(results["s_curve"])
        taus = s_curve[:, 0]
        for i in range(len(taus) - 1):
            assert taus[i] >= taus[i + 1] - 1e-15, (
                f"S-curve not sorted at index {i}: tau={taus[i]:.3e} < {taus[i+1]:.3e}"
            )

    def test_s_curve_extinction_visible(self, results):
        """S-curve must show a temperature drop > 1000 K (extinction jump)."""
        s_curve = np.array(results["s_curve"])
        T_vals = s_curve[:, 1]
        assert np.max(T_vals) - np.min(T_vals) > 1000, (
            f"Temperature range {np.max(T_vals):.0f}-{np.min(T_vals):.0f}K "
            f"too narrow to show extinction"
        )

    def test_s_curve_hot_branch_before_cold(self, results):
        """First points (large tau) should be hot, last points (small tau) cold."""
        s_curve = np.array(results["s_curve"])
        assert s_curve[0, 1] > 1500, (
            f"First S-curve point T={s_curve[0, 1]:.0f}K should be hot"
        )
        assert s_curve[-1, 1] < 800, (
            f"Last S-curve point T={s_curve[-1, 1]:.0f}K should be near-inlet T"
        )


# ---------------------------------------------------------------------------
# PSR sensitivity tests
# ---------------------------------------------------------------------------
class TestPSRSensitivity:
    """Verify PSR exit-temperature sensitivity analysis on the burning branch."""

    def test_sorted_descending_absolute(self, results):
        sens = results["psr_sensitivity"]
        for i in range(len(sens) - 1):
            assert abs(sens[i]["sensitivity"]) >= abs(sens[i + 1]["sensitivity"]) - 1e-10

    def test_baseline_on_hot_branch(self, results):
        """PSR sensitivity must be computed on the burning (hot) branch.
        The top sensitivity magnitude should be non-trivial."""
        top_sens = abs(results["psr_sensitivity"][0]["sensitivity"])
        assert top_sens > 0.001, (
            f"Top PSR sensitivity magnitude {top_sens:.6f} is too small — "
            f"suggests the reactor was evaluated on the cold (extinguished) branch"
        )

    def test_h_o2_reaction_important(self, results):
        """At least one H+O2 reaction should be in the PSR top 5."""
        top5 = [r["equation"] for r in results["psr_sensitivity"][:5]]
        found = any("H + O2" in eq or "O2 + H" in eq for eq in top5)
        assert found, f"No H+O2 reaction in PSR top 5: {top5}"

    def test_has_nonzero_sensitivities(self, results):
        """At least 2 reactions should have measurable PSR sensitivity."""
        count = sum(
            1 for r in results["psr_sensitivity"] if abs(r["sensitivity"]) > 1e-5
        )
        assert count >= 2, f"Only {count} reactions with |sens|>1e-5 in PSR"


# ---------------------------------------------------------------------------
# Cross-analysis tests
# ---------------------------------------------------------------------------
class TestCrossAnalysis:
    """Verify cross-reactor sensitivity comparison."""

    def test_spearman_valid_range(self, results):
        rho = results["spearman_rho"]
        assert -1.0 <= rho <= 1.0, f"Spearman rho={rho} outside [-1, 1]"

    def test_top5_cv_contain_h_o2(self, results):
        found = any("H + O2" in eq or "O2 + H" in eq for eq in results["top5_cv"])
        assert found, f"H+O2 not in CV top 5: {results['top5_cv']}"

    def test_top5_psr_contain_h_o2(self, results):
        found = any("H + O2" in eq or "O2 + H" in eq for eq in results["top5_psr"])
        assert found, f"H+O2 not in PSR top 5: {results['top5_psr']}"

    def test_top5_overlap(self, results):
        """At least one reaction should appear in both top-5 lists."""
        cv_set = set(results["top5_cv"])
        psr_set = set(results["top5_psr"])
        overlap = cv_set & psr_set
        assert len(overlap) >= 1, (
            f"No overlap between CV top5={results['top5_cv']} "
            f"and PSR top5={results['top5_psr']}"
        )
