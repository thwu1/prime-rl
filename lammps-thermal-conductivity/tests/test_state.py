
import json
import math
import os
import re
import pytest

RESULTS_PATH = "/app/results.json"


@pytest.fixture
def results():
    with open(RESULTS_PATH) as f:
        return json.load(f)


class TestResultsStructure:
    def test_results_json_exists(self):
        assert os.path.exists(RESULTS_PATH), "results.json not found at /app/results.json"

    def test_top_level_keys(self, results):
        required = ["kappa_method1", "kappa_method2", "kappa_avg_lj", "kappa_si", "argon_params"]
        for key in required:
            assert key in results, f"Missing required key: {key}"

    def test_argon_params_keys(self, results):
        param_keys = ["epsilon_J", "sigma_m", "mass_kg", "tau_s"]
        for key in param_keys:
            assert key in results["argon_params"], f"Missing argon_params key: {key}"

    def test_kappa_values_are_numeric(self, results):
        for key in ["kappa_method1", "kappa_method2", "kappa_avg_lj", "kappa_si"]:
            assert isinstance(results[key], (int, float)), f"{key} must be numeric, got {type(results[key])}"
            assert math.isfinite(results[key]), f"{key} must be finite, got {results[key]}"

    def test_argon_params_are_numeric(self, results):
        for key in ["epsilon_J", "sigma_m", "mass_kg", "tau_s"]:
            val = results["argon_params"][key]
            assert isinstance(val, (int, float)), f"argon_params.{key} must be numeric"
            assert math.isfinite(val), f"argon_params.{key} must be finite"


class TestKappaValues:
    def test_kappa_method1_positive(self, results):
        assert results["kappa_method1"] > 0, "kappa_method1 must be positive"

    def test_kappa_method2_positive(self, results):
        assert results["kappa_method2"] > 0, "kappa_method2 must be positive"

    def test_kappa_method1_physically_reasonable(self, results):
        """For LJ fluid at rho*=0.6, T*=1.35, kappa should be roughly 2-5 in LJ units.
        Allow wide range [0.5, 15.0] to accommodate short-run statistical noise."""
        kappa = results["kappa_method1"]
        assert 0.5 <= kappa <= 15.0, (
            f"kappa_method1 = {kappa:.4f} is outside the physically plausible "
            f"range [0.5, 15.0] for this LJ state point"
        )

    def test_kappa_method2_physically_reasonable(self, results):
        kappa = results["kappa_method2"]
        assert 0.5 <= kappa <= 15.0, (
            f"kappa_method2 = {kappa:.4f} is outside the physically plausible "
            f"range [0.5, 15.0] for this LJ state point"
        )

    def test_kappa_avg_reasonable(self, results):
        """Average of two methods should be closer to the known value of ~3.4."""
        kappa = results["kappa_avg_lj"]
        assert 1.0 <= kappa <= 10.0, (
            f"kappa_avg_lj = {kappa:.4f} is outside the expected range [1.0, 10.0]"
        )

    def test_kappa_avg_is_arithmetic_mean(self, results):
        expected = (results["kappa_method1"] + results["kappa_method2"]) / 2.0
        rel_err = abs(results["kappa_avg_lj"] - expected) / max(expected, 1e-12)
        assert rel_err < 0.02, (
            f"kappa_avg_lj = {results['kappa_avg_lj']:.6f} should be the arithmetic "
            f"mean of method1 ({results['kappa_method1']:.6f}) and "
            f"method2 ({results['kappa_method2']:.6f}), expected {expected:.6f}"
        )


class TestArgonParams:
    def test_epsilon_range(self, results):
        eps = results["argon_params"]["epsilon_J"]
        # epsilon = 119.8 * kB ~ 1.654e-21 J
        assert 1.4e-21 < eps < 1.9e-21, f"epsilon_J = {eps:.4e} not in expected range"

    def test_sigma_range(self, results):
        sigma = results["argon_params"]["sigma_m"]
        # sigma = 3.405e-10 m
        assert 3.0e-10 < sigma < 4.0e-10, f"sigma_m = {sigma:.4e} not in expected range"

    def test_mass_range(self, results):
        mass = results["argon_params"]["mass_kg"]
        # mass = 39.948 * 1.66054e-27 ~ 6.634e-26 kg
        assert 5.5e-26 < mass < 7.5e-26, f"mass_kg = {mass:.4e} not in expected range"

    def test_tau_range(self, results):
        tau = results["argon_params"]["tau_s"]
        # tau = sigma * sqrt(mass/epsilon) ~ 2.16e-12 s
        assert 1.5e-12 < tau < 3.0e-12, f"tau_s = {tau:.4e} not in expected range"

    def test_tau_internal_consistency(self, results):
        """tau must equal sigma * sqrt(mass / epsilon)."""
        p = results["argon_params"]
        tau_expected = p["sigma_m"] * math.sqrt(p["mass_kg"] / p["epsilon_J"])
        rel_err = abs(p["tau_s"] - tau_expected) / tau_expected
        assert rel_err < 0.05, (
            f"tau_s = {p['tau_s']:.6e} is not consistent with "
            f"sigma*sqrt(m/eps) = {tau_expected:.6e} (rel error {rel_err:.4f})"
        )


class TestSIConversion:
    def test_kappa_si_positive(self, results):
        assert results["kappa_si"] > 0, "kappa_si must be positive"

    def test_kappa_si_physically_reasonable(self, results):
        """For kappa_LJ ~3.4, kappa_SI for Argon should be ~0.064 W/(m*K).
        Allow wide range to accommodate different kappa_LJ values."""
        kappa_si = results["kappa_si"]
        assert 0.005 < kappa_si < 0.5, (
            f"kappa_si = {kappa_si:.6f} W/(m*K) is outside reasonable range"
        )

    def test_kappa_si_conversion_consistent(self, results):
        """Verify kappa_si = kappa_avg_lj * kB / (sigma * tau)."""
        p = results["argon_params"]
        kB = 1.380649e-23  # J/K, 2019 exact definition
        conversion = kB / (p["sigma_m"] * p["tau_s"])
        expected_si = results["kappa_avg_lj"] * conversion
        rel_err = abs(results["kappa_si"] - expected_si) / max(expected_si, 1e-15)
        assert rel_err < 0.15, (
            f"kappa_si = {results['kappa_si']:.6e} is not consistent with "
            f"kappa_avg_lj * kB/(sigma*tau) = {expected_si:.6e} "
            f"(rel error {rel_err:.4f})"
        )


class TestSimulationEvidence:
    def test_lammps_log_files_exist(self):
        """Corrected simulations must have been run — verify log files exist."""
        app_files = os.listdir("/app") if os.path.isdir("/app") else []
        has_log = any("log" in f.lower() for f in app_files)
        has_lammps_default = "log.lammps" in app_files
        assert has_log or has_lammps_default, (
            f"No LAMMPS log files found in /app/. Files: {app_files}"
        )

    def test_temperature_profile_files_exist(self):
        """NEMD simulations produce temperature profile files."""
        app_files = os.listdir("/app") if os.path.isdir("/app") else []
        has_profile = any("profile" in f.lower() for f in app_files)
        assert has_profile, (
            f"No temperature profile files found in /app/. Files: {app_files}"
        )

    def test_corrected_scripts_present(self):
        """The agent should have modified or replaced the input scripts."""
        assert os.path.exists("/app/in.heat") or os.path.exists("/app/in.heat_fixed"), (
            "No heat method input script found in /app/"
        )
        assert os.path.exists("/app/in.mp") or os.path.exists("/app/in.mp_fixed"), (
            "No Muller-Plathe input script found in /app/"
        )

    def test_heat_script_energy_rate_consistency(self):
        """The fix-heat kappa formula energy rate must match fix heat injection."""
        heat_script = None
        for fname in ["in.heat", "in.heat_fixed"]:
            path = os.path.join("/app", fname)
            if os.path.exists(path):
                with open(path) as f:
                    heat_script = f.read()
                break
        assert heat_script is not None, "Cannot find heat method script"
        # Extract the energy rate from the fix heat command
        fix_match = re.search(r'fix\s+\w+\s+all\s+heat\s+\d+\s+([\d.]+)', heat_script)
        assert fix_match is not None, "Cannot find fix heat command in heat script"
        fix_rate = float(fix_match.group(1))
        # Extract the energy rate from the kappa formula
        kappa_match = re.search(r'variable\s+kappa\s+equal\s+\(([\d.]+)', heat_script)
        assert kappa_match is not None, "Cannot find kappa variable definition in heat script"
        formula_rate = float(kappa_match.group(1))
        rel_err = abs(fix_rate - formula_rate) / max(fix_rate, 1e-12)
        assert rel_err < 0.01, (
            f"Kappa formula uses energy rate {formula_rate} but fix heat injects "
            f"{fix_rate} — these must be consistent for correct kappa calculation"
        )

    def test_mp_script_tdiff_sign(self):
        """The MP script temperature difference must have correct sign."""
        mp_script = None
        for fname in ["in.mp", "in.mp_fixed"]:
            path = os.path.join("/app", fname)
            if os.path.exists(path):
                with open(path) as f:
                    mp_script = f.read()
                break
        assert mp_script is not None, "Cannot find MP method script"
        tdiff_match = re.search(r'variable\s+tdiff\s+equal\s+(.*)', mp_script)
        assert tdiff_match is not None, "Cannot find tdiff variable in MP script"
        tdiff_expr = tdiff_match.group(1).strip()
        # The correct expression should have chunk 11 first (center, hot)
        # minus chunk 1 (edge, cold) -> f_2[11][3]-f_2[1][3]
        assert "f_2[11]" in tdiff_expr.split("-")[0] or "11" in tdiff_expr.split("-")[0], (
            f"tdiff expression '{tdiff_expr}' appears to have wrong sign: "
            f"center (chunk 11) should come first for positive temperature difference"
        )
