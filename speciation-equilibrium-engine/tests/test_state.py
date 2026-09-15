"""
Tests for the aqueous geochemical speciation engine.
Validates equilibrium speciation results and mineral saturation indices
against hand-computed reference values from MINTEQ/PHREEQC thermodynamic data.
"""

import json
import os
import math
import pytest

RESULTS_PATH = "/app/results.json"


@pytest.fixture
def results():
    assert os.path.exists(RESULTS_PATH), f"Results file not found at {RESULTS_PATH}"
    with open(RESULTS_PATH) as f:
        data = json.load(f)
    assert "scenarios" in data, "Results must contain 'scenarios' key"
    return data["scenarios"]


def get_scenario(results, name):
    for s in results:
        if s["name"] == name:
            return s
    pytest.fail(f"Scenario '{name}' not found in results")


def approx_equal(actual, expected, rel_tol=0.15):
    if expected == 0:
        return abs(actual) < 1e-20
    return abs(actual - expected) / abs(expected) < rel_tol


# ============================================================
# Structural tests
# ============================================================
class TestStructure:
    def test_results_exist(self, results):
        assert len(results) == 5, f"Expected 5 scenarios, got {len(results)}"

    def test_scenario_names(self, results):
        names = {s["name"] for s in results}
        expected = {
            "limestone_equilibrium", "lead_contamination", "iron_fluoride",
            "copper_carbonate", "mixed_carbonate",
        }
        assert names == expected, f"Scenario names mismatch: {names}"

    def test_required_keys(self, results):
        for s in results:
            assert "free_concentrations" in s, f"Missing free_concentrations in {s['name']}"
            assert "species_concentrations" in s, f"Missing species_concentrations in {s['name']}"
            assert "saturation_indices" in s, f"Missing saturation_indices in {s['name']}"

    def test_h_plus_present(self, results):
        for s in results:
            assert "H+" in s["free_concentrations"], f"H+ missing from free_concentrations in {s['name']}"


# ============================================================
# Scenario 1: limestone_equilibrium (Ca-CO3, pH 8.3)
# Hand-computed: [Ca+2]~9.57e-4, [CO3-2]~1.79e-5, [HCO3-]~1.92e-3
# Calcite SI~0.68, Aragonite SI~0.57
# ============================================================
class TestLimestoneEquilibrium:
    def test_free_calcium(self, results):
        s = get_scenario(results, "limestone_equilibrium")
        ca = s["free_concentrations"]["Ca+2"]
        assert 8.5e-4 < ca < 1.0e-3, f"Free Ca+2 = {ca:.4e}, expected ~9.57e-4"

    def test_free_carbonate(self, results):
        s = get_scenario(results, "limestone_equilibrium")
        co3 = s["free_concentrations"]["CO3-2"]
        assert 1.4e-5 < co3 < 2.2e-5, f"Free CO3-2 = {co3:.4e}, expected ~1.79e-5"

    def test_h_plus_value(self, results):
        s = get_scenario(results, "limestone_equilibrium")
        h = s["free_concentrations"]["H+"]
        expected = 10**(-8.3)
        assert approx_equal(h, expected, rel_tol=0.01), f"H+ = {h:.4e}, expected {expected:.4e}"

    def test_bicarbonate_dominant(self, results):
        s = get_scenario(results, "limestone_equilibrium")
        sp = s["species_concentrations"]
        hco3 = sp.get("HCO3-", 0)
        h2co3 = sp.get("H2CO3", 0)
        co3 = s["free_concentrations"]["CO3-2"]
        assert hco3 > h2co3, "HCO3- should exceed H2CO3 at pH 8.3"
        assert hco3 > co3, "HCO3- should exceed free CO3-2 at pH 8.3"

    def test_bicarbonate_value(self, results):
        s = get_scenario(results, "limestone_equilibrium")
        hco3 = s["species_concentrations"].get("HCO3-", 0)
        assert 1.7e-3 < hco3 < 2.1e-3, f"[HCO3-] = {hco3:.4e}, expected ~1.92e-3"

    def test_calcite_supersaturated(self, results):
        s = get_scenario(results, "limestone_equilibrium")
        si = s["saturation_indices"]["Calcite"]
        assert 0.4 < si < 1.0, f"Calcite SI = {si:.3f}, expected ~0.68"

    def test_aragonite_supersaturated(self, results):
        s = get_scenario(results, "limestone_equilibrium")
        si = s["saturation_indices"]["Aragonite"]
        assert 0.3 < si < 0.9, f"Aragonite SI = {si:.3f}, expected ~0.57"

    def test_calcite_gt_aragonite_si(self, results):
        s = get_scenario(results, "limestone_equilibrium")
        si_c = s["saturation_indices"]["Calcite"]
        si_a = s["saturation_indices"]["Aragonite"]
        assert si_c > si_a, "Calcite SI should exceed Aragonite SI (calcite less soluble)"

    def test_calcium_mass_balance(self, results):
        s = get_scenario(results, "limestone_equilibrium")
        ca_free = s["free_concentrations"]["Ca+2"]
        sp = s["species_concentrations"]
        total = ca_free + sp.get("CaCO3", 0) + sp.get("CaHCO3+", 0) + sp.get("CaOH+", 0)
        assert approx_equal(total, 1e-3, rel_tol=0.05), f"Ca mass balance: {total:.4e} vs 1e-3"

    def test_carbonate_mass_balance(self, results):
        s = get_scenario(results, "limestone_equilibrium")
        co3_free = s["free_concentrations"]["CO3-2"]
        sp = s["species_concentrations"]
        total = (co3_free + sp.get("HCO3-", 0) + sp.get("H2CO3", 0)
                 + sp.get("CaCO3", 0) + sp.get("CaHCO3+", 0))
        assert approx_equal(total, 2e-3, rel_tol=0.05), f"CO3 mass balance: {total:.4e} vs 2e-3"


# ============================================================
# Scenario 2: lead_contamination (Pb-SO4-Cl, pH 4.0)
# Hand-computed: [Pb+2]~1.1e-6, PbSO4(aq) dominant Pb species
# Anglesite SI~-0.17
# ============================================================
class TestLeadContamination:
    def test_free_lead(self, results):
        s = get_scenario(results, "lead_contamination")
        pb = s["free_concentrations"]["Pb+2"]
        assert 4e-7 < pb < 3e-6, f"Free Pb+2 = {pb:.4e}, expected ~1.1e-6"

    def test_lead_sulfate_dominant(self, results):
        s = get_scenario(results, "lead_contamination")
        sp = s["species_concentrations"]
        pbso4 = sp.get("PbSO4", 0)
        pb_free = s["free_concentrations"]["Pb+2"]
        assert pbso4 > pb_free, "PbSO4(aq) should exceed free Pb+2"

    def test_lead_chloride_present(self, results):
        s = get_scenario(results, "lead_contamination")
        sp = s["species_concentrations"]
        pbcl = sp.get("PbCl+", 0)
        assert pbcl > 1e-8, f"PbCl+ = {pbcl:.4e}, should be significant"

    def test_anglesite_si(self, results):
        s = get_scenario(results, "lead_contamination")
        si = s["saturation_indices"]["Anglesite"]
        assert -0.6 < si < 0.2, f"Anglesite SI = {si:.3f}, expected ~-0.17"

    def test_cotunnite_undersaturated(self, results):
        s = get_scenario(results, "lead_contamination")
        si = s["saturation_indices"]["Cotunnite"]
        assert si < -1.5, f"Cotunnite SI = {si:.3f}, expected well below 0"

    def test_lead_mass_balance(self, results):
        s = get_scenario(results, "lead_contamination")
        pb_free = s["free_concentrations"]["Pb+2"]
        sp = s["species_concentrations"]
        total = pb_free
        for name in ["PbCl+", "PbCl2", "PbCl3-", "PbSO4", "Pb(SO4)2-2",
                      "PbOH+", "Pb(OH)2", "Pb(OH)3-"]:
            total += sp.get(name, 0)
        assert approx_equal(total, 1e-5, rel_tol=0.05), f"Pb mass balance: {total:.4e} vs 1e-5"

    def test_sulfate_mass_balance(self, results):
        s = get_scenario(results, "lead_contamination")
        so4_free = s["free_concentrations"]["SO4-2"]
        sp = s["species_concentrations"]
        total = so4_free + sp.get("HSO4-", 0) + sp.get("PbSO4", 0) + 2 * sp.get("Pb(SO4)2-2", 0)
        assert approx_equal(total, 0.01, rel_tol=0.05), f"SO4 mass balance: {total:.4e} vs 0.01"


# ============================================================
# Scenario 3: iron_fluoride (Fe(III)-F-SO4, pH 3.0)
# Strong Fe-F complexation depletes free Fe+3
# Ferrihydrite undersaturated due to F complexation
# ============================================================
class TestIronFluoride:
    def test_free_iron_depleted(self, results):
        s = get_scenario(results, "iron_fluoride")
        fe = s["free_concentrations"]["Fe+3"]
        assert fe < 1e-4, f"Free Fe+3 = {fe:.4e}, should be << 1e-3 due to F complexation"

    def test_fluoride_complexes_dominate(self, results):
        s = get_scenario(results, "iron_fluoride")
        sp = s["species_concentrations"]
        fe_free = s["free_concentrations"]["Fe+3"]
        fef_sum = sp.get("FeF+2", 0) + sp.get("FeF2+", 0) + sp.get("FeF3", 0)
        assert fef_sum > fe_free, "Sum of Fe-F complexes should exceed free Fe+3"

    def test_fef2_significant(self, results):
        s = get_scenario(results, "iron_fluoride")
        sp = s["species_concentrations"]
        fef = sp.get("FeF+2", 0)
        assert fef > 1e-5, f"[FeF+2] = {fef:.4e}, expected significant"

    def test_ferrihydrite_undersaturated(self, results):
        s = get_scenario(results, "iron_fluoride")
        si = s["saturation_indices"]["Ferrihydrite"]
        assert si < 0, f"Ferrihydrite SI = {si:.3f}, expected < 0 at pH 3"

    def test_iron_mass_balance(self, results):
        s = get_scenario(results, "iron_fluoride")
        fe_free = s["free_concentrations"]["Fe+3"]
        sp = s["species_concentrations"]
        total = fe_free
        for name in ["FeOH+2", "Fe(OH)2+", "Fe(OH)3", "Fe(OH)4-",
                      "FeF+2", "FeF2+", "FeF3", "FeSO4+", "Fe(SO4)2-"]:
            total += sp.get(name, 0)
        total += 2 * sp.get("Fe2(OH)2+4", 0) + 3 * sp.get("Fe3(OH)4+5", 0)
        assert approx_equal(total, 1e-3, rel_tol=0.10), f"Fe mass balance: {total:.4e} vs 1e-3"

    def test_fluoride_mass_balance(self, results):
        s = get_scenario(results, "iron_fluoride")
        f_free = s["free_concentrations"]["F-"]
        sp = s["species_concentrations"]
        total = f_free + sp.get("HF", 0) + 2 * sp.get("HF2-", 0)
        total += sp.get("FeF+2", 0) + 2 * sp.get("FeF2+", 0) + 3 * sp.get("FeF3", 0)
        assert approx_equal(total, 2e-3, rel_tol=0.10), f"F mass balance: {total:.4e} vs 2e-3"


# ============================================================
# Scenario 4: copper_carbonate (Cu-CO3-Cl, pH 6.5)
# CuCO3(aq) significant; Cu(OH)2 mineral undersaturated
# Azurite may be supersaturated
# ============================================================
class TestCopperCarbonate:
    def test_cuco3_significant(self, results):
        s = get_scenario(results, "copper_carbonate")
        sp = s["species_concentrations"]
        cuco3 = sp.get("CuCO3", 0)
        cu_free = s["free_concentrations"]["Cu+2"]
        assert cuco3 > 0.05 * cu_free, "CuCO3 should be significant at pH 6.5"

    def test_cu_hydroxide_mineral(self, results):
        s = get_scenario(results, "copper_carbonate")
        si = s["saturation_indices"]["Cu_hydroxide"]
        assert si < 0.5, f"Cu(OH)2 mineral SI = {si:.3f}"

    def test_azurite_present(self, results):
        s = get_scenario(results, "copper_carbonate")
        assert "Azurite" in s["saturation_indices"], "Azurite SI should be computed"

    def test_azurite_supersaturated(self, results):
        s = get_scenario(results, "copper_carbonate")
        si = s["saturation_indices"]["Azurite"]
        assert si > 0.5, f"Azurite SI = {si:.3f}, expected >> 0 at pH 6.5 with Cu+CO3"

    def test_bicarbonate_and_h2co3_present(self, results):
        s = get_scenario(results, "copper_carbonate")
        sp = s["species_concentrations"]
        hco3 = sp.get("HCO3-", 0)
        h2co3 = sp.get("H2CO3", 0)
        assert hco3 > 0 and h2co3 > 0, "Both HCO3- and H2CO3 should be present at pH 6.5"

    def test_copper_mass_balance(self, results):
        s = get_scenario(results, "copper_carbonate")
        cu_free = s["free_concentrations"]["Cu+2"]
        sp = s["species_concentrations"]
        total = cu_free
        for name in ["CuOH+", "Cu(OH)2", "Cu(OH)3-", "Cu(OH)4-2",
                      "CuCO3", "Cu(CO3)2-2", "CuCl+", "CuCl2"]:
            total += sp.get(name, 0)
        total += 2 * sp.get("Cu2(OH)2+2", 0)
        assert approx_equal(total, 5e-5, rel_tol=0.10), f"Cu mass balance: {total:.4e} vs 5e-5"

    def test_carbonate_mass_balance(self, results):
        s = get_scenario(results, "copper_carbonate")
        co3_free = s["free_concentrations"]["CO3-2"]
        sp = s["species_concentrations"]
        total = (co3_free + sp.get("HCO3-", 0) + sp.get("H2CO3", 0)
                 + sp.get("CuCO3", 0) + 2 * sp.get("Cu(CO3)2-2", 0))
        assert approx_equal(total, 1e-3, rel_tol=0.05), f"CO3 mass balance: {total:.4e} vs 1e-3"


# ============================================================
# Scenario 5: mixed_carbonate (Ca-Mg-CO3-SO4, pH 7.5)
# Hand-computed: [Ca+2]~1.11e-3, Calcite SI~0.10, Dolomite SI~0.12
# Gypsum SI~-0.83, Magnesite SI~-0.59
# ============================================================
class TestMixedCarbonate:
    def test_free_calcium(self, results):
        s = get_scenario(results, "mixed_carbonate")
        ca = s["free_concentrations"]["Ca+2"]
        assert 8e-4 < ca < 1.5e-3, f"Free Ca+2 = {ca:.4e}, expected ~1.11e-3"

    def test_free_magnesium(self, results):
        s = get_scenario(results, "mixed_carbonate")
        mg = s["free_concentrations"]["Mg+2"]
        assert 3e-4 < mg < 8e-4, f"Free Mg+2 = {mg:.4e}, expected ~5.87e-4"

    def test_calcite_si(self, results):
        s = get_scenario(results, "mixed_carbonate")
        si = s["saturation_indices"]["Calcite"]
        assert -0.2 < si < 0.4, f"Calcite SI = {si:.3f}, expected ~0.10"

    def test_dolomite_si(self, results):
        s = get_scenario(results, "mixed_carbonate")
        si = s["saturation_indices"]["Dolomite"]
        assert -0.3 < si < 0.5, f"Dolomite SI = {si:.3f}, expected ~0.12"

    def test_gypsum_undersaturated(self, results):
        s = get_scenario(results, "mixed_carbonate")
        si = s["saturation_indices"]["Gypsum"]
        assert si < -0.3, f"Gypsum SI = {si:.3f}, expected < -0.3"

    def test_magnesite_undersaturated(self, results):
        s = get_scenario(results, "mixed_carbonate")
        si = s["saturation_indices"]["Magnesite"]
        assert si < -0.2, f"Magnesite SI = {si:.3f}, expected < 0"

    def test_brucite_very_undersaturated(self, results):
        s = get_scenario(results, "mixed_carbonate")
        si = s["saturation_indices"]["Brucite"]
        assert si < -3, f"Brucite SI = {si:.3f}, expected << 0 at pH 7.5"

    def test_calcium_mass_balance(self, results):
        s = get_scenario(results, "mixed_carbonate")
        ca_free = s["free_concentrations"]["Ca+2"]
        sp = s["species_concentrations"]
        total = ca_free + sp.get("CaCO3", 0) + sp.get("CaHCO3+", 0) + sp.get("CaOH+", 0) + sp.get("CaSO4", 0)
        assert approx_equal(total, 2e-3, rel_tol=0.05), f"Ca mass balance: {total:.4e} vs 2e-3"

    def test_magnesium_mass_balance(self, results):
        s = get_scenario(results, "mixed_carbonate")
        mg_free = s["free_concentrations"]["Mg+2"]
        sp = s["species_concentrations"]
        total = mg_free + sp.get("MgCO3", 0) + sp.get("MgHCO3+", 0) + sp.get("MgOH+", 0) + sp.get("MgSO4", 0)
        assert approx_equal(total, 1e-3, rel_tol=0.05), f"Mg mass balance: {total:.4e} vs 1e-3"

    def test_sulfate_mass_balance(self, results):
        s = get_scenario(results, "mixed_carbonate")
        so4_free = s["free_concentrations"]["SO4-2"]
        sp = s["species_concentrations"]
        total = so4_free + sp.get("HSO4-", 0) + sp.get("CaSO4", 0) + sp.get("MgSO4", 0)
        assert approx_equal(total, 5e-3, rel_tol=0.05), f"SO4 mass balance: {total:.4e} vs 5e-3"

    def test_bicarbonate_dominant_at_ph75(self, results):
        s = get_scenario(results, "mixed_carbonate")
        sp = s["species_concentrations"]
        hco3 = sp.get("HCO3-", 0)
        co3 = s["free_concentrations"]["CO3-2"]
        h2co3 = sp.get("H2CO3", 0)
        assert hco3 > co3, "HCO3- should dominate over CO3-2 at pH 7.5"
        assert hco3 > h2co3, "HCO3- should dominate over H2CO3 at pH 7.5"
