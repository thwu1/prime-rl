"""Tests for two-phase Poiseuille flow relative permeability analysis.

"""

import json
import math
import os

import pytest


RESULTS_PATH = "/app/results.json"

EXPECTED_SATURATIONS = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
EXPECTED_MU_RATIOS = [1.0, 2.0, 5.0, 10.0, 20.0]
EXPECTED_MU_RATIO_KEYS = [f"mu_ratio_{r}" for r in EXPECTED_MU_RATIOS]


def load_results():
    """Load and return results.json."""
    assert os.path.exists(RESULTS_PATH), f"{RESULTS_PATH} does not exist"
    with open(RESULTS_PATH) as f:
        return json.load(f)


def find_sw_index(sw_list, target, tol=1e-9):
    """Find index of target saturation in list, with tolerance."""
    for i, sw in enumerate(sw_list):
        if abs(sw - target) < tol:
            return i
    raise ValueError(f"Saturation {target} not found in {sw_list}")


def get_kr_data(results, mu_ratio):
    """Get kr data for a viscosity ratio, flexible about key format."""
    key = f"mu_ratio_{mu_ratio}"
    if key in results["analytical_kr"]:
        return results["analytical_kr"][key]
    if mu_ratio == int(mu_ratio):
        key2 = f"mu_ratio_{int(mu_ratio)}.0"
        if key2 in results["analytical_kr"]:
            return results["analytical_kr"][key2]
    raise KeyError(f"Cannot find kr data for mu_ratio={mu_ratio}. "
                   f"Available keys: {list(results['analytical_kr'].keys())}")


# ============================================================================
# Structure Tests
# ============================================================================

class TestStructure:
    """Verify results.json has the required structure."""

    def test_results_file_exists(self):
        assert os.path.exists(RESULTS_PATH)

    def test_top_level_keys(self):
        results = load_results()
        assert "analytical_kr" in results, "Missing 'analytical_kr'"
        assert "convergence" in results, "Missing 'convergence'"
        assert "validation" in results, "Missing 'validation'"

    def test_all_viscosity_ratios_present(self):
        results = load_results()
        for key in EXPECTED_MU_RATIO_KEYS:
            assert key in results["analytical_kr"], f"Missing {key}"

    def test_all_saturations_present(self):
        results = load_results()
        for key in EXPECTED_MU_RATIO_KEYS:
            data = results["analytical_kr"][key]
            assert "Sw" in data, f"Missing 'Sw' in {key}"
            assert "kr1" in data, f"Missing 'kr1' in {key}"
            assert "kr2" in data, f"Missing 'kr2' in {key}"
            assert len(data["Sw"]) == 9, f"Expected 9 saturations in {key}"
            assert len(data["kr1"]) == 9, f"Expected 9 kr1 values in {key}"
            assert len(data["kr2"]) == 9, f"Expected 9 kr2 values in {key}"

    def test_convergence_structure(self):
        results = load_results()
        conv = results["convergence"]
        assert "mesh_sizes" in conv
        assert "l2_errors" in conv
        assert "convergence_order" in conv

    def test_validation_structure(self):
        results = load_results()
        v = results["validation"]
        for key in ["finest_mesh_max_error", "kr1_numerical", "kr2_numerical",
                     "kr1_analytical", "kr2_analytical"]:
            assert key in v, f"Missing '{key}' in validation"


# ============================================================================
# Analytical Solution Tests
# ============================================================================

class TestEqualViscosity:
    """For mu_ratio=1, the analytical solution has a known closed form:
    kr1 = Sw^2 * (3 - 2*Sw)
    kr2 = (1 - Sw)^2 * (1 + 2*Sw)
    """

    def test_symmetric_case(self):
        """Sw=0.5, mu_ratio=1: kr1 = kr2 = 0.5."""
        results = load_results()
        data = get_kr_data(results, 1.0)
        idx = find_sw_index(data["Sw"], 0.5)
        assert abs(data["kr1"][idx] - 0.5) < 1e-6, \
            f"kr1 at Sw=0.5, mu_ratio=1 should be 0.5, got {data['kr1'][idx]}"
        assert abs(data["kr2"][idx] - 0.5) < 1e-6, \
            f"kr2 at Sw=0.5, mu_ratio=1 should be 0.5, got {data['kr2'][idx]}"

    def test_closed_form_kr1(self):
        """kr1 = Sw^2 * (3 - 2*Sw) for all saturations."""
        results = load_results()
        data = get_kr_data(results, 1.0)
        for sw, kr1 in zip(data["Sw"], data["kr1"]):
            expected = sw ** 2 * (3 - 2 * sw)
            assert abs(kr1 - expected) < 1e-5, \
                f"kr1 at Sw={sw}: expected {expected:.6f}, got {kr1:.6f}"

    def test_closed_form_kr2(self):
        """kr2 = (1-Sw)^2 * (1 + 2*Sw) for all saturations."""
        results = load_results()
        data = get_kr_data(results, 1.0)
        for sw, kr2 in zip(data["Sw"], data["kr2"]):
            expected = (1 - sw) ** 2 * (1 + 2 * sw)
            assert abs(kr2 - expected) < 1e-5, \
                f"kr2 at Sw={sw}: expected {expected:.6f}, got {kr2:.6f}"

    def test_sum_rule(self):
        """For equal viscosities, kr1 + kr2 = 1 for all Sw."""
        results = load_results()
        data = get_kr_data(results, 1.0)
        for sw, kr1, kr2 in zip(data["Sw"], data["kr1"], data["kr2"]):
            total = kr1 + kr2
            assert abs(total - 1.0) < 1e-5, \
                f"Sum rule violated at Sw={sw}: kr1+kr2={total}"


class TestUnequalViscosity:
    """Test specific analytical values for unequal viscosity ratios."""

    def test_mu10_sw05(self):
        """mu_ratio=10, Sw=0.5: kr1 = 17/88, kr2 = 71/88."""
        results = load_results()
        data = get_kr_data(results, 10.0)
        idx = find_sw_index(data["Sw"], 0.5)
        assert abs(data["kr1"][idx] - 17.0 / 88.0) < 1e-4, \
            f"kr1(Sw=0.5, mu_ratio=10) should be {17/88:.6f}, got {data['kr1'][idx]}"
        assert abs(data["kr2"][idx] - 71.0 / 88.0) < 1e-4, \
            f"kr2(Sw=0.5, mu_ratio=10) should be {71/88:.6f}, got {data['kr2'][idx]}"

    def test_mu2_sw05(self):
        """mu_ratio=2, Sw=0.5: kr1 = 3/8, kr2 = 5/8."""
        results = load_results()
        data = get_kr_data(results, 2.0)
        idx = find_sw_index(data["Sw"], 0.5)
        assert abs(data["kr1"][idx] - 3.0 / 8.0) < 1e-4, \
            f"kr1(Sw=0.5, mu_ratio=2) should be {3/8:.6f}, got {data['kr1'][idx]}"
        assert abs(data["kr2"][idx] - 5.0 / 8.0) < 1e-4, \
            f"kr2(Sw=0.5, mu_ratio=2) should be {5/8:.6f}, got {data['kr2'][idx]}"

    def test_mu5_sw05(self):
        """mu_ratio=5, Sw=0.5: kr1 = 1/4, kr2 = 3/4."""
        results = load_results()
        data = get_kr_data(results, 5.0)
        idx = find_sw_index(data["Sw"], 0.5)
        assert abs(data["kr1"][idx] - 0.25) < 1e-4, \
            f"kr1(Sw=0.5, mu_ratio=5) should be 0.25, got {data['kr1'][idx]}"
        assert abs(data["kr2"][idx] - 0.75) < 1e-4, \
            f"kr2(Sw=0.5, mu_ratio=5) should be 0.75, got {data['kr2'][idx]}"

    def test_mu20_sw05(self):
        """mu_ratio=20, Sw=0.5: kr1 = 9/56, kr2 = 47/56."""
        results = load_results()
        data = get_kr_data(results, 20.0)
        idx = find_sw_index(data["Sw"], 0.5)
        assert abs(data["kr1"][idx] - 9.0 / 56.0) < 1e-4, \
            f"kr1(Sw=0.5, mu_ratio=20) should be {9/56:.6f}, got {data['kr1'][idx]}"
        assert abs(data["kr2"][idx] - 47.0 / 56.0) < 1e-4, \
            f"kr2(Sw=0.5, mu_ratio=20) should be {47/56:.6f}, got {data['kr2'][idx]}"

    def test_sw05_sum_rule(self):
        """For Sw=0.5 at ANY viscosity ratio, kr1 + kr2 = 1."""
        results = load_results()
        for mu_ratio in EXPECTED_MU_RATIOS:
            data = get_kr_data(results, mu_ratio)
            idx = find_sw_index(data["Sw"], 0.5)
            total = data["kr1"][idx] + data["kr2"][idx]
            assert abs(total - 1.0) < 1e-4, \
                f"Sum rule at Sw=0.5, mu_ratio={mu_ratio}: kr1+kr2={total}"


# ============================================================================
# Physical Consistency Tests
# ============================================================================

class TestPhysicalConsistency:
    """Check physical correctness of relative permeability curves."""

    def test_kr_non_negative(self):
        """All relative permeabilities must be >= 0."""
        results = load_results()
        for key in results["analytical_kr"]:
            data = results["analytical_kr"][key]
            for i, (kr1, kr2) in enumerate(zip(data["kr1"], data["kr2"])):
                assert kr1 >= -1e-10, \
                    f"Negative kr1={kr1} at Sw={data['Sw'][i]} in {key}"
                assert kr2 >= -1e-10, \
                    f"Negative kr2={kr2} at Sw={data['Sw'][i]} in {key}"

    def test_kr1_monotonically_increasing(self):
        """kr1 must increase with wetting phase saturation Sw."""
        results = load_results()
        for key in results["analytical_kr"]:
            data = results["analytical_kr"][key]
            kr1 = data["kr1"]
            for i in range(len(kr1) - 1):
                assert kr1[i] <= kr1[i + 1] + 1e-10, \
                    f"kr1 not increasing at Sw={data['Sw'][i]}->{data['Sw'][i+1]} in {key}"

    def test_kr2_monotonically_decreasing(self):
        """kr2 must decrease with wetting phase saturation Sw."""
        results = load_results()
        for key in results["analytical_kr"]:
            data = results["analytical_kr"][key]
            kr2 = data["kr2"]
            for i in range(len(kr2) - 1):
                assert kr2[i] >= kr2[i + 1] - 1e-10, \
                    f"kr2 not decreasing at Sw={data['Sw'][i]}->{data['Sw'][i+1]} in {key}"

    def test_higher_mu_ratio_reduces_kr1(self):
        """Higher mu2/mu1 should reduce kr1 at fixed Sw=0.5."""
        results = load_results()
        kr1_values = []
        for mu_ratio in EXPECTED_MU_RATIOS:
            data = get_kr_data(results, mu_ratio)
            idx = find_sw_index(data["Sw"], 0.5)
            kr1_values.append(data["kr1"][idx])
        for i in range(len(kr1_values) - 1):
            assert kr1_values[i] >= kr1_values[i + 1] - 1e-10, \
                f"kr1 should decrease with mu_ratio at Sw=0.5"

    def test_lubrication_effect(self):
        """For asymmetric saturation and high viscosity ratio, kr2 can exceed 1.
        At Sw=0.3 with mu_ratio=5, the less viscous phase 1 lubricates the flow,
        so kr2 > 1 (phase 2 flows faster than it would alone)."""
        results = load_results()
        data = get_kr_data(results, 5.0)
        idx = find_sw_index(data["Sw"], 0.3)
        assert data["kr2"][idx] > 1.0, \
            f"Expected kr2 > 1 at Sw=0.3, mu_ratio=5 (lubrication effect), got {data['kr2'][idx]}"


# ============================================================================
# Convergence Tests
# ============================================================================

class TestConvergence:
    """Test mesh convergence of the numerical solver."""

    def test_convergence_order(self):
        """Convergence order should be approximately 2."""
        results = load_results()
        order = results["convergence"]["convergence_order"]
        assert 1.5 <= order <= 2.5, \
            f"Convergence order should be ~2.0, got {order}"

    def test_errors_decrease(self):
        """L2 errors must decrease with mesh refinement."""
        results = load_results()
        errors = results["convergence"]["l2_errors"]
        assert len(errors) >= 3, "Need at least 3 mesh levels"
        for i in range(len(errors) - 1):
            assert errors[i] > errors[i + 1], \
                f"Error not decreasing: e[{i}]={errors[i]} <= e[{i+1}]={errors[i+1]}"

    def test_finest_mesh_accuracy(self):
        """Finest mesh L2 error should be small."""
        results = load_results()
        errors = results["convergence"]["l2_errors"]
        assert errors[-1] < 1e-3, \
            f"Finest mesh L2 error {errors[-1]} exceeds 1e-3 threshold"

    def test_error_reduction_ratio(self):
        """The geometric mean of refinement ratios should indicate ~2nd order."""
        results = load_results()
        errors = results["convergence"]["l2_errors"]
        ratios = [errors[i] / errors[i + 1] for i in range(len(errors) - 1)]
        geo_mean = 1.0
        for r in ratios:
            geo_mean *= r
        geo_mean = geo_mean ** (1.0 / len(ratios))
        assert geo_mean > 2.5, \
            f"Geometric mean of error ratios {geo_mean:.2f} too small (expected ~4)"


# ============================================================================
# Validation Tests
# ============================================================================

class TestValidation:
    """Test agreement between numerical and analytical solutions."""

    def test_kr1_agreement(self):
        """Numerical kr1 should match analytical within tolerance."""
        results = load_results()
        v = results["validation"]
        diff = abs(v["kr1_numerical"] - v["kr1_analytical"])
        assert diff < 5e-3, \
            f"kr1 mismatch: numerical={v['kr1_numerical']:.6f}, " \
            f"analytical={v['kr1_analytical']:.6f}, diff={diff:.2e}"

    def test_kr2_agreement(self):
        """Numerical kr2 should match analytical within tolerance."""
        results = load_results()
        v = results["validation"]
        diff = abs(v["kr2_numerical"] - v["kr2_analytical"])
        assert diff < 5e-3, \
            f"kr2 mismatch: numerical={v['kr2_numerical']:.6f}, " \
            f"analytical={v['kr2_analytical']:.6f}, diff={diff:.2e}"

    def test_analytical_kr_values_match_expected(self):
        """Validation analytical kr values should match the convergence study
        params (Sw=0.3, mu_ratio=5): kr1 = 621/5500, kr2 = 7399/5500."""
        results = load_results()
        v = results["validation"]
        assert abs(v["kr1_analytical"] - 621.0 / 5500.0) < 1e-4, \
            f"Analytical kr1 should be {621/5500:.6f}, got {v['kr1_analytical']}"
        assert abs(v["kr2_analytical"] - 7399.0 / 5500.0) < 1e-4, \
            f"Analytical kr2 should be {7399/5500:.6f}, got {v['kr2_analytical']}"

    def test_finest_mesh_max_error_small(self):
        """Max pointwise error at finest mesh should be small."""
        results = load_results()
        v = results["validation"]
        assert v["finest_mesh_max_error"] < 1e-3, \
            f"Finest mesh max error {v['finest_mesh_max_error']} too large"
