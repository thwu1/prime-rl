
"""
Tests for the multi-scale electrolyte solution thermodynamic analysis engine.
Verifies solution properties, Pitzer activity coefficients, Debye length,
mixing thermodynamics (including excess properties), scan optimality,
concentration profile with critical-point identification, dilution optimization,
multi-solution mixing, and edge cases.
"""

import json
import subprocess
import numpy as np
import pytest


def run_tool(input_data, tmp_dir):
    """Run the analysis engine and return parsed output."""
    input_path = str(tmp_dir / "input.json")
    output_path = str(tmp_dir / "output.json")
    with open(input_path, "w") as f:
        json.dump(input_data, f)
    result = subprocess.run(
        ["python3", "/app/electrolyte_engine.py",
         "--input", input_path, "--output", output_path],
        capture_output=True, text=True, timeout=300,
    )
    assert result.returncode == 0, (
        f"Tool failed (rc={result.returncode}).\n"
        f"stderr: {result.stderr}\nstdout: {result.stdout}"
    )
    with open(output_path) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Input helpers
# ---------------------------------------------------------------------------

def nacl_water_input():
    """0.5 mol/kg NaCl mixed with pure water (equal volumes)."""
    return {
        "solutions": [
            {"name": "nacl_05",
             "solutes": {"Na+": "0.5 mol/kg", "Cl-": "0.5 mol/kg"},
             "pH": 7.0, "temperature": "25 degC", "volume": "1 L"},
            {"name": "pure_water", "solutes": {},
             "pH": 7.0, "temperature": "25 degC", "volume": "1 L"},
        ],
        "scan_steps": 11,
    }


def full_nacl_input():
    """Full input with concentration profile and dilution target."""
    return {
        "solutions": [
            {"name": "nacl_05",
             "solutes": {"Na+": "0.5 mol/kg", "Cl-": "0.5 mol/kg"},
             "pH": 7.0, "temperature": "25 degC", "volume": "1 L"},
            {"name": "pure_water", "solutes": {},
             "pH": 7.0, "temperature": "25 degC", "volume": "1 L"},
        ],
        "scan_steps": 5,
        "concentration_profile": {
            "salt_cation": "Na+", "salt_anion": "Cl-",
            "min_molal": 0.01, "max_molal": 6.0, "steps": 15,
        },
        "target_water_activity": 0.995,
    }


def _find_key(coeffs, element):
    """Find key containing element name in activity_coefficients dict."""
    for k in coeffs:
        if element in k:
            return k
    raise KeyError(f"No {element} key in {list(coeffs.keys())}")


# ---------------------------------------------------------------------------
# Module-scoped fixtures (one run_tool call shared across all tests in module)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def nacl_result(tmp_path_factory):
    return run_tool(nacl_water_input(), tmp_path_factory.mktemp("nacl"))


@pytest.fixture(scope="module")
def full_result(tmp_path_factory):
    return run_tool(full_nacl_input(), tmp_path_factory.mktemp("full"))


@pytest.fixture(scope="module")
def multi_result(tmp_path_factory):
    data = {
        "solutions": [
            {"name": "hard_water", "solutes": {
                "Ca+2": "5 mmol/L", "Mg+2": "3 mmol/L",
                "Na+": "10 mmol/L", "Cl-": "20 mmol/L",
                "SO4-2": "3 mmol/L"},
             "pH": 7.5, "temperature": "25 degC", "volume": "1 L"},
            {"name": "soft_water",
             "solutes": {"Na+": "2 mmol/L", "Cl-": "2 mmol/L"},
             "pH": 7.0, "temperature": "25 degC", "volume": "1 L"},
        ],
        "scan_steps": 5,
    }
    return run_tool(data, tmp_path_factory.mktemp("multi"))


@pytest.fixture(scope="module")
def three_sol_result(tmp_path_factory):
    data = {
        "solutions": [
            {"name": "nacl_soln",
             "solutes": {"Na+": "0.3 mol/kg", "Cl-": "0.3 mol/kg"},
             "pH": 7.0, "temperature": "25 degC", "volume": "0.5 L"},
            {"name": "kcl_soln",
             "solutes": {"K+": "0.2 mol/kg", "Cl-": "0.2 mol/kg"},
             "pH": 7.0, "temperature": "25 degC", "volume": "0.5 L"},
            {"name": "dilute_water", "solutes": {},
             "pH": 7.0, "temperature": "25 degC", "volume": "1 L"},
        ],
        "scan_steps": 5,
    }
    return run_tool(data, tmp_path_factory.mktemp("three"))


@pytest.fixture(scope="module")
def identical_result(tmp_path_factory):
    data = {
        "solutions": [
            {"name": "a",
             "solutes": {"Na+": "0.1 mol/kg", "Cl-": "0.1 mol/kg"},
             "pH": 7.0, "temperature": "25 degC", "volume": "1 L"},
            {"name": "b",
             "solutes": {"Na+": "0.1 mol/kg", "Cl-": "0.1 mol/kg"},
             "pH": 7.0, "temperature": "25 degC", "volume": "1 L"},
        ],
        "scan_steps": 5,
    }
    return run_tool(data, tmp_path_factory.mktemp("identical"))


# ---------------------------------------------------------------------------
# Individual solution property tests
# ---------------------------------------------------------------------------

class TestSolutionProperties:
    def test_nacl_ionic_strength(self, nacl_result):
        assert np.isclose(
            nacl_result["individual"][0]["ionic_strength_mol_kg"], 0.5, rtol=0.05)

    def test_nacl_density_above_water(self, nacl_result):
        assert 1.0 < nacl_result["individual"][0]["density_kg_L"] < 1.05

    def test_nacl_osmotic_pressure_positive(self, nacl_result):
        assert nacl_result["individual"][0]["osmotic_pressure_Pa"] > 0

    def test_nacl_water_activity_below_one(self, nacl_result):
        assert 0.95 < nacl_result["individual"][0]["water_activity"] < 1.0

    def test_pure_water_density(self, nacl_result):
        assert np.isclose(
            nacl_result["individual"][1]["density_kg_L"], 0.997, rtol=0.01)

    def test_pure_water_ph(self, nacl_result):
        assert np.isclose(nacl_result["individual"][1]["pH"], 7.0, atol=0.3)


# ---------------------------------------------------------------------------
# Activity coefficient tests (Pitzer model vs published literature)
# ---------------------------------------------------------------------------

class TestActivityCoefficients:
    def test_nacl_05_molkg(self, nacl_result):
        """gamma_pm(NaCl) at 0.5 mol/kg ~ 0.681 (J. Phys. Chem. Ref. Data)."""
        coeffs = nacl_result["individual"][0]["activity_coefficients"]
        gamma = coeffs[_find_key(coeffs, "Na")]
        assert np.isclose(gamma, 0.681, rtol=0.06)

    def test_nacl_01_molkg(self, tmp_path):
        """gamma_pm(NaCl) at 0.1 mol/kg ~ 0.778."""
        data = {
            "solutions": [
                {"name": "a",
                 "solutes": {"Na+": "0.1 mol/kg", "Cl-": "0.1 mol/kg"},
                 "pH": 7.0, "temperature": "25 degC", "volume": "1 L"},
                {"name": "b", "solutes": {},
                 "pH": 7.0, "temperature": "25 degC", "volume": "1 L"},
            ],
            "scan_steps": 3,
        }
        result = run_tool(data, tmp_path)
        coeffs = result["individual"][0]["activity_coefficients"]
        gamma = coeffs[_find_key(coeffs, "Na")]
        assert np.isclose(gamma, 0.778, rtol=0.06)

    def test_nacl_1_molkg(self, tmp_path):
        """gamma_pm(NaCl) at 1.0 mol/kg ~ 0.657."""
        data = {
            "solutions": [
                {"name": "a",
                 "solutes": {"Na+": "1.0 mol/kg", "Cl-": "1.0 mol/kg"},
                 "pH": 7.0, "temperature": "25 degC", "volume": "1 L"},
                {"name": "b", "solutes": {},
                 "pH": 7.0, "temperature": "25 degC", "volume": "1 L"},
            ],
            "scan_steps": 3,
        }
        result = run_tool(data, tmp_path)
        coeffs = result["individual"][0]["activity_coefficients"]
        gamma = coeffs[_find_key(coeffs, "Na")]
        assert np.isclose(gamma, 0.657, rtol=0.06)

    def test_nacl_5_molkg_pitzer_ushape(self, tmp_path):
        """At 5 mol/kg NaCl, gamma rises above 0.8 (Pitzer U-shape)."""
        data = {
            "solutions": [
                {"name": "conc",
                 "solutes": {"Na+": "5 mol/kg", "Cl-": "5 mol/kg"},
                 "pH": 7.0, "temperature": "25 degC", "volume": "1 L"},
                {"name": "dil",
                 "solutes": {"Na+": "0.01 mol/kg", "Cl-": "0.01 mol/kg"},
                 "pH": 7.0, "temperature": "25 degC", "volume": "1 L"},
            ],
            "scan_steps": 3,
        }
        result = run_tool(data, tmp_path)
        coeffs = result["individual"][0]["activity_coefficients"]
        gamma = coeffs[_find_key(coeffs, "Na")]
        assert gamma > 0.8, f"gamma at 5 mol/kg should be > 0.8, got {gamma}"
        assert np.isclose(gamma, 0.873, rtol=0.06)


# ---------------------------------------------------------------------------
# Debye length tests
# ---------------------------------------------------------------------------

class TestDebyeLength:
    def test_nacl_debye_length_range(self, nacl_result):
        """NaCl at 0.5 mol/kg: Debye length ~ 0.43 nm."""
        dl = nacl_result["individual"][0]["debye_length_nm"]
        assert 0.2 < dl < 0.8

    def test_pure_water_debye_length_much_larger(self, nacl_result):
        dl_nacl = nacl_result["individual"][0]["debye_length_nm"]
        dl_water = nacl_result["individual"][1]["debye_length_nm"]
        assert dl_water > dl_nacl * 10

    def test_blend_debye_length_intermediate(self, nacl_result):
        dl_nacl = nacl_result["individual"][0]["debye_length_nm"]
        dl_water = nacl_result["individual"][1]["debye_length_nm"]
        dl_blend = nacl_result["blend"]["debye_length_nm"]
        assert dl_nacl < dl_blend < dl_water


# ---------------------------------------------------------------------------
# Blend property tests
# ---------------------------------------------------------------------------

class TestBlendProperties:
    def test_blend_ionic_strength_intermediate(self, nacl_result):
        is_nacl = nacl_result["individual"][0]["ionic_strength_mol_kg"]
        is_water = nacl_result["individual"][1]["ionic_strength_mol_kg"]
        is_blend = nacl_result["blend"]["ionic_strength_mol_kg"]
        assert is_water < is_blend < is_nacl

    def test_blend_density_intermediate(self, nacl_result):
        d_nacl = nacl_result["individual"][0]["density_kg_L"]
        d_water = nacl_result["individual"][1]["density_kg_L"]
        d_blend = nacl_result["blend"]["density_kg_L"]
        assert min(d_nacl, d_water) <= d_blend <= max(d_nacl, d_water)


# ---------------------------------------------------------------------------
# Excess properties tests
# ---------------------------------------------------------------------------

class TestExcessProperties:
    def test_excess_gibbs_self_consistent(self, nacl_result):
        """excess_gibbs must exactly equal gibbs_mix - gibbs_mix_ideal."""
        thermo = nacl_result["thermodynamics"]
        expected = thermo["gibbs_mix_J"] - thermo["gibbs_mix_ideal_J"]
        assert np.isclose(thermo["excess_gibbs_J"], expected, rtol=0.001), (
            f"excess_gibbs={thermo['excess_gibbs_J']} != "
            f"dG_real-dG_ideal={expected}"
        )

    def test_excess_gibbs_nonzero_for_electrolyte(self, nacl_result):
        """Real and ideal mixing differ for electrolyte solutions."""
        assert abs(nacl_result["thermodynamics"]["excess_gibbs_J"]) > 1.0

    def test_excess_volume_finite_and_small(self, nacl_result):
        ev = nacl_result["thermodynamics"]["excess_volume_mL"]
        assert np.isfinite(ev), "excess volume must be finite"
        assert abs(ev) < 100, f"excess volume {ev} mL too large for 2L total"

    def test_three_sol_excess_gibbs_consistent(self, three_sol_result):
        """Excess Gibbs consistency also holds for N>2 solutions."""
        thermo = three_sol_result["thermodynamics"]
        expected = thermo["gibbs_mix_J"] - thermo["gibbs_mix_ideal_J"]
        assert np.isclose(thermo["excess_gibbs_J"], expected, rtol=0.01)


# ---------------------------------------------------------------------------
# Mixing thermodynamics tests
# ---------------------------------------------------------------------------

class TestMixingThermodynamics:
    def test_gibbs_mix_negative(self, nacl_result):
        assert nacl_result["thermodynamics"]["gibbs_mix_J"] < 0

    def test_gibbs_ideal_negative(self, nacl_result):
        assert nacl_result["thermodynamics"]["gibbs_mix_ideal_J"] < 0

    def test_entropy_mix_positive(self, nacl_result):
        assert nacl_result["thermodynamics"]["entropy_mix_J_K"] > 0

    def test_entropy_consistent_with_gibbs(self, nacl_result):
        """dS must satisfy dS = -dG_ideal / T."""
        ds = nacl_result["thermodynamics"]["entropy_mix_J_K"]
        dg_ideal = nacl_result["thermodynamics"]["gibbs_mix_ideal_J"]
        expected_ds = -dg_ideal / 298.15
        assert np.isclose(ds, expected_ds, rtol=0.01), (
            f"entropy {ds} != -dG_ideal/T = {expected_ds}"
        )

    def test_nonideality_factor_finite(self, nacl_result):
        eta = nacl_result["thermodynamics"]["nonideality_factor"]
        assert 0.1 < eta < 10.0

    def test_real_differs_from_ideal(self, nacl_result):
        dg_r = nacl_result["thermodynamics"]["gibbs_mix_J"]
        dg_i = nacl_result["thermodynamics"]["gibbs_mix_ideal_J"]
        assert not np.isclose(dg_r, dg_i, rtol=0.001)

    def test_mes_positive(self, nacl_result):
        assert nacl_result["thermodynamics"]["min_energy_separation_kWh_m3"] > 0


# ---------------------------------------------------------------------------
# Scan tests
# ---------------------------------------------------------------------------

class TestScan:
    def test_scan_length(self, nacl_result):
        assert len(nacl_result["scan"]) == 11

    def test_scan_endpoints_zero(self, nacl_result):
        scan = nacl_result["scan"]
        assert np.isclose(scan[0]["gibbs_mix_J"], 0.0, atol=1.0)
        assert np.isclose(scan[-1]["gibbs_mix_J"], 0.0, atol=1.0)

    def test_scan_interior_negative(self, nacl_result):
        for pt in nacl_result["scan"][1:-1]:
            assert pt["gibbs_mix_J"] < 0, (
                f"dG should be < 0 at fraction {pt['fraction_0']}"
            )

    def test_scan_fractions_span_unit_interval(self, nacl_result):
        fracs = [p["fraction_0"] for p in nacl_result["scan"]]
        assert np.isclose(fracs[0], 0.0, atol=1e-6)
        assert np.isclose(fracs[-1], 1.0, atol=1e-6)

    def test_scan_has_exactly_one_optimal(self, nacl_result):
        optimal_count = sum(
            1 for pt in nacl_result["scan"] if pt.get("optimal", False))
        assert optimal_count == 1, (
            f"Expected exactly 1 optimal point, found {optimal_count}"
        )

    def test_scan_optimal_is_global_minimum(self, nacl_result):
        """The optimal-marked point must have the most negative dG."""
        scan = nacl_result["scan"]
        min_gibbs = min(pt["gibbs_mix_J"] for pt in scan)
        optimal = [pt for pt in scan if pt.get("optimal", False)][0]
        assert np.isclose(optimal["gibbs_mix_J"], min_gibbs, rtol=1e-6)

    def test_scan_optimal_is_interior(self, nacl_result):
        optimal = [pt for pt in nacl_result["scan"]
                    if pt.get("optimal", False)][0]
        assert 0 < optimal["fraction_0"] < 1


# ---------------------------------------------------------------------------
# Concentration profile tests
# ---------------------------------------------------------------------------

class TestConcentrationProfile:
    def test_profile_point_count(self, full_result):
        assert len(full_result["concentration_profile"]["points"]) == 15

    def test_profile_molality_range(self, full_result):
        pts = full_result["concentration_profile"]["points"]
        assert np.isclose(pts[0]["molality"], 0.01, rtol=0.02)
        assert np.isclose(pts[-1]["molality"], 6.0, rtol=0.02)

    def test_profile_gamma_minimum_location(self, full_result):
        """NaCl mean gamma minimum is near 1.0 mol/kg (literature)."""
        gm = full_result["concentration_profile"]["gamma_minimum"]
        assert 0.5 < gm["molality"] < 2.5, (
            f"Gamma minimum at {gm['molality']} mol/kg, expected ~1.0"
        )

    def test_profile_gamma_minimum_value(self, full_result):
        """NaCl mean gamma minimum value should be ~0.65."""
        gm = full_result["concentration_profile"]["gamma_minimum"]
        assert 0.5 < gm["value"] < 0.75, (
            f"Gamma minimum value {gm['value']}, expected ~0.65"
        )

    def test_profile_debye_length_decreasing(self, full_result):
        """Debye length decreases with increasing ionic strength."""
        pts = full_result["concentration_profile"]["points"]
        assert pts[0]["debye_length_nm"] > pts[-1]["debye_length_nm"]

    def test_profile_no_unity_crossing_nacl_under_6(self, full_result):
        """NaCl gamma_mean doesn't cross 1.0 below ~6 mol/kg."""
        assert full_result["concentration_profile"][
            "gamma_unity_crossing_molality"] is None

    def test_profile_gamma_values_positive(self, full_result):
        """All gamma_mean values must be positive."""
        for pt in full_result["concentration_profile"]["points"]:
            assert pt["gamma_mean"] > 0, (
                f"gamma_mean <= 0 at {pt['molality']} mol/kg"
            )

    def test_profile_ushape_trend(self, full_result):
        """Gamma should decrease then increase (U-shape)."""
        pts = full_result["concentration_profile"]["points"]
        gammas = [p["gamma_mean"] for p in pts]
        min_idx = int(np.argmin(gammas))
        # Should decrease from start to minimum
        assert gammas[0] > gammas[min_idx]
        # Should increase from minimum to end
        assert gammas[-1] > gammas[min_idx]


# ---------------------------------------------------------------------------
# Dilution optimization tests
# ---------------------------------------------------------------------------

class TestDilution:
    def test_dilution_volume_positive(self, full_result):
        """Diluting 0.25 mol/kg NaCl to a_w=0.995 requires added water."""
        assert full_result["dilution"]["dilution_volume_L"] > 0

    def test_dilution_achieves_target(self, full_result):
        """Achieved water activity must be within tolerance of target."""
        assert np.isclose(
            full_result["dilution"]["achieved_water_activity"],
            0.995, atol=0.002)

    def test_dilution_reduces_ionic_strength(self, full_result):
        """Dilution must reduce ionic strength below blend value."""
        assert (full_result["dilution"]["diluted_ionic_strength_mol_kg"] <
                full_result["blend"]["ionic_strength_mol_kg"])

    def test_dilution_not_needed_for_water(self, tmp_path):
        """Pure water already has a_w ~ 1, no dilution needed."""
        data = {
            "solutions": [
                {"name": "w1", "solutes": {},
                 "pH": 7.0, "temperature": "25 degC", "volume": "1 L"},
                {"name": "w2", "solutes": {},
                 "pH": 7.0, "temperature": "25 degC", "volume": "1 L"},
            ],
            "scan_steps": 3,
            "target_water_activity": 0.999,
        }
        result = run_tool(data, tmp_path)
        assert result["dilution"]["dilution_volume_L"] == 0.0


# ---------------------------------------------------------------------------
# Multi-electrolyte tests
# ---------------------------------------------------------------------------

class TestMultiElectrolyte:
    def test_hard_water_positive_hardness(self, multi_result):
        assert multi_result["individual"][0]["hardness_mg_L"] > 0

    def test_soft_water_zero_hardness(self, multi_result):
        assert multi_result["individual"][1]["hardness_mg_L"] == 0

    def test_multi_ion_activity_coeffs(self, multi_result):
        coeffs = multi_result["individual"][0]["activity_coefficients"]
        assert len(coeffs) >= 4
        for key, val in coeffs.items():
            assert 0 < val <= 1.0, f"gamma({key}) = {val}"

    def test_conductivity_positive(self, multi_result):
        for sol in multi_result["individual"]:
            assert sol["conductivity_S_m"] > 0


# ---------------------------------------------------------------------------
# Three-solution mixing tests
# ---------------------------------------------------------------------------

class TestThreeSolutionMixing:
    def test_three_sol_individual_count(self, three_sol_result):
        assert len(three_sol_result["individual"]) == 3

    def test_three_sol_blend_has_both_cations(self, three_sol_result):
        coeffs = three_sol_result["blend"]["activity_coefficients"]
        keys_str = " ".join(coeffs.keys())
        assert "Na" in keys_str, (
            f"No Na in blend coefficients: {list(coeffs.keys())}")
        assert "K" in keys_str, (
            f"No K in blend coefficients: {list(coeffs.keys())}")

    def test_three_sol_gibbs_negative(self, three_sol_result):
        assert three_sol_result["thermodynamics"]["gibbs_mix_J"] < 0

    def test_three_sol_entropy_positive(self, three_sol_result):
        assert three_sol_result["thermodynamics"]["entropy_mix_J_K"] > 0

    def test_three_sol_scan_length(self, three_sol_result):
        assert len(three_sol_result["scan"]) == 5

    def test_three_sol_blend_debye_positive(self, three_sol_result):
        dl = three_sol_result["blend"]["debye_length_nm"]
        assert dl > 0 and np.isfinite(dl)


# ---------------------------------------------------------------------------
# Identical-solution mixing edge case
# ---------------------------------------------------------------------------

class TestIdenticalMixing:
    def test_identical_gibbs_near_zero(self, identical_result):
        dg = identical_result["thermodynamics"]["gibbs_mix_J"]
        assert abs(dg) < 50.0, (
            f"dG for identical solutions should be ~0, got {dg}")

    def test_identical_entropy_near_zero(self, identical_result):
        ds = identical_result["thermodynamics"]["entropy_mix_J_K"]
        assert abs(ds) < 0.2, (
            f"dS for identical solutions should be ~0, got {ds}")

    def test_identical_scan_all_near_zero(self, identical_result):
        for pt in identical_result["scan"]:
            assert abs(pt["gibbs_mix_J"]) < 50.0, (
                f"dG should be ~0 at fraction {pt['fraction_0']}, "
                f"got {pt['gibbs_mix_J']}"
            )
