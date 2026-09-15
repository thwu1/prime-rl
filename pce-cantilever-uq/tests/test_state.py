
import pytest
import json
import math
import subprocess
import shutil
import numpy as np
from scipy.stats import norm


@pytest.fixture(scope="module")
def results():
    with open("/app/results.json") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def stress_analytical():
    """Compute exact analytical values for stress (linear in X, Y)."""
    w, t = 2.5, 3.5
    c_Y = 600.0 / (w * t ** 2)
    c_X = 600.0 / (w ** 2 * t)
    mu_X, mu_Y = 500.0, 1000.0
    sigma_X, sigma_Y = 100.0, 100.0
    mean = c_Y * mu_Y + c_X * mu_X
    var = c_Y ** 2 * sigma_Y ** 2 + c_X ** 2 * sigma_X ** 2
    std = math.sqrt(var)
    S_X = c_X ** 2 * sigma_X ** 2 / var
    S_Y = c_Y ** 2 * sigma_Y ** 2 / var
    return {
        "mean": mean, "std": std, "var": var,
        "S_X": S_X, "S_Y": S_Y,
        "c_X": c_X, "c_Y": c_Y,
    }


@pytest.fixture(scope="module")
def displacement_mc():
    """Compute Monte Carlo reference values for displacement."""
    np.random.seed(42)
    N = 500000
    w, t, L, D0 = 2.5, 3.5, 100.0, 2.2535
    E_s = np.random.normal(29e6, 1.45e6, N)
    X_s = np.random.normal(500, 100, N)
    Y_s = np.random.normal(1000, 100, N)
    D1 = 4.0 * L ** 3 / (E_s * w * t)
    D2 = (Y_s / t ** 2) ** 2 + (X_s / w ** 2) ** 2
    disp = D1 * np.sqrt(D2) / D0
    return {
        "mean": float(np.mean(disp)),
        "std": float(np.std(disp, ddof=0)),
        "pf": float(np.mean(disp > 1.0)),
    }


class TestResultsStructure:
    def test_has_stress_mean(self, results):
        assert "stress_mean" in results
        assert isinstance(results["stress_mean"], (int, float))

    def test_has_stress_std(self, results):
        assert "stress_std" in results
        assert isinstance(results["stress_std"], (int, float))

    def test_has_displacement_mean(self, results):
        assert "displacement_mean" in results
        assert isinstance(results["displacement_mean"], (int, float))

    def test_has_displacement_std(self, results):
        assert "displacement_std" in results
        assert isinstance(results["displacement_std"], (int, float))

    def test_has_sobol_first_order(self, results):
        s = results["sobol_first_order"]
        for resp in ["stress", "displacement"]:
            assert resp in s
            for var in ["R", "E", "X", "Y"]:
                assert var in s[resp]

    def test_has_sobol_total(self, results):
        s = results["sobol_total"]
        for resp in ["stress", "displacement"]:
            assert resp in s
            for var in ["R", "E", "X", "Y"]:
                assert var in s[resp]

    def test_has_failure_stress(self, results):
        f = results["failure_stress"]
        assert "probability" in f
        assert "reliability_index" in f

    def test_has_failure_displacement(self, results):
        f = results["failure_displacement"]
        assert "probability" in f
        assert "reliability_index" in f


class TestStressExact:
    """Stress is linear in X, Y and independent of R, E.
    PCE should recover exact values regardless of quadrature method."""

    def test_stress_mean(self, results, stress_analytical):
        expected = stress_analytical["mean"]
        actual = results["stress_mean"]
        assert abs(actual - expected) / abs(expected) < 1e-4, (
            f"stress_mean: expected {expected:.6f}, got {actual:.6f}"
        )

    def test_stress_std(self, results, stress_analytical):
        expected = stress_analytical["std"]
        actual = results["stress_std"]
        assert abs(actual - expected) / abs(expected) < 1e-4, (
            f"stress_std: expected {expected:.6f}, got {actual:.6f}"
        )

    def test_stress_mean_positive(self, results):
        assert results["stress_mean"] > 0

    def test_stress_std_positive(self, results):
        assert results["stress_std"] > 0


class TestStressSobol:
    """Sobol indices for stress: only X, Y contribute (linear function)."""

    def test_sobol_S_R_zero(self, results):
        actual = results["sobol_first_order"]["stress"]["R"]
        assert abs(actual) < 0.01, f"S_R for stress should be ~0, got {actual}"

    def test_sobol_S_E_zero(self, results):
        actual = results["sobol_first_order"]["stress"]["E"]
        assert abs(actual) < 0.01, f"S_E for stress should be ~0, got {actual}"

    def test_sobol_S_X(self, results, stress_analytical):
        expected = stress_analytical["S_X"]
        actual = results["sobol_first_order"]["stress"]["X"]
        assert abs(actual - expected) < 0.01, (
            f"S_X for stress: expected {expected:.4f}, got {actual:.4f}"
        )

    def test_sobol_S_Y(self, results, stress_analytical):
        expected = stress_analytical["S_Y"]
        actual = results["sobol_first_order"]["stress"]["Y"]
        assert abs(actual - expected) < 0.01, (
            f"S_Y for stress: expected {expected:.4f}, got {actual:.4f}"
        )

    def test_sobol_first_order_sum(self, results):
        """For linear stress, first-order indices should sum to 1."""
        s = results["sobol_first_order"]["stress"]
        total = sum(s[v] for v in ["R", "E", "X", "Y"])
        assert abs(total - 1.0) < 0.02, f"Sum of S1 = {total}, expected ~1.0"

    def test_sobol_total_S_R_zero(self, results):
        actual = results["sobol_total"]["stress"]["R"]
        assert abs(actual) < 0.01

    def test_sobol_total_S_E_zero(self, results):
        actual = results["sobol_total"]["stress"]["E"]
        assert abs(actual) < 0.01

    def test_total_equals_first_for_linear(self, results):
        """For a linear function, total Sobol = first-order Sobol."""
        for var in ["X", "Y"]:
            s1 = results["sobol_first_order"]["stress"][var]
            st = results["sobol_total"]["stress"][var]
            assert abs(s1 - st) < 0.01, (
                f"For linear stress, S1_{var}={s1:.4f} should equal ST_{var}={st:.4f}"
            )


class TestDisplacementStats:
    """Displacement is nonlinear in E, X, Y. Check against MC reference."""

    def test_displacement_mean(self, results, displacement_mc):
        expected = displacement_mc["mean"]
        actual = results["displacement_mean"]
        assert abs(actual - expected) / abs(expected) < 0.02, (
            f"displacement_mean: MC ref={expected:.6f}, got {actual:.6f}"
        )

    def test_displacement_std(self, results, displacement_mc):
        expected = displacement_mc["std"]
        actual = results["displacement_std"]
        assert abs(actual - expected) / abs(expected) < 0.05, (
            f"displacement_std: MC ref={expected:.6f}, got {actual:.6f}"
        )

    def test_displacement_mean_positive(self, results):
        assert results["displacement_mean"] > 0

    def test_displacement_mean_less_than_one(self, results):
        """At the design point, displacement should be less than 1 on average."""
        assert results["displacement_mean"] < 1.0


class TestDisplacementSobol:
    """Displacement depends on E, X, Y but NOT R."""

    def test_sobol_S_R_zero(self, results):
        actual = results["sobol_first_order"]["displacement"]["R"]
        assert abs(actual) < 0.01, f"S_R for displacement should be ~0, got {actual}"

    def test_sobol_E_positive(self, results):
        actual = results["sobol_first_order"]["displacement"]["E"]
        assert actual > 0.01, f"S_E for displacement should be > 0, got {actual}"

    def test_sobol_X_positive(self, results):
        actual = results["sobol_first_order"]["displacement"]["X"]
        assert actual > 0.01, f"S_X for displacement should be > 0, got {actual}"

    def test_sobol_Y_positive(self, results):
        actual = results["sobol_first_order"]["displacement"]["Y"]
        assert actual > 0.01, f"S_Y for displacement should be > 0, got {actual}"

    def test_sobol_total_S_R_zero(self, results):
        actual = results["sobol_total"]["displacement"]["R"]
        assert abs(actual) < 0.01

    def test_sobol_total_sum_bounded(self, results):
        """Total Sobol indices can sum to > 1 due to interactions, but should be <= d."""
        s = results["sobol_total"]["displacement"]
        total = sum(s[v] for v in ["R", "E", "X", "Y"])
        assert 0.9 < total <= 4.0, f"Sum of ST = {total}"

    def test_total_geq_first_order(self, results):
        """Total Sobol index >= first-order for each variable."""
        for var in ["R", "E", "X", "Y"]:
            s1 = results["sobol_first_order"]["displacement"][var]
            st = results["sobol_total"]["displacement"][var]
            assert st >= s1 - 0.01, (
                f"ST_{var}={st:.4f} should be >= S1_{var}={s1:.4f}"
            )


class TestFailureStress:
    """Limit state g = stress - R is linear in normals, so exact analytical."""

    def test_failure_probability(self, results, stress_analytical):
        c_Y = stress_analytical["c_Y"]
        c_X = stress_analytical["c_X"]
        g_mean = c_Y * 1000 + c_X * 500 - 40000
        g_var = c_Y ** 2 * 100 ** 2 + c_X ** 2 * 100 ** 2 + 2000 ** 2
        g_std = math.sqrt(g_var)
        beta = -g_mean / g_std
        expected_pf = float(norm.cdf(-beta))
        actual = results["failure_stress"]["probability"]
        assert abs(actual - expected_pf) / expected_pf < 0.05, (
            f"P_f stress: expected {expected_pf:.6f}, got {actual:.6f}"
        )

    def test_reliability_index(self, results, stress_analytical):
        c_Y = stress_analytical["c_Y"]
        c_X = stress_analytical["c_X"]
        g_mean = c_Y * 1000 + c_X * 500 - 40000
        g_var = c_Y ** 2 * 100 ** 2 + c_X ** 2 * 100 ** 2 + 2000 ** 2
        g_std = math.sqrt(g_var)
        expected_beta = -g_mean / g_std
        actual = results["failure_stress"]["reliability_index"]
        assert abs(actual - expected_beta) / expected_beta < 0.02, (
            f"beta stress: expected {expected_beta:.4f}, got {actual:.4f}"
        )

    def test_reliability_index_positive(self, results):
        """Beta should be positive (mean stress < mean R, i.e., safe on average)."""
        assert results["failure_stress"]["reliability_index"] > 0

    def test_probability_bounded(self, results):
        pf = results["failure_stress"]["probability"]
        assert 0 < pf < 0.5, f"P_f stress = {pf}, expected in (0, 0.5)"


class TestFailureDisplacement:
    """Displacement failure: check internal consistency of FOSM approach."""

    def test_consistency_beta_pf(self, results):
        """P_f should equal Phi(-beta)."""
        beta = results["failure_displacement"]["reliability_index"]
        pf = results["failure_displacement"]["probability"]
        expected_pf = float(norm.cdf(-beta))
        assert abs(pf - expected_pf) / max(expected_pf, 1e-10) < 0.05, (
            f"P_f={pf:.6f} vs Phi(-beta)={expected_pf:.6f}"
        )

    def test_consistency_with_moments(self, results):
        """Beta should be consistent with displacement mean and std."""
        disp_mean = results["displacement_mean"]
        disp_std = results["displacement_std"]
        expected_beta = (1.0 - disp_mean) / disp_std
        actual_beta = results["failure_displacement"]["reliability_index"]
        assert abs(actual_beta - expected_beta) / abs(expected_beta) < 0.05, (
            f"beta_disp={actual_beta:.4f} vs (1-mu)/sigma={expected_beta:.4f}"
        )

    def test_reliability_index_positive(self, results):
        """Beta should be positive (displacement < 1 on average)."""
        assert results["failure_displacement"]["reliability_index"] > 0

    def test_probability_reasonable(self, results, displacement_mc):
        """Failure probability should be in a reasonable range."""
        pf = results["failure_displacement"]["probability"]
        mc_pf = displacement_mc["pf"]
        assert 0 < pf < 0.5, f"P_f displacement = {pf}"
        assert abs(pf - mc_pf) < 0.05, (
            f"P_f displacement: got {pf:.4f}, MC ref {mc_pf:.4f}"
        )


class TestPipelineRerunnable:
    """Verify the pipeline reads config dynamically (anti-hardcoding check)."""

    def test_adapts_to_modified_design_point(self):
        shutil.copy("/app/results.json", "/app/results_orig_backup.json")
        shutil.copy("/app/problem_spec.json", "/app/problem_spec_backup.json")

        try:
            with open("/app/problem_spec.json") as f:
                config = json.load(f)
            config["design_point"]["w"] = 3.0
            config["design_point"]["t"] = 4.0
            with open("/app/problem_spec.json", "w") as f:
                json.dump(config, f, indent=2)

            result = subprocess.run(
                ["python3", "/app/uq_pipeline.py"],
                capture_output=True, timeout=180,
            )
            assert result.returncode == 0, (
                f"Pipeline failed on modified config: {result.stderr.decode()[:500]}"
            )

            with open("/app/results.json") as f:
                new_results = json.load(f)

            w2, t2 = 3.0, 4.0
            c_Y2 = 600.0 / (w2 * t2 ** 2)
            c_X2 = 600.0 / (w2 ** 2 * t2)
            expected_mean2 = c_Y2 * 1000 + c_X2 * 500
            actual_mean2 = new_results["stress_mean"]
            assert abs(actual_mean2 - expected_mean2) / abs(expected_mean2) < 1e-4, (
                f"Modified stress_mean: expected {expected_mean2:.4f}, "
                f"got {actual_mean2:.4f}"
            )

            orig_mean = 600.0 / (2.5 * 3.5 ** 2) * 1000 + 600.0 / (2.5 ** 2 * 3.5) * 500
            assert abs(actual_mean2 - orig_mean) / orig_mean > 0.1, (
                "stress_mean did not change with modified design point"
            )
        finally:
            shutil.copy("/app/problem_spec_backup.json", "/app/problem_spec.json")
            shutil.copy("/app/results_orig_backup.json", "/app/results.json")
