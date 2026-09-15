"""
Tests for LJ fluid thermal conductivity via multi-method NEMD.
Verifies results.json structure, physical plausibility, unit conversion,
and cross-method consistency.
"""

import json
import os
import math

RESULTS_PATH = "/app/results.json"

# Analytically correct conversion factor for argon:
# kappa_SI = kappa* x kB x sqrt(epsilon/m) / sigma^2
# With sigma=3.405e-10, eps/kB=119.8, m=6.6335e-26, kB=1.380649e-23
# Factor = 1.380649e-23 * sqrt(1.654018e-21 / 6.6335e-26) / (3.405e-10)^2
#        = 1.380649e-23 * 157.89 / 1.15940e-19
#        = 0.018804 W/(m*K)
EXPECTED_FACTOR = 0.018804
FACTOR_TOLERANCE = 0.35

# Reference kappa* ~ 3.4 for LJ at rho*=0.6, T*=1.35 (Evans 1986)
KAPPA_STAR_MIN = 1.5
KAPPA_STAR_MAX = 7.0

CROSS_VALIDATION_MAX_RATIO = 3.0


def load_results():
    with open(RESULTS_PATH) as f:
        return json.load(f)


class TestResultsFileStructure:
    def test_results_file_exists(self):
        assert os.path.exists(RESULTS_PATH), "results.json not found at /app/results.json"

    def test_results_has_all_required_fields(self):
        results = load_results()
        required = [
            "kappa_star_mp",
            "kappa_star_heat",
            "kappa_si_mp",
            "kappa_si_heat",
            "cross_validation_ratio",
            "conversion_factor_w_per_m_k",
        ]
        for field in required:
            assert field in results, f"Missing required field: {field}"
            assert isinstance(
                results[field], (int, float)
            ), f"{field} must be numeric, got {type(results[field])}"
            assert math.isfinite(results[field]), f"{field} must be finite"
            assert results[field] > 0, f"{field} must be positive"


class TestKappaStarValues:
    def test_kappa_star_mp_in_physical_range(self):
        results = load_results()
        kappa = results["kappa_star_mp"]
        assert KAPPA_STAR_MIN <= kappa <= KAPPA_STAR_MAX, (
            f"kappa*(MP) = {kappa:.3f} outside expected range "
            f"[{KAPPA_STAR_MIN}, {KAPPA_STAR_MAX}] for LJ fluid at rho*=0.6, T*=1.35"
        )

    def test_kappa_star_heat_in_physical_range(self):
        results = load_results()
        kappa = results["kappa_star_heat"]
        assert KAPPA_STAR_MIN <= kappa <= KAPPA_STAR_MAX, (
            f"kappa*(heat) = {kappa:.3f} outside expected range "
            f"[{KAPPA_STAR_MIN}, {KAPPA_STAR_MAX}] for LJ fluid at rho*=0.6, T*=1.35"
        )


class TestUnitConversion:
    def test_conversion_factor_matches_analytical(self):
        """The LJ-to-SI conversion factor must be derived correctly via
        dimensional analysis: kappa_SI = kappa* x kB x sqrt(eps/m) / sigma^2"""
        results = load_results()
        factor = results["conversion_factor_w_per_m_k"]
        lower = EXPECTED_FACTOR * (1 - FACTOR_TOLERANCE)
        upper = EXPECTED_FACTOR * (1 + FACTOR_TOLERANCE)
        assert lower <= factor <= upper, (
            f"Conversion factor {factor:.6f} W/(m*K) outside expected range "
            f"[{lower:.6f}, {upper:.6f}], correct value is ~{EXPECTED_FACTOR:.5f}"
        )

    def test_si_mp_consistent_with_star_times_factor(self):
        results = load_results()
        factor = results["conversion_factor_w_per_m_k"]
        expected = results["kappa_star_mp"] * factor
        actual = results["kappa_si_mp"]
        rel_err = abs(actual - expected) / expected
        assert rel_err < 0.05, (
            f"kappa_SI(MP) = {actual:.6f} inconsistent with "
            f"kappa*(MP) x factor = {expected:.6f} (rel err {rel_err:.3f})"
        )

    def test_si_heat_consistent_with_star_times_factor(self):
        results = load_results()
        factor = results["conversion_factor_w_per_m_k"]
        expected = results["kappa_star_heat"] * factor
        actual = results["kappa_si_heat"]
        rel_err = abs(actual - expected) / expected
        assert rel_err < 0.05, (
            f"kappa_SI(heat) = {actual:.6f} inconsistent with "
            f"kappa*(heat) x factor = {expected:.6f} (rel err {rel_err:.3f})"
        )

    def test_si_values_physically_reasonable(self):
        """SI thermal conductivity for argon-like LJ fluid should be
        in range [0.005, 0.5] W/(m*K)"""
        results = load_results()
        for key in ["kappa_si_mp", "kappa_si_heat"]:
            val = results[key]
            assert 0.005 <= val <= 0.5, (
                f"{key} = {val:.6f} W/(m*K) outside physically reasonable range "
                f"for an argon-like Lennard-Jones fluid"
            )


class TestCrossValidation:
    def test_cross_validation_ratio_reasonable(self):
        results = load_results()
        ratio = results["cross_validation_ratio"]
        assert 1.0 <= ratio <= CROSS_VALIDATION_MAX_RATIO, (
            f"Cross-validation ratio {ratio:.3f} outside acceptable range "
            f"[1.0, {CROSS_VALIDATION_MAX_RATIO}]"
        )

    def test_cross_validation_ratio_computed_correctly(self):
        results = load_results()
        k_mp = results["kappa_star_mp"]
        k_heat = results["kappa_star_heat"]
        expected_ratio = max(k_mp, k_heat) / min(k_mp, k_heat)
        actual_ratio = results["cross_validation_ratio"]
        assert abs(actual_ratio - expected_ratio) < 0.02, (
            f"Cross-validation ratio {actual_ratio:.4f} does not match "
            f"max/min = {expected_ratio:.4f}"
        )


class TestProfileData:
    def test_mp_profile_exists_with_data(self):
        fpath = "/app/profile.mp"
        assert os.path.exists(fpath), "Temperature profile file profile.mp not found"
        assert os.path.getsize(fpath) > 50, "profile.mp is too small to contain valid data"

    def test_heat_profile_exists_with_data(self):
        fpath = "/app/profile.heat"
        assert os.path.exists(fpath), "Temperature profile file profile.heat not found"
        assert os.path.getsize(fpath) > 50, "profile.heat is too small to contain valid data"
