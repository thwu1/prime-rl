"""
Tests for the quantum error mitigation system.

Verifies both execution paths:
1. Benchmarking pipeline (report.json) — correctness of scenario extraction,
   extrapolation methods, shot allocation, and post-processing.
2. ZNE optimization analysis (results.json) — correctness of zne_optimizer
   function implementations including Lagrange coefficients, Richardson
   extrapolation, optimal allocation, variance formulas, exponential
   extrapolation, and optimal scale factor selection.
"""


import json
import math
import os
import sys

import pytest

sys.path.insert(0, "/app")


# ============================================================
# Pipeline Track: Scenario extraction tests (SQL layer)
# ============================================================

class TestScenarioExtraction:
    """Verify scenarios.json is correctly extracted from calibration.db."""

    def _load_scenarios(self):
        with open("/app/scenarios.json") as f:
            return json.load(f)

    def test_all_scenarios_extracted(self):
        scenarios = self._load_scenarios()
        ids = {s["id"] for s in scenarios}
        assert ids == {"S1", "S2", "S3", "S4", "S5", "S6"}

    def test_s1_zero_asymptote(self):
        scenarios = self._load_scenarios()
        s1 = next(s for s in scenarios if s["id"] == "S1")
        assert s1["asymptote"] == pytest.approx(0.0, abs=1e-10), \
            f"S1 asymptote should be 0.0, got {s1['asymptote']}"

    def test_s3_nonzero_asymptote(self):
        scenarios = self._load_scenarios()
        s3 = next(s for s in scenarios if s["id"] == "S3")
        assert s3["asymptote"] == pytest.approx(0.15, abs=1e-10), \
            f"S3 asymptote should be 0.15, got {s3['asymptote']}"

    def test_s4_zero_asymptote(self):
        scenarios = self._load_scenarios()
        s4 = next(s for s in scenarios if s["id"] == "S4")
        assert s4["asymptote"] == pytest.approx(0.0, abs=1e-10), \
            f"S4 asymptote should be 0.0, got {s4['asymptote']}"


# ============================================================
# Pipeline Track: Lagrange coefficient tests (extrapolators.py)
# ============================================================

class TestLagrangeCoefficients:
    def test_three_factors(self):
        from extrapolators import compute_lagrange_coefficients
        coeffs = compute_lagrange_coefficients([1, 2, 3])
        assert coeffs == pytest.approx([3.0, -3.0, 1.0], abs=1e-10)

    def test_four_factors_sparse(self):
        from extrapolators import compute_lagrange_coefficients
        coeffs = compute_lagrange_coefficients([1, 3, 5, 7])
        assert coeffs == pytest.approx(
            [2.1875, -2.1875, 1.3125, -0.3125], abs=1e-10
        )

    def test_five_factors(self):
        from extrapolators import compute_lagrange_coefficients
        coeffs = compute_lagrange_coefficients([1, 2, 3, 4, 5])
        assert coeffs == pytest.approx([5.0, -10.0, 10.0, -5.0, 1.0], abs=1e-10)

    def test_coefficients_sum_to_one(self):
        from extrapolators import compute_lagrange_coefficients
        for sf in [[1, 2, 3], [1, 3, 5], [1, 2, 3, 5], [1, 3, 5, 7], [1, 2, 3, 4, 5]]:
            coeffs = compute_lagrange_coefficients(sf)
            assert sum(coeffs) == pytest.approx(1.0, abs=1e-10), (
                f"Coefficients for {sf} sum to {sum(coeffs)}, expected 1.0"
            )

    def test_gamma_norm_three(self):
        from extrapolators import compute_lagrange_coefficients
        coeffs = compute_lagrange_coefficients([1, 2, 3])
        gamma = sum(abs(c) for c in coeffs)
        assert gamma == pytest.approx(7.0, abs=1e-10)

    def test_gamma_norm_four(self):
        from extrapolators import compute_lagrange_coefficients
        coeffs = compute_lagrange_coefficients([1, 3, 5, 7])
        gamma = sum(abs(c) for c in coeffs)
        assert gamma == pytest.approx(6.0, abs=1e-10)


# ============================================================
# Pipeline Track: Richardson extrapolation tests
# ============================================================

class TestRichardsonExtrapolation:
    def test_exact_for_quadratic(self):
        from extrapolators import richardson_extrapolate
        sf = [1, 2, 3]
        vals = [2 - 1 + 0.5, 2 - 2 + 2.0, 2 - 3 + 4.5]
        result = richardson_extrapolate(sf, vals)
        assert result == pytest.approx(2.0, abs=1e-10)

    def test_exact_for_linear(self):
        from extrapolators import richardson_extrapolate
        sf = [1, 3]
        vals = [2.5, 1.5]
        result = richardson_extrapolate(sf, vals)
        assert result == pytest.approx(3.0, abs=1e-10)

    def test_polynomial_noise_exact(self):
        from extrapolators import richardson_extrapolate
        sf = [1, 2, 3]
        vals = [
            0.8 - 0.05 * 1 - 0.01 * 1,
            0.8 - 0.05 * 2 - 0.01 * 4,
            0.8 - 0.05 * 3 - 0.01 * 9,
        ]
        result = richardson_extrapolate(sf, vals)
        assert result == pytest.approx(0.8, abs=1e-10)


# ============================================================
# Pipeline Track: Exponential extrapolation tests
# ============================================================

class TestExponentialExtrapolation:
    def test_pure_exponential_positive(self):
        from extrapolators import exponential_extrapolate
        from noise_model import exponential_decay
        sf = [1, 2, 3]
        vals = [exponential_decay(0.9, s, 0.15) for s in sf]
        result = exponential_extrapolate(sf, vals, asymptote=0.0)
        assert result == pytest.approx(0.9, abs=1e-6)

    def test_negative_values(self):
        from extrapolators import exponential_extrapolate
        from noise_model import exponential_decay
        sf = [1, 3, 5]
        vals = [exponential_decay(-0.6, s, 0.2) for s in sf]
        result = exponential_extrapolate(sf, vals, asymptote=0.0)
        assert result == pytest.approx(-0.6, abs=1e-6)

    def test_with_nonzero_asymptote(self):
        from extrapolators import exponential_extrapolate
        from noise_model import exponential_decay
        sf = [1, 2, 3, 5]
        vals = [exponential_decay(0.7, s, 0.1, asymptote=0.15) for s in sf]
        result = exponential_extrapolate(sf, vals, asymptote=0.15)
        assert result == pytest.approx(0.7, abs=1e-6)


# ============================================================
# Pipeline Track: Shot allocation tests (allocator.py)
# ============================================================

class TestShotAllocation:
    def test_sum_equals_budget(self):
        from allocator import optimal_allocation
        for coeffs, budget in [
            ([3.0, -3.0, 1.0], 10000),
            ([2.1875, -2.1875, 1.3125, -0.3125], 20000),
            ([5.0, -10.0, 10.0, -5.0, 1.0], 25000),
        ]:
            alloc = optimal_allocation(coeffs, budget)
            assert sum(alloc) == budget, (
                f"Allocation sums to {sum(alloc)}, expected {budget}"
            )

    def test_proportional_to_abs_gamma(self):
        from allocator import optimal_allocation
        coeffs = [3.0, -3.0, 1.0]
        budget = 1000000
        alloc = optimal_allocation(coeffs, budget)
        total = sum(alloc)
        ratios = [a / total for a in alloc]
        assert ratios[0] == pytest.approx(3.0 / 7.0, rel=0.001)
        assert ratios[1] == pytest.approx(3.0 / 7.0, rel=0.001)
        assert ratios[2] == pytest.approx(1.0 / 7.0, rel=0.001)

    def test_symmetric_coefficients_equal(self):
        from allocator import optimal_allocation
        coeffs = [3.0, -3.0, 1.0]
        alloc = optimal_allocation(coeffs, 10000)
        assert abs(alloc[0] - alloc[1]) <= 1


# ============================================================
# Pipeline Track: Variance tests (allocator.py)
# ============================================================

class TestVariance:
    def test_uniform_three_factors(self):
        from allocator import variance_uniform
        var = variance_uniform([3.0, -3.0, 1.0], 10000)
        assert var == pytest.approx(0.0057, abs=1e-8)

    def test_optimal_three_factors(self):
        from allocator import variance_optimal
        var = variance_optimal([3.0, -3.0, 1.0], 10000)
        assert var == pytest.approx(0.0049, abs=1e-8)

    def test_optimal_leq_uniform(self):
        from allocator import variance_uniform, variance_optimal
        for coeffs in [
            [3.0, -3.0, 1.0],
            [2.1875, -2.1875, 1.3125, -0.3125],
            [5.0, -10.0, 10.0, -5.0, 1.0],
        ]:
            var_u = variance_uniform(coeffs, 10000)
            var_o = variance_optimal(coeffs, 10000)
            assert var_o <= var_u + 1e-15, (
                f"Optimal variance {var_o} > uniform variance {var_u}"
            )


# ============================================================
# Pipeline Track: Report correctness (end-to-end)
# ============================================================

def _get_report():
    with open("/app/report.json") as f:
        return json.load(f)


class TestReport:
    def test_report_exists(self):
        assert os.path.exists("/app/report.json"), (
            "report.json not found at /app/report.json"
        )

    def test_all_scenarios_present(self):
        report = _get_report()
        for sid in ["S1", "S2", "S3", "S4", "S5", "S6"]:
            assert sid in report, f"Missing scenario {sid} in report"

    def test_lagrange_S1(self):
        report = _get_report()
        assert report["S1"]["lagrange_coefficients"] == pytest.approx(
            [3.0, -3.0, 1.0], abs=1e-6
        )

    def test_gamma_norm_S4(self):
        report = _get_report()
        assert report["S4"]["gamma_norm"] == pytest.approx(6.0, abs=1e-6)

    def test_gamma_norm_S6(self):
        report = _get_report()
        assert report["S6"]["gamma_norm"] == pytest.approx(31.0, abs=1e-6)

    def test_exponential_exact_S1(self):
        report = _get_report()
        assert report["S1"]["exponential"]["error"] < 1e-5

    def test_exponential_exact_S2_negative(self):
        report = _get_report()
        assert report["S2"]["exponential"]["error"] < 1e-5

    def test_exponential_exact_S3_asymptote(self):
        report = _get_report()
        assert report["S3"]["exponential"]["error"] < 1e-5

    def test_richardson_exact_S5(self):
        report = _get_report()
        assert report["S5"]["richardson"]["error"] < 1e-10

    def test_best_method_has_lowest_error(self):
        report = _get_report()
        for sid in report:
            s = report[sid]
            errors = {
                "richardson": s["richardson"]["error"],
                "exponential": s["exponential"]["error"],
                "linear": s["linear"]["error"],
            }
            actual_best = min(errors, key=errors.get)
            assert s["best_method"] == actual_best, (
                f"Scenario {sid}: best_method={s['best_method']} but "
                f"{actual_best} has error {errors[actual_best]:.2e} vs "
                f"{errors[s['best_method']]:.2e}"
            )

    def test_best_method_S5_is_richardson(self):
        report = _get_report()
        assert report["S5"]["best_method"] == "richardson"

    def test_allocation_sums_to_budget(self):
        report = _get_report()
        for sid in report:
            alloc = report[sid]["allocation"]
            assert sum(alloc["optimal"]) == alloc["shot_budget"], (
                f"Scenario {sid}: allocation sums to {sum(alloc['optimal'])}, "
                f"expected {alloc['shot_budget']}"
            )

    def test_improvement_ratio_geq_one(self):
        report = _get_report()
        for sid in report:
            ratio = report[sid]["allocation"]["improvement_ratio"]
            assert ratio >= 1.0 - 1e-10, (
                f"Scenario {sid}: improvement_ratio={ratio} < 1"
            )


# ============================================================
# Analysis Track: generate_measurements (noise_model.py)
# ============================================================

class TestGenerateMeasurements:
    def test_function_exists(self):
        from noise_model import generate_measurements
        assert callable(generate_measurements)

    def test_correct_exponential_values(self):
        from noise_model import generate_measurements, exponential_decay
        sf = [1, 2, 3]
        measurements = generate_measurements(0.8, sf, 0.1, 0.0)
        expected = [exponential_decay(0.8, s, 0.1, 0.0) for s in sf]
        assert measurements == pytest.approx(expected, abs=1e-12)

    def test_with_asymptote(self):
        from noise_model import generate_measurements, exponential_decay
        sf = [1, 2, 3, 5]
        measurements = generate_measurements(0.6, sf, 0.15, 0.1)
        expected = [exponential_decay(0.6, s, 0.15, 0.1) for s in sf]
        assert measurements == pytest.approx(expected, abs=1e-12)

    def test_negative_ideal(self):
        from noise_model import generate_measurements, exponential_decay
        sf = [1, 3, 5]
        measurements = generate_measurements(-0.5, sf, 0.2, 0.0)
        expected = [exponential_decay(-0.5, s, 0.2, 0.0) for s in sf]
        assert measurements == pytest.approx(expected, abs=1e-12)


# ============================================================
# Analysis Track: zne_optimizer Lagrange coefficients
# ============================================================

class TestZneOptLagrange:
    def test_three_factors(self):
        from zne_optimizer import compute_lagrange_coefficients
        coeffs = compute_lagrange_coefficients([1, 2, 3])
        assert coeffs == pytest.approx([3.0, -3.0, 1.0], abs=1e-10)

    def test_three_factors_sparse(self):
        from zne_optimizer import compute_lagrange_coefficients
        coeffs = compute_lagrange_coefficients([1, 3, 5])
        assert coeffs == pytest.approx([1.875, -1.25, 0.375], abs=1e-10)

    def test_four_factors(self):
        from zne_optimizer import compute_lagrange_coefficients
        coeffs = compute_lagrange_coefficients([1, 3, 5, 7])
        assert coeffs == pytest.approx(
            [2.1875, -2.1875, 1.3125, -0.3125], abs=1e-10
        )

    def test_five_factors(self):
        from zne_optimizer import compute_lagrange_coefficients
        coeffs = compute_lagrange_coefficients([1, 2, 3, 4, 5])
        assert coeffs == pytest.approx([5.0, -10.0, 10.0, -5.0, 1.0], abs=1e-10)

    def test_four_factors_irregular(self):
        from zne_optimizer import compute_lagrange_coefficients
        coeffs = compute_lagrange_coefficients([1, 2, 3, 5])
        assert coeffs == pytest.approx([3.75, -5.0, 2.5, -0.25], abs=1e-10)

    def test_sum_to_one(self):
        from zne_optimizer import compute_lagrange_coefficients
        for sf in [[1, 2, 3], [1, 3, 5], [1, 2, 3, 5], [1, 3, 5, 7], [1, 2, 3, 4, 5]]:
            coeffs = compute_lagrange_coefficients(sf)
            assert sum(coeffs) == pytest.approx(1.0, abs=1e-10), (
                f"Coefficients for {sf} sum to {sum(coeffs)}, expected 1.0"
            )

    def test_gamma_norm_three(self):
        from zne_optimizer import compute_lagrange_coefficients
        coeffs = compute_lagrange_coefficients([1, 2, 3])
        gamma = sum(abs(c) for c in coeffs)
        assert gamma == pytest.approx(7.0, abs=1e-10)

    def test_gamma_norm_five(self):
        from zne_optimizer import compute_lagrange_coefficients
        coeffs = compute_lagrange_coefficients([1, 2, 3, 4, 5])
        gamma = sum(abs(c) for c in coeffs)
        assert gamma == pytest.approx(31.0, abs=1e-10)


# ============================================================
# Analysis Track: zne_optimizer Richardson extrapolation
# ============================================================

class TestZneOptRichardson:
    def test_exact_for_quadratic(self):
        from zne_optimizer import richardson_extrapolate
        sf = [1, 2, 3]
        vals = [2 - 1 + 0.5, 2 - 2 + 2.0, 2 - 3 + 4.5]
        result = richardson_extrapolate(sf, vals)
        assert result == pytest.approx(2.0, abs=1e-10)

    def test_exact_for_cubic_with_four_points(self):
        from zne_optimizer import richardson_extrapolate
        sf = [1, 2, 3, 5]
        # f(x) = 1.0 - 0.1*x + 0.02*x^2 - 0.001*x^3, ideal f(0) = 1.0
        vals = [1.0 - 0.1*s + 0.02*s**2 - 0.001*s**3 for s in sf]
        result = richardson_extrapolate(sf, vals)
        assert result == pytest.approx(1.0, abs=1e-10)


# ============================================================
# Analysis Track: zne_optimizer shot allocation
# ============================================================

class TestZneOptAllocation:
    def test_sum_equals_budget_three(self):
        from zne_optimizer import optimal_shot_allocation
        alloc = optimal_shot_allocation([1, 2, 3], 10000)
        assert sum(alloc) == 10000

    def test_sum_equals_budget_four(self):
        from zne_optimizer import optimal_shot_allocation
        alloc = optimal_shot_allocation([1, 3, 5, 7], 21000)
        assert sum(alloc) == 21000

    def test_sum_equals_budget_five(self):
        from zne_optimizer import optimal_shot_allocation
        alloc = optimal_shot_allocation([1, 2, 3, 4, 5], 25000)
        assert sum(alloc) == 25000

    def test_proportional_three(self):
        """With large budget, allocation proportional to |gamma_j|."""
        from zne_optimizer import optimal_shot_allocation
        alloc = optimal_shot_allocation([1, 2, 3], 1000000)
        total = sum(alloc)
        # [1,2,3] -> coeffs [3,-3,1], |gamma| = [3,3,1], Gamma=7
        assert alloc[0] / total == pytest.approx(3.0 / 7.0, rel=0.001)
        assert alloc[1] / total == pytest.approx(3.0 / 7.0, rel=0.001)
        assert alloc[2] / total == pytest.approx(1.0 / 7.0, rel=0.001)

    def test_symmetric_equal(self):
        """For |gamma_0| == |gamma_1|, allocations within 1 shot."""
        from zne_optimizer import optimal_shot_allocation
        alloc = optimal_shot_allocation([1, 2, 3], 10000)
        assert abs(alloc[0] - alloc[1]) <= 1


# ============================================================
# Analysis Track: zne_optimizer variance formulas
# ============================================================

class TestZneOptVariance:
    def test_uniform_three(self):
        from zne_optimizer import richardson_variance_uniform
        # [1,2,3] -> coeffs [3,-3,1], n=3, sum(c^2)=19
        var = richardson_variance_uniform([1, 2, 3], 10000)
        assert var == pytest.approx(0.0057, abs=1e-8)

    def test_optimal_three(self):
        from zne_optimizer import richardson_variance_optimal
        # [1,2,3] -> Gamma=7, var = 49/10000
        var = richardson_variance_optimal([1, 2, 3], 10000)
        assert var == pytest.approx(0.0049, abs=1e-8)

    def test_uniform_four(self):
        from zne_optimizer import richardson_variance_uniform
        # [1,3,5,7] -> coeffs [2.1875,-2.1875,1.3125,-0.3125]
        # sum(c^2) = 4.78515625 + 4.78515625 + 1.72265625 + 0.09765625 = 11.390625
        # var = 4/21000 * 11.390625
        var = richardson_variance_uniform([1, 3, 5, 7], 21000)
        expected = (4.0 / 21000) * (2.1875**2 + 2.1875**2 + 1.3125**2 + 0.3125**2)
        assert var == pytest.approx(expected, abs=1e-10)

    def test_optimal_four(self):
        from zne_optimizer import richardson_variance_optimal
        # [1,3,5,7] -> Gamma=6, var = 36/21000
        var = richardson_variance_optimal([1, 3, 5, 7], 21000)
        assert var == pytest.approx(36.0 / 21000, abs=1e-10)

    def test_optimal_leq_uniform(self):
        """Cauchy-Schwarz: optimal variance <= uniform variance."""
        from zne_optimizer import richardson_variance_uniform, richardson_variance_optimal
        for sf in [[1, 2, 3], [1, 3, 5, 7], [1, 2, 3, 4, 5]]:
            var_u = richardson_variance_uniform(sf, 10000)
            var_o = richardson_variance_optimal(sf, 10000)
            assert var_o <= var_u + 1e-15, (
                f"Optimal {var_o} > uniform {var_u} for scale factors {sf}"
            )


# ============================================================
# Analysis Track: zne_optimizer exponential extrapolation
# ============================================================

class TestZneOptExponential:
    def test_pure_exp_positive(self):
        from zne_optimizer import exponential_extrapolate
        from noise_model import exponential_decay
        sf = [1, 2, 3]
        vals = [exponential_decay(0.9, s, 0.15) for s in sf]
        result = exponential_extrapolate(sf, vals, asymptote=0.0)
        assert result == pytest.approx(0.9, abs=1e-6)

    def test_negative_ideal(self):
        from zne_optimizer import exponential_extrapolate
        from noise_model import exponential_decay
        sf = [1, 3, 5]
        vals = [exponential_decay(-0.5, s, 0.2) for s in sf]
        result = exponential_extrapolate(sf, vals, asymptote=0.0)
        assert result == pytest.approx(-0.5, abs=1e-6)

    def test_with_asymptote(self):
        from zne_optimizer import exponential_extrapolate
        from noise_model import exponential_decay
        sf = [1, 2, 3, 5]
        vals = [exponential_decay(0.6, s, 0.15, asymptote=0.1) for s in sf]
        result = exponential_extrapolate(sf, vals, asymptote=0.1)
        assert result == pytest.approx(0.6, abs=1e-6)


# ============================================================
# Analysis Track: zne_optimizer optimal scale factor selection
# ============================================================

class TestZneOptScaleFactors:
    def test_o1_best_factors(self):
        from zne_optimizer import find_optimal_scale_factors
        factors, gamma = find_optimal_scale_factors([1, 2, 3, 4, 5, 6, 7], 3)
        assert sorted(factors) == [1, 4, 7], (
            f"O1: expected [1,4,7] but got {sorted(factors)}"
        )

    def test_o1_gamma_norm(self):
        from zne_optimizer import find_optimal_scale_factors
        factors, gamma = find_optimal_scale_factors([1, 2, 3, 4, 5, 6, 7], 3)
        # [1,4,7]: Gamma = 14/9 + 7/9 + 2/9 = 23/9
        assert gamma == pytest.approx(23.0 / 9.0, abs=1e-6)

    def test_o2_best_factors(self):
        from zne_optimizer import find_optimal_scale_factors
        factors, gamma = find_optimal_scale_factors(
            [1, 2, 3, 4, 5, 6, 7, 8, 9], 3
        )
        assert sorted(factors) == [1, 5, 9], (
            f"O2: expected [1,5,9] but got {sorted(factors)}"
        )

    def test_o2_gamma_norm(self):
        from zne_optimizer import find_optimal_scale_factors
        factors, gamma = find_optimal_scale_factors(
            [1, 2, 3, 4, 5, 6, 7, 8, 9], 3
        )
        # [1,5,9]: Gamma = 45/32 + 9/16 + 5/32 = 68/32 = 17/8
        assert gamma == pytest.approx(17.0 / 8.0, abs=1e-6)

    def test_returns_sorted(self):
        from zne_optimizer import find_optimal_scale_factors
        factors, _ = find_optimal_scale_factors([7, 3, 5, 1, 4, 6, 2], 3)
        assert factors == sorted(factors)


# ============================================================
# Analysis Track: results.json end-to-end
# ============================================================

def _get_results():
    with open("/app/results.json") as f:
        return json.load(f)


class TestResults:
    def test_results_exists(self):
        assert os.path.exists("/app/results.json"), (
            "results.json not found at /app/results.json"
        )

    def test_lagrange_sections_present(self):
        results = _get_results()
        for lid in ["L1", "L2", "L3", "L4", "L5"]:
            assert lid in results["lagrange"], f"Missing {lid} in lagrange results"

    def test_lagrange_L1_coefficients(self):
        results = _get_results()
        coeffs = results["lagrange"]["L1"]["coefficients"]
        assert coeffs == pytest.approx([3.0, -3.0, 1.0], abs=1e-6)

    def test_lagrange_L4_gamma_norm(self):
        results = _get_results()
        gamma = results["lagrange"]["L4"]["gamma_norm"]
        assert gamma == pytest.approx(6.0, abs=1e-6)

    def test_lagrange_L5_gamma_norm(self):
        results = _get_results()
        gamma = results["lagrange"]["L5"]["gamma_norm"]
        assert gamma == pytest.approx(31.0, abs=1e-6)

    def test_allocation_A1_sum(self):
        results = _get_results()
        alloc = results["allocation"]["A1"]["allocation"]
        assert sum(alloc) == 10000

    def test_allocation_A2_sum(self):
        results = _get_results()
        alloc = results["allocation"]["A2"]["allocation"]
        assert sum(alloc) == 21000

    def test_allocation_improvement_ratios(self):
        results = _get_results()
        for aid in ["A1", "A2", "A3", "A4"]:
            ratio = results["allocation"][aid]["improvement_ratio"]
            assert ratio >= 1.0 - 1e-10, (
                f"{aid}: improvement_ratio={ratio} < 1"
            )

    def test_extrapolation_E1_exp_accuracy(self):
        results = _get_results()
        err = results["extrapolation"]["E1"]["exponential_error"]
        assert err < 1e-5, f"E1 exponential error {err} >= 1e-5"

    def test_extrapolation_E2_exp_accuracy(self):
        results = _get_results()
        err = results["extrapolation"]["E2"]["exponential_error"]
        assert err < 1e-5, f"E2 exponential error {err} >= 1e-5"

    def test_extrapolation_E3_exp_accuracy(self):
        results = _get_results()
        err = results["extrapolation"]["E3"]["exponential_error"]
        assert err < 1e-5, f"E3 exponential error {err} >= 1e-5"

    def test_optimization_O1_factors(self):
        results = _get_results()
        factors = results["optimization"]["O1"]["best_factors"]
        assert sorted(factors) == [1, 4, 7], (
            f"O1: expected [1,4,7] but got {sorted(factors)}"
        )

    def test_optimization_O2_factors(self):
        results = _get_results()
        factors = results["optimization"]["O2"]["best_factors"]
        assert sorted(factors) == [1, 5, 9], (
            f"O2: expected [1,5,9] but got {sorted(factors)}"
        )

    def test_optimization_O1_gamma(self):
        results = _get_results()
        gamma = results["optimization"]["O1"]["best_gamma_norm"]
        assert gamma == pytest.approx(23.0 / 9.0, abs=1e-6)

    def test_optimization_O2_gamma(self):
        results = _get_results()
        gamma = results["optimization"]["O2"]["best_gamma_norm"]
        assert gamma == pytest.approx(17.0 / 8.0, abs=1e-6)
