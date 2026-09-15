
"""
Verification tests for two-phase flow boiling analysis engine.

Golden reference values are from CalebBell/fluids and CalebBell/ht test suites
(MIT licensed, verified against VDI Heat Atlas correlations).
"""

import json
import math
import os

import pytest

# Golden reference values from authoritative test suites
GOLDEN = {
    "friedel_1": {"dP": 738.6500525002241},
    "friedel_2": {"dP": 274.21322116878406},
    "friedel_3": {"dP": 2742.1322116878405},
    "gronnerud_1": {"dP": 384.12541144474085},
    "gronnerud_2": {"dP": 26650.676132410194},
    "chisholm_1": {"dP": 1084.1489922923736},
    "chisholm_2": {"dP": 7081.89630764668},
    "chisholm_3": {"dP": 8743.742915625126},
    "void_1": {
        "homogeneous": 0.995334370139969,
        "thom": 0.9801482164042417,
        "xtt": 0.12761659240532292,
    },
    "chen_bennett_1": {"h": 4938.275351219369},
    "gorenflo_1": {"h": 3043.344595525422},
}

# Relative tolerances
DP_RTOL = 0.01  # 1% for pressure drops (friction factor impl may vary)
HT_RTOL = 0.005  # 0.5% for heat transfer coefficients
VF_RTOL = 1e-4  # 0.01% for void fractions (pure formulas)


def assert_close(actual, expected, rtol, label=""):
    """Assert that actual is within rtol of expected (relative)."""
    if expected == 0:
        assert abs(actual) < 1e-10, f"{label}: got {actual}, expected ~0"
    else:
        rel_err = abs(actual - expected) / abs(expected)
        assert rel_err < rtol, (
            f"{label}: got {actual}, expected {expected}, "
            f"rel_err={rel_err:.4e} exceeds rtol={rtol}"
        )


@pytest.fixture(scope="module")
def results():
    """Load the results.json produced by the solver's tool."""
    results_path = "/app/results.json"
    assert os.path.exists(results_path), (
        "results.json not found at /app/results.json. "
        "Did python3 /app/twophase.py run successfully?"
    )
    with open(results_path) as f:
        return json.load(f)


class TestResultsFormat:
    """Verify that the output format is correct."""

    def test_results_file_exists(self):
        assert os.path.exists("/app/results.json"), "results.json not found"

    def test_all_case_ids_present(self, results):
        for case_id in GOLDEN:
            assert case_id in results, f"Missing case '{case_id}' in results"

    def test_pressure_drop_keys(self, results):
        pd_cases = [
            "friedel_1", "friedel_2", "friedel_3",
            "gronnerud_1", "gronnerud_2",
            "chisholm_1", "chisholm_2", "chisholm_3",
        ]
        for case_id in pd_cases:
            assert "dP" in results[case_id], (
                f"Missing 'dP' key in result for '{case_id}'"
            )

    def test_void_fraction_keys(self, results):
        for key in ["homogeneous", "thom", "xtt"]:
            assert key in results["void_1"], (
                f"Missing '{key}' key in void_1 result"
            )

    def test_heat_transfer_keys(self, results):
        for case_id in ["chen_bennett_1", "gorenflo_1"]:
            assert "h" in results[case_id], (
                f"Missing 'h' key in result for '{case_id}'"
            )

    def test_values_are_numeric(self, results):
        for case_id, expected in GOLDEN.items():
            for key in expected:
                val = results[case_id][key]
                assert isinstance(val, (int, float)), (
                    f"{case_id}.{key} is {type(val).__name__}, expected numeric"
                )

    def test_values_are_positive(self, results):
        for case_id, expected in GOLDEN.items():
            for key in expected:
                val = results[case_id][key]
                assert val > 0, (
                    f"{case_id}.{key} = {val}, expected positive value"
                )


class TestFriedel:
    """Friedel (1979) two-phase pressure drop correlation."""

    def test_standard_conditions(self, results):
        assert_close(
            results["friedel_1"]["dP"],
            GOLDEN["friedel_1"]["dP"],
            DP_RTOL,
            "Friedel: m=0.6, x=0.1, standard fluid",
        )

    def test_high_quality(self, results):
        assert_close(
            results["friedel_2"]["dP"],
            GOLDEN["friedel_2"]["dP"],
            DP_RTOL,
            "Friedel: m=10, x=0.9, high quality",
        )

    def test_length_proportionality(self, results):
        """Pressure drop must scale linearly with pipe length."""
        dP_L1 = results["friedel_2"]["dP"]
        dP_L10 = results["friedel_3"]["dP"]
        ratio = dP_L10 / dP_L1
        assert abs(ratio - 10.0) / 10.0 < DP_RTOL, (
            f"Friedel length proportionality failed: "
            f"dP(L=10)/dP(L=1) = {ratio:.4f}, expected 10.0"
        )

    def test_length_10_absolute(self, results):
        assert_close(
            results["friedel_3"]["dP"],
            GOLDEN["friedel_3"]["dP"],
            DP_RTOL,
            "Friedel: L=10 absolute value",
        )


class TestGronnerud:
    """Gronnerud (1972) two-phase pressure drop correlation."""

    def test_low_mass_flux(self, results):
        assert_close(
            results["gronnerud_1"]["dP"],
            GOLDEN["gronnerud_1"]["dP"],
            DP_RTOL,
            "Gronnerud: m=0.6, low mass flux",
        )

    def test_high_mass_flux(self, results):
        assert_close(
            results["gronnerud_2"]["dP"],
            GOLDEN["gronnerud_2"]["dP"],
            DP_RTOL,
            "Gronnerud: m=5, high mass flux",
        )

    def test_mass_flux_ordering(self, results):
        """Higher mass flow rate should give higher pressure drop."""
        dP_low = results["gronnerud_1"]["dP"]
        dP_high = results["gronnerud_2"]["dP"]
        assert dP_high > dP_low, (
            f"Gronnerud: dP at m=5 ({dP_high:.1f}) should exceed "
            f"dP at m=0.6 ({dP_low:.1f})"
        )


class TestChisholm:
    """Chisholm (1973) two-phase pressure drop correlation."""

    def test_gamma_mid_G_low(self, results):
        """Tests 9.5 < Gamma < 28, G < 600 branch."""
        assert_close(
            results["chisholm_1"]["dP"],
            GOLDEN["chisholm_1"]["dP"],
            DP_RTOL,
            "Chisholm: mid-Gamma, low-G",
        )

    def test_gamma_mid_G_high(self, results):
        """Tests 9.5 < Gamma < 28, G > 600 branch."""
        assert_close(
            results["chisholm_2"]["dP"],
            GOLDEN["chisholm_2"]["dP"],
            DP_RTOL,
            "Chisholm: mid-Gamma, high-G",
        )

    def test_gamma_high(self, results):
        """Tests Gamma > 28 branch (extreme density ratio)."""
        assert_close(
            results["chisholm_3"]["dP"],
            GOLDEN["chisholm_3"]["dP"],
            DP_RTOL,
            "Chisholm: high-Gamma",
        )


class TestVoidFraction:
    """Void fraction and Lockhart-Martinelli parameter."""

    def test_homogeneous(self, results):
        assert_close(
            results["void_1"]["homogeneous"],
            GOLDEN["void_1"]["homogeneous"],
            VF_RTOL,
            "Homogeneous void fraction",
        )

    def test_thom(self, results):
        assert_close(
            results["void_1"]["thom"],
            GOLDEN["void_1"]["thom"],
            VF_RTOL,
            "Thom void fraction",
        )

    def test_xtt(self, results):
        assert_close(
            results["void_1"]["xtt"],
            GOLDEN["void_1"]["xtt"],
            VF_RTOL,
            "Lockhart-Martinelli Xtt",
        )

    def test_ordering(self, results):
        """Homogeneous model typically gives highest void fraction."""
        alpha_h = results["void_1"]["homogeneous"]
        alpha_t = results["void_1"]["thom"]
        assert alpha_h > alpha_t, (
            "Homogeneous void fraction should exceed Thom for these conditions"
        )


class TestChenBennett:
    """Chen-Bennett flow boiling heat transfer correlation."""

    def test_heat_transfer_coefficient(self, results):
        assert_close(
            results["chen_bennett_1"]["h"],
            GOLDEN["chen_bennett_1"]["h"],
            HT_RTOL,
            "Chen-Bennett h",
        )

    def test_reasonable_magnitude(self, results):
        """Flow boiling HTC should be in a physically reasonable range."""
        h = results["chen_bennett_1"]["h"]
        assert 100 < h < 100000, (
            f"Chen-Bennett h = {h:.1f} W/m²/K is outside reasonable range"
        )


class TestGorenflo:
    """Gorenflo (VDI) pool boiling correlation."""

    def test_water_pool_boiling(self, results):
        assert_close(
            results["gorenflo_1"]["h"],
            GOLDEN["gorenflo_1"]["h"],
            HT_RTOL,
            "Gorenflo: water at 3 bar",
        )

    def test_reasonable_magnitude(self, results):
        """Pool boiling HTC for water should be in reasonable range."""
        h = results["gorenflo_1"]["h"]
        assert 500 < h < 50000, (
            f"Gorenflo h = {h:.1f} W/m²/K is outside reasonable range for water"
        )


class TestCrossValidation:
    """Cross-correlation consistency checks."""

    def test_pressure_drop_correlation_ordering(self, results):
        """For these specific conditions, verify relative ordering holds."""
        dP_f = results["friedel_1"]["dP"]
        dP_g = results["gronnerud_1"]["dP"]
        dP_c = results["chisholm_1"]["dP"]
        # All should be positive
        assert dP_f > 0 and dP_g > 0 and dP_c > 0
        # For x=0.1 with these fluid props, Chisholm > Friedel > Gronnerud
        assert dP_c > dP_f > dP_g, (
            f"Expected Chisholm ({dP_c:.1f}) > Friedel ({dP_f:.1f}) > "
            f"Gronnerud ({dP_g:.1f}) for these conditions"
        )
