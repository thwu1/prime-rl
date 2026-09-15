
"""
Tests for elastic constants and derived mechanical properties of SW silicon.
Verifies that results.json contains physically correct and self-consistent values.
"""

import json
import os
import math
import pytest

RESULTS_PATH = "/app/results.json"

REQUIRED_KEYS = [
    "C11", "C12", "C44",
    "bulk_modulus",
    "shear_modulus_voigt", "shear_modulus_reuss", "shear_modulus_hill",
    "youngs_modulus_100", "youngs_modulus_111",
    "poisson_ratio",
    "zener_anisotropy",
    "cauchy_pressure",
]


@pytest.fixture
def results():
    assert os.path.isfile(RESULTS_PATH), f"Results file not found at {RESULTS_PATH}"
    with open(RESULTS_PATH) as f:
        data = json.load(f)
    return data


class TestResultsStructure:
    def test_file_exists(self):
        assert os.path.isfile(RESULTS_PATH), "results.json not found"

    def test_valid_json(self):
        with open(RESULTS_PATH) as f:
            data = json.load(f)
        assert isinstance(data, dict), "results.json must contain a JSON object"

    def test_all_keys_present(self, results):
        for key in REQUIRED_KEYS:
            assert key in results, f"Missing required key: {key}"

    def test_all_values_numeric(self, results):
        for key in REQUIRED_KEYS:
            val = results[key]
            assert isinstance(val, (int, float)), f"{key} must be numeric, got {type(val)}"
            assert math.isfinite(val), f"{key} must be finite, got {val}"


class TestElasticConstants:
    """Verify the three independent cubic elastic constants against known SW Si values."""

    def test_C11_range(self, results):
        c11 = results["C11"]
        assert 149.0 <= c11 <= 153.0, f"C11={c11:.2f} out of range [149, 153] GPa"

    def test_C12_range(self, results):
        c12 = results["C12"]
        assert 75.0 <= c12 <= 77.0, f"C12={c12:.2f} out of range [75, 77] GPa"

    def test_C44_range(self, results):
        c44 = results["C44"]
        assert 55.0 <= c44 <= 57.0, f"C44={c44:.2f} out of range [55, 57] GPa"

    def test_stability_born_criterion_1(self, results):
        """Born stability: C11 > |C12|"""
        assert results["C11"] > abs(results["C12"])

    def test_stability_born_criterion_2(self, results):
        """Born stability: C11 + 2*C12 > 0 (positive bulk modulus)"""
        assert results["C11"] + 2 * results["C12"] > 0

    def test_stability_born_criterion_3(self, results):
        """Born stability: C44 > 0"""
        assert results["C44"] > 0


class TestBulkModulus:
    def test_bulk_modulus_range(self, results):
        K = results["bulk_modulus"]
        assert 99.0 <= K <= 103.0, f"K={K:.2f} out of expected range [99, 103] GPa"

    def test_bulk_modulus_consistency(self, results):
        """K must equal (C11 + 2*C12) / 3 to within 0.5 GPa."""
        K = results["bulk_modulus"]
        K_expected = (results["C11"] + 2 * results["C12"]) / 3.0
        assert abs(K - K_expected) < 0.5, (
            f"K={K:.4f} inconsistent with (C11+2C12)/3={K_expected:.4f}"
        )


class TestShearModuli:
    def test_voigt_range(self, results):
        G_V = results["shear_modulus_voigt"]
        assert 47.0 <= G_V <= 50.5, f"G_V={G_V:.2f} out of range"

    def test_reuss_range(self, results):
        G_R = results["shear_modulus_reuss"]
        assert 45.0 <= G_R <= 49.0, f"G_R={G_R:.2f} out of range"

    def test_reuss_nonzero(self, results):
        """Reuss shear modulus must not be zero (catch unimplemented stub)."""
        assert results["shear_modulus_reuss"] > 1.0, (
            f"G_R={results['shear_modulus_reuss']:.4f} appears unimplemented"
        )

    def test_hill_is_average(self, results):
        """Hill average must be (G_V + G_R) / 2."""
        G_H = results["shear_modulus_hill"]
        expected = (results["shear_modulus_voigt"] + results["shear_modulus_reuss"]) / 2.0
        assert abs(G_H - expected) < 0.3, (
            f"G_H={G_H:.4f} not average of G_V and G_R ({expected:.4f})"
        )

    def test_voigt_geq_reuss(self, results):
        """Voigt bound >= Reuss bound (always true)."""
        assert results["shear_modulus_voigt"] >= results["shear_modulus_reuss"] - 0.01

    def test_voigt_consistency(self, results):
        """G_V = (C11 - C12 + 3*C44) / 5 for cubic."""
        G_V = results["shear_modulus_voigt"]
        expected = (results["C11"] - results["C12"] + 3 * results["C44"]) / 5.0
        assert abs(G_V - expected) < 0.5, (
            f"G_V={G_V:.4f} inconsistent with formula ({expected:.4f})"
        )

    def test_reuss_consistency(self, results):
        """G_R = 5*(C11-C12)*C44 / (4*C44 + 3*(C11-C12)) for cubic."""
        C11, C12, C44 = results["C11"], results["C12"], results["C44"]
        G_R = results["shear_modulus_reuss"]
        expected = 5.0 * (C11 - C12) * C44 / (4 * C44 + 3 * (C11 - C12))
        assert abs(G_R - expected) < 0.5, (
            f"G_R={G_R:.4f} inconsistent with formula ({expected:.4f})"
        )


class TestYoungsModulus:
    def test_E100_range(self, results):
        E = results["youngs_modulus_100"]
        assert 98.0 <= E <= 103.0, f"E_100={E:.2f} out of range"

    def test_E111_range(self, results):
        E = results["youngs_modulus_111"]
        assert 140.0 <= E <= 146.0, f"E_111={E:.2f} out of range"

    def test_E111_nonzero(self, results):
        """E_111 must not be zero (catch unimplemented stub)."""
        assert results["youngs_modulus_111"] > 1.0, (
            f"E_111={results['youngs_modulus_111']:.4f} appears unimplemented"
        )

    def test_E111_greater_than_E100(self, results):
        """For SW Si (anisotropy ratio A > 1), E_111 > E_100."""
        assert results["youngs_modulus_111"] > results["youngs_modulus_100"]

    def test_E100_consistency(self, results):
        """E_100 = (C11-C12)(C11+2C12)/(C11+C12) for cubic."""
        C11, C12 = results["C11"], results["C12"]
        E = results["youngs_modulus_100"]
        expected = (C11 - C12) * (C11 + 2 * C12) / (C11 + C12)
        assert abs(E - expected) < 1.0, (
            f"E_100={E:.4f} inconsistent with formula ({expected:.4f})"
        )

    def test_E111_consistency(self, results):
        """E_111 must be consistent with compliance tensor and [111] orientation."""
        C11, C12, C44 = results["C11"], results["C12"], results["C44"]
        denom = (C11 - C12) * (C11 + 2 * C12)
        S11 = (C11 + C12) / denom
        S12 = -C12 / denom
        S44 = 1.0 / C44
        Gamma = 1.0 / 3.0
        expected = 1.0 / (S11 - 2.0 * (S11 - S12 - 0.5 * S44) * Gamma)
        E = results["youngs_modulus_111"]
        assert abs(E - expected) < 1.0, (
            f"E_111={E:.4f} inconsistent with compliance formula ({expected:.4f})"
        )


class TestDerivedProperties:
    def test_poisson_ratio_range(self, results):
        nu = results["poisson_ratio"]
        assert 0.25 <= nu <= 0.32, f"nu={nu:.4f} out of expected range"

    def test_poisson_ratio_consistency(self, results):
        """Poisson ratio must be consistent with bulk and Hill shear moduli."""
        K = results["bulk_modulus"]
        G_H = results["shear_modulus_hill"]
        nu = results["poisson_ratio"]
        expected = (3 * K - 2 * G_H) / (2 * (3 * K + G_H))
        assert abs(nu - expected) < 0.005, (
            f"nu={nu:.6f} inconsistent with (3K-2G_H)/(2(3K+G_H))={expected:.6f}"
        )

    def test_zener_anisotropy_range(self, results):
        A = results["zener_anisotropy"]
        assert 1.3 <= A <= 1.7, f"A={A:.4f} out of expected range"

    def test_zener_anisotropy_consistency(self, results):
        """A = 2*C44 / (C11 - C12)."""
        A = results["zener_anisotropy"]
        expected = 2 * results["C44"] / (results["C11"] - results["C12"])
        assert abs(A - expected) < 0.02, (
            f"A={A:.6f} inconsistent with formula ({expected:.6f})"
        )

    def test_cauchy_pressure_consistency(self, results):
        """Cauchy pressure = C12 - C44."""
        cp = results["cauchy_pressure"]
        expected = results["C12"] - results["C44"]
        assert abs(cp - expected) < 0.5, (
            f"cauchy_pressure={cp:.4f} inconsistent with C12-C44={expected:.4f}"
        )

    def test_cauchy_pressure_range(self, results):
        cp = results["cauchy_pressure"]
        assert 18.0 <= cp <= 22.0, f"cauchy_pressure={cp:.2f} out of range"

    def test_cauchy_pressure_nonzero(self, results):
        """Cauchy pressure must not be zero (catch unimplemented stub)."""
        assert abs(results["cauchy_pressure"]) > 1.0, (
            f"cauchy_pressure={results['cauchy_pressure']:.4f} appears unimplemented"
        )
