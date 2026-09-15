"""Tests for SPACE landscape evolution multi-regime analyzer.

Verifies that the solver correctly:
1. Sets up and runs SPACE on a landlab RasterModelGrid
2. Classifies erosion regimes
3. Computes analytical steady-state solutions
4. Achieves numerical convergence
5. Computes slope-area concavity index
"""


import json
import os

import numpy as np
import pytest


RESULTS_PATH = "/app/results.json"
CONFIG_PATH = "/app/config.json"


@pytest.fixture(scope="session")
def config():
    with open(CONFIG_PATH) as f:
        return json.load(f)


@pytest.fixture(scope="session")
def results():
    with open(RESULTS_PATH) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Structure tests
# ---------------------------------------------------------------------------

class TestStructure:
    def test_results_file_exists(self):
        assert os.path.exists(RESULTS_PATH), "results.json not found"

    def test_results_valid_json(self, results):
        assert isinstance(results, dict)

    def test_all_scenarios_present(self, results, config):
        for name in config["scenarios"]:
            assert name in results, f"Scenario '{name}' missing from results"

    @pytest.mark.parametrize("scenario", ["detachment_limited", "transport_limited", "bedrock_alluvial"])
    def test_required_keys(self, results, scenario):
        required = {
            "regime",
            "core_node_slopes",
            "core_node_drainage_areas",
            "core_node_soil_depths",
            "core_node_sediment_fluxes",
            "analytical_slopes",
            "analytical_soil_depth",
            "analytical_sediment_fluxes",
            "slope_area_concavity",
        }
        assert required.issubset(set(results[scenario].keys())), \
            f"Scenario '{scenario}' missing keys: {required - set(results[scenario].keys())}"


# ---------------------------------------------------------------------------
# Regime classification
# ---------------------------------------------------------------------------

class TestRegimeClassification:
    def test_detachment_limited(self, results):
        assert results["detachment_limited"]["regime"] == "detachment_limited"

    def test_transport_limited(self, results):
        assert results["transport_limited"]["regime"] == "transport_limited"

    def test_bedrock_alluvial(self, results):
        assert results["bedrock_alluvial"]["regime"] == "bedrock_alluvial"


# ---------------------------------------------------------------------------
# Physical consistency
# ---------------------------------------------------------------------------

class TestPhysicalConsistency:
    @pytest.mark.parametrize("scenario", ["detachment_limited", "transport_limited", "bedrock_alluvial"])
    def test_slopes_positive(self, results, scenario):
        slopes = np.array(results[scenario]["core_node_slopes"])
        assert np.all(slopes > 0), f"Non-positive slopes in {scenario}"

    @pytest.mark.parametrize("scenario", ["detachment_limited", "transport_limited", "bedrock_alluvial"])
    def test_drainage_areas_positive(self, results, scenario):
        areas = np.array(results[scenario]["core_node_drainage_areas"])
        assert np.all(areas > 0), f"Non-positive drainage areas in {scenario}"

    @pytest.mark.parametrize("scenario", ["detachment_limited", "transport_limited", "bedrock_alluvial"])
    def test_core_node_count(self, results, config, scenario):
        """Grid with all boundaries closed except node 0 has (rows-2)*(cols-2) core nodes."""
        p = config["scenarios"][scenario]
        expected = (p["grid_rows"] - 2) * (p["grid_cols"] - 2)
        actual = len(results[scenario]["core_node_slopes"])
        assert actual == expected, f"Expected {expected} core nodes, got {actual}"

    @pytest.mark.parametrize("scenario", ["detachment_limited", "transport_limited", "bedrock_alluvial"])
    def test_array_lengths_consistent(self, results, scenario):
        r = results[scenario]
        n = len(r["core_node_slopes"])
        assert len(r["core_node_drainage_areas"]) == n
        assert len(r["core_node_soil_depths"]) == n
        assert len(r["core_node_sediment_fluxes"]) == n
        assert len(r["analytical_slopes"]) == n

    @pytest.mark.parametrize("scenario", ["detachment_limited", "transport_limited", "bedrock_alluvial"])
    def test_soil_depths_non_negative(self, results, scenario):
        """Soil depth must be physically non-negative everywhere."""
        depths = np.array(results[scenario]["core_node_soil_depths"])
        assert np.all(depths >= -1e-10), f"Negative soil depth in {scenario}"

    @pytest.mark.parametrize("scenario", ["detachment_limited", "transport_limited", "bedrock_alluvial"])
    def test_drainage_area_minimum(self, results, config, scenario):
        """Every node drains at least its own cell area."""
        p = config["scenarios"][scenario]
        cell_area = p["grid_spacing"] ** 2
        areas = np.array(results[scenario]["core_node_drainage_areas"])
        assert np.all(areas >= cell_area - 1e-6), \
            f"Drainage areas smaller than cell area in {scenario}"


# ---------------------------------------------------------------------------
# Detachment-limited analytical verification
# ---------------------------------------------------------------------------

class TestDetachmentLimited:
    def test_analytical_slopes_formula(self, results, config):
        """Independently verify the analytical slope-area relationship."""
        s = results["detachment_limited"]
        p = config["scenarios"]["detachment_limited"]

        U = p["uplift_rate"]
        K_br = p["K_br"]
        m = p["m_sp"]
        n = p["n_sp"]

        A = np.array(s["core_node_drainage_areas"])
        expected = np.power(U / K_br, 1.0 / n) * np.power(A, -m / n)
        reported = np.array(s["analytical_slopes"])

        np.testing.assert_allclose(
            reported, expected, rtol=1e-6,
            err_msg="Detachment-limited analytical slopes don't match formula",
        )

    def test_numerical_convergence(self, results):
        """Numerical slopes should converge to analytical."""
        s = results["detachment_limited"]
        num = np.array(s["core_node_slopes"])
        ana = np.array(s["analytical_slopes"])
        rmse = np.sqrt(np.mean((num - ana) ** 2))
        assert rmse < 1e-4, f"Detachment-limited slope RMSE = {rmse:.2e}, expected < 1e-4"

    def test_soil_depth_negligible(self, results):
        """Detachment-limited should have negligible soil."""
        depths = np.array(results["detachment_limited"]["core_node_soil_depths"])
        assert np.all(np.abs(depths) < 0.1), "Soil should be negligible in detachment-limited regime"

    def test_no_analytical_soil_depth(self, results):
        assert results["detachment_limited"]["analytical_soil_depth"] is None

    def test_no_analytical_sediment_flux(self, results):
        assert results["detachment_limited"]["analytical_sediment_fluxes"] is None


# ---------------------------------------------------------------------------
# Transport-limited analytical verification
# ---------------------------------------------------------------------------

class TestTransportLimited:
    def test_analytical_slopes_formula(self, results, config):
        """Independently verify the transport-limited slope formula."""
        s = results["transport_limited"]
        p = config["scenarios"]["transport_limited"]

        U = p["uplift_rate"]
        K_sed = p["K_sed"]
        v_s = p["v_s"]
        phi = p["phi"]
        m = p["m_sp"]
        n = p["n_sp"]

        A = np.array(s["core_node_drainage_areas"])
        expected = np.power(
            (U * v_s * (1.0 - phi)) / (K_sed * np.power(A, m))
            + (U * (1.0 - phi)) / (K_sed * np.power(A, m)),
            1.0 / n,
        )
        reported = np.array(s["analytical_slopes"])

        np.testing.assert_allclose(
            reported, expected, rtol=1e-6,
            err_msg="Transport-limited analytical slopes don't match formula",
        )

    def test_numerical_slope_convergence(self, results):
        s = results["transport_limited"]
        num = np.array(s["core_node_slopes"])
        ana = np.array(s["analytical_slopes"])
        rmse = np.sqrt(np.mean((num - ana) ** 2))
        assert rmse < 1e-4, f"Transport-limited slope RMSE = {rmse:.2e}, expected < 1e-4"

    def test_analytical_sediment_flux_formula(self, results, config):
        """Verify the steady-state mass balance sediment flux."""
        s = results["transport_limited"]
        p = config["scenarios"]["transport_limited"]

        U = p["uplift_rate"]
        phi = p["phi"]
        A = np.array(s["core_node_drainage_areas"])

        expected = U * A * (1.0 - phi)
        reported = np.array(s["analytical_sediment_fluxes"])

        np.testing.assert_allclose(
            reported, expected, rtol=1e-6,
            err_msg="Transport-limited analytical sediment flux doesn't match formula",
        )

    def test_sediment_flux_convergence(self, results):
        """Numerical sediment fluxes should match analytical within 1%."""
        s = results["transport_limited"]
        num = np.array(s["core_node_sediment_fluxes"])
        ana = np.array(s["analytical_sediment_fluxes"])
        np.testing.assert_allclose(
            num, ana, rtol=0.01,
            err_msg="Transport-limited sediment flux not converged",
        )

    def test_no_analytical_soil_depth(self, results):
        assert results["transport_limited"]["analytical_soil_depth"] is None


# ---------------------------------------------------------------------------
# Bedrock-alluvial analytical verification
# ---------------------------------------------------------------------------

class TestBedrockAlluvial:
    def test_analytical_slopes_formula(self, results, config):
        """Independently verify the bedrock-alluvial slope formula."""
        s = results["bedrock_alluvial"]
        p = config["scenarios"]["bedrock_alluvial"]

        U = p["uplift_rate"]
        K_sed = p["K_sed"]
        K_br = p["K_br"]
        v_s = p["v_s"]
        F_f = p["F_f"]
        m = p["m_sp"]
        n = p["n_sp"]

        A = np.array(s["core_node_drainage_areas"])
        expected = np.power(
            (U * v_s * (1.0 - F_f)) / (K_sed * np.power(A, m))
            + U / (K_br * np.power(A, m)),
            1.0 / n,
        )
        reported = np.array(s["analytical_slopes"])

        np.testing.assert_allclose(
            reported, expected, rtol=1e-6,
            err_msg="Bedrock-alluvial analytical slopes don't match formula",
        )

    def test_numerical_slope_convergence(self, results):
        s = results["bedrock_alluvial"]
        num = np.array(s["core_node_slopes"])
        ana = np.array(s["analytical_slopes"])
        rmse = np.sqrt(np.mean((num - ana) ** 2))
        assert rmse < 1e-4, f"Bedrock-alluvial slope RMSE = {rmse:.2e}, expected < 1e-4"

    def test_analytical_soil_depth_formula(self, results, config):
        """Verify the equilibrium soil depth from the SPACE governing equations."""
        s = results["bedrock_alluvial"]
        p = config["scenarios"]["bedrock_alluvial"]

        H_star = p["H_star"]
        v_s = p["v_s"]
        K_sed = p["K_sed"]
        K_br = p["K_br"]
        F_f = p["F_f"]

        expected = -H_star * np.log(
            1.0 - (v_s / (K_sed / (K_br * (1.0 - F_f)) + v_s))
        )
        reported = s["analytical_soil_depth"]

        assert abs(reported - expected) < 1e-6, \
            f"Bedrock-alluvial analytical soil depth: got {reported}, expected {expected}"

    def test_soil_depth_convergence(self, results):
        """All core nodes should have soil depth close to analytical."""
        s = results["bedrock_alluvial"]
        num = np.array(s["core_node_soil_depths"])
        ana = s["analytical_soil_depth"]
        np.testing.assert_allclose(
            num, ana, atol=1e-3,
            err_msg="Bedrock-alluvial soil depths not converged",
        )

    def test_no_analytical_sediment_flux(self, results):
        assert results["bedrock_alluvial"]["analytical_sediment_fluxes"] is None


# ---------------------------------------------------------------------------
# Concavity index
# ---------------------------------------------------------------------------

class TestConcavity:
    @pytest.mark.parametrize("scenario", ["detachment_limited", "transport_limited", "bedrock_alluvial"])
    def test_concavity_matches_theory(self, results, config, scenario):
        """Concavity index should match m/n from the power-law slope-area scaling."""
        p = config["scenarios"][scenario]
        expected_theta = p["m_sp"] / p["n_sp"]
        reported = results[scenario]["slope_area_concavity"]
        assert abs(reported - expected_theta) < 0.1, \
            f"Concavity {reported:.4f} not within 0.1 of m/n={expected_theta:.4f} in {scenario}"

    @pytest.mark.parametrize("scenario", ["detachment_limited", "transport_limited", "bedrock_alluvial"])
    def test_concavity_positive(self, results, scenario):
        """Concavity index should be positive (slopes decrease with area)."""
        assert results[scenario]["slope_area_concavity"] > 0, \
            f"Concavity should be positive in {scenario}"

    def test_concavity_consistent_across_regimes(self, results):
        """All scenarios use the same m/n so concavity indices should be similar."""
        concavities = [results[s]["slope_area_concavity"] for s in results]
        spread = max(concavities) - min(concavities)
        assert spread < 0.15, \
            f"Concavity spread across regimes is {spread:.4f}, expected < 0.15"


# ---------------------------------------------------------------------------
# Cross-scenario validation
# ---------------------------------------------------------------------------

class TestCrossScenario:
    def test_slopes_decrease_with_area(self, results):
        """In all regimes, larger drainage area should yield lower slope (power law)."""
        for name in ["detachment_limited", "transport_limited", "bedrock_alluvial"]:
            s = results[name]
            slopes = np.array(s["analytical_slopes"])
            da = np.array(s["core_node_drainage_areas"])
            order = np.argsort(da)
            sorted_slopes = slopes[order]
            sorted_areas = da[order]
            for i in range(len(sorted_areas) - 1):
                if sorted_areas[i + 1] > sorted_areas[i] + 1e-10:
                    assert sorted_slopes[i + 1] <= sorted_slopes[i] + 1e-10, \
                        f"Slope not decreasing with area in {name}"

    def test_analytical_slopes_are_power_law(self, results, config):
        """Analytical slopes should follow a tight power-law (high R^2 in log-log)."""
        for name in config["scenarios"]:
            s = results[name]
            A = np.array(s["core_node_drainage_areas"])
            S = np.array(s["analytical_slopes"])
            log_a = np.log(A)
            log_s = np.log(S)
            coeffs = np.polyfit(log_a, log_s, 1)
            predicted = np.polyval(coeffs, log_a)
            ss_res = np.sum((log_s - predicted) ** 2)
            ss_tot = np.sum((log_s - np.mean(log_s)) ** 2)
            r_squared = 1.0 - ss_res / ss_tot if ss_tot > 0 else 1.0
            assert r_squared > 0.99, \
                f"Analytical slopes R^2 = {r_squared:.4f} in {name}, expected > 0.99"

    @pytest.mark.parametrize("scenario", ["detachment_limited", "transport_limited", "bedrock_alluvial"])
    def test_sediment_fluxes_non_negative(self, results, scenario):
        """Sediment flux should be non-negative at all core nodes."""
        fluxes = np.array(results[scenario]["core_node_sediment_fluxes"])
        assert np.all(fluxes >= -1e-10), f"Negative sediment flux in {scenario}"
