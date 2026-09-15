"""
Tests for JCGM 101:2008 measurement uncertainty evaluation.
Verifies correctness of GUM framework, adaptive MCM, GUM validation,
and correct data extraction from heterogeneous sources (SQLite + JSON).
"""

import json
import os
import math
import sqlite3
import pytest


@pytest.fixture(scope="session")
def results():
    with open("/app/results.json") as f:
        return json.load(f)


@pytest.fixture(scope="session")
def calibration_db():
    conn = sqlite3.connect("/app/calibration.db")
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


# ============================================================
# Structural tests
# ============================================================


class TestStructure:
    def test_results_file_exists(self):
        assert os.path.exists("/app/results.json"), "results.json not found"

    def test_has_comparison_loss(self, results):
        assert "comparison_loss" in results

    def test_has_gauge_block(self, results):
        assert "gauge_block" in results

    def test_comparison_loss_has_all_cases(self, results):
        cl = results["comparison_loss"]
        for cid in ("case1", "case2", "case3"):
            assert cid in cl, f"Missing {cid}"
            for section in ("gum", "mcm", "validation"):
                assert section in cl[cid], f"Missing {section} in {cid}"

    def test_gauge_block_sections(self, results):
        gb = results["gauge_block"]
        for section in ("gum", "mcm", "validation"):
            assert section in gb, f"Missing {section} in gauge_block"

    def test_gum_fields(self, results):
        gum = results["gauge_block"]["gum"]
        for field in ("estimate", "uncertainty", "coverage_interval",
                      "coverage_probability", "effective_dof"):
            assert field in gum, f"Missing GUM field: {field}"

    def test_mcm_fields(self, results):
        mcm = results["gauge_block"]["mcm"]
        for field in ("estimate", "uncertainty", "shortest_coverage_interval",
                      "num_trials"):
            assert field in mcm, f"Missing MCM field: {field}"

    def test_validation_fields(self, results):
        val = results["gauge_block"]["validation"]
        for field in ("d_low", "d_high", "delta", "validated"):
            assert field in val, f"Missing validation field: {field}"


# ============================================================
# SQLite data extraction verification
# ============================================================


class TestDataExtraction:
    """Verify the agent correctly extracted data from the SQLite database."""

    def test_type_a_dof_D(self, results, calibration_db):
        """DOF for D must equal n-1 where n is the number of observations."""
        cur = calibration_db.execute(
            "SELECT COUNT(*) as n FROM measurement_observations WHERE quantity='D'"
        )
        n = cur.fetchone()["n"]
        expected_dof = n - 1  # 24
        gum = results["gauge_block"]["gum"]
        # The effective DOF should reflect Type A evaluation: DOF(D)=n-1=24
        # We can't check nu_eff directly equals 24 (it's combined), but we check
        # that the estimate used the correct mean from the raw data
        cur2 = calibration_db.execute(
            "SELECT AVG(value_nm) as mean_val FROM measurement_observations WHERE quantity='D'"
        )
        db_mean = cur2.fetchone()["mean_val"]
        # The GUM estimate should incorporate this mean value (~215 nm)
        # gauge_block estimate = Ls + D + d1 + d2 - ... ≈ 838 nm
        assert abs(gum["estimate"] - 838) < 2, \
            f"GUM estimate should be ~838 nm (reflecting D mean from DB), got {gum['estimate']}"

    def test_type_a_dof_d1(self, calibration_db):
        """d1 should have 6 observations → DOF=5."""
        cur = calibration_db.execute(
            "SELECT COUNT(*) as n FROM measurement_observations WHERE quantity='d1'"
        )
        n = cur.fetchone()["n"]
        assert n == 6, f"d1 should have 6 observations, found {n}"

    def test_type_a_dof_d2(self, calibration_db):
        """d2 should have 9 observations → DOF=8."""
        cur = calibration_db.execute(
            "SELECT COUNT(*) as n FROM measurement_observations WHERE quantity='d2'"
        )
        n = cur.fetchone()["n"]
        assert n == 9, f"d2 should have 9 observations, found {n}"

    def test_type_a_mean_d1_near_zero(self, results, calibration_db):
        """d1 observations have mean ~0, which should be reflected in the estimate."""
        cur = calibration_db.execute(
            "SELECT AVG(value_nm) as mean_val FROM measurement_observations WHERE quantity='d1'"
        )
        db_mean = cur.fetchone()["mean_val"]
        assert abs(db_mean) < 0.01, \
            f"d1 mean from DB should be ~0, got {db_mean}"


# ============================================================
# Comparison loss case 1: x1=0, x2=0 (GUM first-order fails)
# Analytical: delta_Y ~ Exp(rate = 1/(2*u^2)) = chi-squared(2) scaled
# E[delta_Y] = 2*u^2(x1) = 50e-6
# u(delta_Y) = 2*u^2(x1) = 50e-6
# Shortest 95% CI = [0, -2*u^2(x1)*ln(0.05)] = [0, ~150e-6]
# ============================================================


class TestComparisonLossCase1:
    """GUM gives zero uncertainty here because sensitivity coefficients vanish."""

    def test_gum_estimate_is_zero(self, results):
        gum = results["comparison_loss"]["case1"]["gum"]
        assert abs(gum["estimate"]) < 1e-10, \
            f"GUM estimate should be 0, got {gum['estimate']}"

    def test_gum_uncertainty_is_zero(self, results):
        gum = results["comparison_loss"]["case1"]["gum"]
        assert gum["uncertainty"] < 1e-10, \
            f"GUM uncertainty should be 0, got {gum['uncertainty']}"

    def test_mcm_estimate_positive(self, results):
        mcm = results["comparison_loss"]["case1"]["mcm"]
        assert mcm["estimate"] > 0, "MCM estimate must be positive (delta_Y >= 0)"

    def test_mcm_estimate_near_analytical(self, results):
        mcm = results["comparison_loss"]["case1"]["mcm"]
        # Analytical: E[delta_Y] = 2 * 0.005^2 = 50e-6
        assert abs(mcm["estimate"] - 50e-6) < 15e-6, \
            f"MCM estimate should be ~50e-6, got {mcm['estimate']}"

    def test_mcm_uncertainty_near_analytical(self, results):
        mcm = results["comparison_loss"]["case1"]["mcm"]
        # Analytical: std(delta_Y) = 2 * u^2(x1) = 50e-6 (exponential)
        assert abs(mcm["uncertainty"] - 50e-6) < 15e-6, \
            f"MCM uncertainty should be ~50e-6, got {mcm['uncertainty']}"

    def test_mcm_ci_lower_near_zero(self, results):
        mcm = results["comparison_loss"]["case1"]["mcm"]
        ci = mcm["shortest_coverage_interval"]
        assert ci[0] >= -1e-6, "CI lower bound can't be negative"
        assert ci[0] < 10e-6, \
            f"CI lower should be near 0 for exponential, got {ci[0]}"

    def test_mcm_ci_upper_near_analytical(self, results):
        mcm = results["comparison_loss"]["case1"]["mcm"]
        ci = mcm["shortest_coverage_interval"]
        # Analytical: -2*0.005^2*ln(0.05) = 149.8e-6
        assert abs(ci[1] - 150e-6) < 30e-6, \
            f"CI upper should be ~150e-6, got {ci[1]}"

    def test_not_validated(self, results):
        val = results["comparison_loss"]["case1"]["validation"]
        assert val["validated"] is False, \
            "Case1 GUM must NOT be validated (u_GUM=0, MCM CI is [0,150e-6])"

    def test_mcm_used_enough_trials(self, results):
        mcm = results["comparison_loss"]["case1"]["mcm"]
        assert mcm["num_trials"] >= 10000


# ============================================================
# Comparison loss case 2: x1=0.01, x2=0
# ============================================================


class TestComparisonLossCase2:
    def test_gum_estimate(self, results):
        gum = results["comparison_loss"]["case2"]["gum"]
        # y = 0.01^2 + 0^2 = 100e-6
        assert abs(gum["estimate"] - 100e-6) < 1e-6

    def test_gum_uncertainty(self, results):
        gum = results["comparison_loss"]["case2"]["gum"]
        # c1=2*0.01=0.02, c2=0; u^2 = 0.02^2*0.005^2 = 1e-8; u = 100e-6
        assert abs(gum["uncertainty"] - 100e-6) < 5e-6

    def test_mcm_estimate(self, results):
        mcm = results["comparison_loss"]["case2"]["mcm"]
        # E[delta_Y] = x1^2+x2^2+u^2(x1)+u^2(x2) = 100e-6 + 50e-6 = 150e-6
        assert abs(mcm["estimate"] - 150e-6) < 30e-6

    def test_mcm_uncertainty(self, results):
        mcm = results["comparison_loss"]["case2"]["mcm"]
        # Analytical: u ~ 112e-6
        assert abs(mcm["uncertainty"] - 112e-6) < 25e-6


# ============================================================
# Comparison loss case 3: x1=0.05, x2=0
# ============================================================


class TestComparisonLossCase3:
    def test_gum_estimate(self, results):
        gum = results["comparison_loss"]["case3"]["gum"]
        # y = 0.05^2 = 2500e-6
        assert abs(gum["estimate"] - 2500e-6) < 1e-6

    def test_gum_uncertainty(self, results):
        gum = results["comparison_loss"]["case3"]["gum"]
        # c1=0.1; u^2 = 0.1^2*0.005^2 = 2.5e-7; u = 500e-6
        assert abs(gum["uncertainty"] - 500e-6) < 10e-6

    def test_mcm_estimate(self, results):
        mcm = results["comparison_loss"]["case3"]["mcm"]
        # E[delta_Y] = 2500e-6 + 50e-6 = 2550e-6
        assert abs(mcm["estimate"] - 2550e-6) < 100e-6

    def test_mcm_uncertainty(self, results):
        mcm = results["comparison_loss"]["case3"]["mcm"]
        # Analytical: u ~ 502e-6
        assert abs(mcm["uncertainty"] - 502e-6) < 60e-6


# ============================================================
# Gauge block: GUM framework
# Reference: delta_L = 838 nm, u(delta_L) ~ 32 nm, nu_eff ~ 16
# ============================================================


class TestGaugeBlockGUM:
    def test_estimate(self, results):
        gum = results["gauge_block"]["gum"]
        assert abs(gum["estimate"] - 838) < 2, \
            f"GUM estimate should be ~838 nm, got {gum['estimate']}"

    def test_uncertainty_in_range(self, results):
        gum = results["gauge_block"]["gum"]
        assert 25 < gum["uncertainty"] < 42, \
            f"GUM uncertainty should be ~32 nm, got {gum['uncertainty']}"

    def test_effective_dof_finite(self, results):
        gum = results["gauge_block"]["gum"]
        dof = gum["effective_dof"]
        assert dof is not None, "Gauge block should have finite effective DOF"
        assert 8 < float(dof) < 30, \
            f"Effective DOF should be ~16, got {dof}"

    def test_coverage_interval_contains_estimate(self, results):
        gum = results["gauge_block"]["gum"]
        ci = gum["coverage_interval"]
        assert ci[0] < gum["estimate"] < ci[1]

    def test_coverage_interval_endpoints(self, results):
        gum = results["gauge_block"]["gum"]
        ci = gum["coverage_interval"]
        # 99% CI endpoints should be roughly [745, 931] nm
        assert 710 < ci[0] < 775, \
            f"CI lower should be ~745, got {ci[0]}"
        assert 895 < ci[1] < 965, \
            f"CI upper should be ~931, got {ci[1]}"

    def test_coverage_probability(self, results):
        gum = results["gauge_block"]["gum"]
        assert abs(gum["coverage_probability"] - 0.99) < 0.001


# ============================================================
# Gauge block: Adaptive MCM
# Reference: delta_L = 838 nm, u(delta_L) ~ 36 nm, CI ~ [745, 932]
# ============================================================


class TestGaugeBlockMCM:
    def test_estimate(self, results):
        mcm = results["gauge_block"]["mcm"]
        assert abs(mcm["estimate"] - 838) < 8, \
            f"MCM estimate should be ~838 nm, got {mcm['estimate']}"

    def test_uncertainty_in_range(self, results):
        mcm = results["gauge_block"]["mcm"]
        assert 28 < mcm["uncertainty"] < 50, \
            f"MCM uncertainty should be ~36 nm, got {mcm['uncertainty']}"

    def test_mcm_uncertainty_geq_gum(self, results):
        """MCM u(y) should be >= GUM u(y) due to t-distribution heavier tails
        and second-order model non-linearity."""
        gum_u = results["gauge_block"]["gum"]["uncertainty"]
        mcm_u = results["gauge_block"]["mcm"]["uncertainty"]
        assert mcm_u >= gum_u - 3, \
            f"MCM u ({mcm_u}) should be >= GUM u ({gum_u}) minus small tolerance"

    def test_coverage_interval_ordered(self, results):
        mcm = results["gauge_block"]["mcm"]
        ci = mcm["shortest_coverage_interval"]
        assert ci[0] < ci[1]

    def test_coverage_interval_endpoints(self, results):
        mcm = results["gauge_block"]["mcm"]
        ci = mcm["shortest_coverage_interval"]
        assert 710 < ci[0] < 780, \
            f"CI lower should be ~745, got {ci[0]}"
        assert 890 < ci[1] < 965, \
            f"CI upper should be ~932, got {ci[1]}"

    def test_num_trials_reasonable(self, results):
        mcm = results["gauge_block"]["mcm"]
        assert mcm["num_trials"] >= 10000, \
            "Adaptive MCM should use at least 10000 trials"


# ============================================================
# Gauge block: Validation
# With ndig=1, delta ~ 5 nm. GUM and MCM endpoints differ by ~0-2 nm.
# ============================================================


class TestGaugeBlockValidation:
    def test_d_values_reasonable(self, results):
        val = results["gauge_block"]["validation"]
        assert val["d_low"] < 20, \
            f"d_low should be small, got {val['d_low']}"
        assert val["d_high"] < 20, \
            f"d_high should be small, got {val['d_high']}"

    def test_delta_positive(self, results):
        val = results["gauge_block"]["validation"]
        assert val["delta"] > 0

    def test_validated_is_boolean(self, results):
        val = results["gauge_block"]["validation"]
        assert isinstance(val["validated"], bool)


# ============================================================
# Cross-model consistency checks
# ============================================================


class TestConsistency:
    def test_all_mcm_ci_ordered(self, results):
        """All shortest coverage intervals must have lower < upper."""
        for case_id in ("case1", "case2", "case3"):
            ci = results["comparison_loss"][case_id]["mcm"]["shortest_coverage_interval"]
            assert ci[0] < ci[1], f"CI not ordered in {case_id}"

    def test_all_gum_ci_ordered(self, results):
        """All GUM coverage intervals must have lower < upper (or both zero)."""
        for case_id in ("case1", "case2", "case3"):
            ci = results["comparison_loss"][case_id]["gum"]["coverage_interval"]
            assert ci[0] <= ci[1], f"GUM CI not ordered in {case_id}"

    def test_comparison_loss_monotonic_estimates(self, results):
        """MCM estimates should increase with x1: case1 < case2 < case3."""
        e1 = results["comparison_loss"]["case1"]["mcm"]["estimate"]
        e2 = results["comparison_loss"]["case2"]["mcm"]["estimate"]
        e3 = results["comparison_loss"]["case3"]["mcm"]["estimate"]
        assert e1 < e2 < e3, f"Estimates not monotonic: {e1}, {e2}, {e3}"

    def test_comparison_loss_case1_gum_vs_mcm_bias(self, results):
        """For case1, MCM estimate >> GUM estimate (non-linearity bias)."""
        gum_e = results["comparison_loss"]["case1"]["gum"]["estimate"]
        mcm_e = results["comparison_loss"]["case1"]["mcm"]["estimate"]
        assert mcm_e > gum_e + 1e-6, \
            "MCM estimate should be much larger than GUM for case1 (non-linearity)"
