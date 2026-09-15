"""
Tests for JCGM 101:2008 measurement uncertainty validation.
Verifies comparison loss model uncertainty propagation results.
"""

import json
import math
import os
import sqlite3
import pytest


RESULTS_PATH = "/app/results/comparison_loss.json"
DB_PATH = "/app/input/calibration.db"
SIGMA = 0.005  # standard uncertainty for all input quantities


@pytest.fixture(scope="module")
def results():
    """Load the results JSON file."""
    assert os.path.exists(RESULTS_PATH), (
        f"Results file not found at {RESULTS_PATH}. "
        "Ensure run_analysis.py was executed successfully."
    )
    with open(RESULTS_PATH) as f:
        data = json.load(f)
    return data


# ── Structure tests ──────────────────────────────────────────────────────


class TestResultsStructure:
    """Verify output file structure and completeness."""

    def test_all_cases_present(self, results):
        for i in range(1, 7):
            assert f"case_{i}" in results, f"Missing case_{i}"

    def test_mcm_fields(self, results):
        for i in range(1, 7):
            mcm = results[f"case_{i}"]["mcm"]
            for field in ["y", "u_y", "shortest_95", "symmetric_95", "M_trials"]:
                assert field in mcm, f"case_{i} mcm missing '{field}'"
            assert len(mcm["shortest_95"]) == 2
            assert len(mcm["symmetric_95"]) == 2
            assert isinstance(mcm["M_trials"], int)

    def test_guf_fields(self, results):
        for i in range(1, 7):
            for guf_key in ["guf1", "guf2"]:
                guf = results[f"case_{i}"][guf_key]
                for field in ["y", "u_y", "coverage_95"]:
                    assert field in guf, f"case_{i} {guf_key} missing '{field}'"
                assert len(guf["coverage_95"]) == 2

    def test_validation_fields(self, results):
        for i in range(1, 7):
            val = results[f"case_{i}"]["validation"]
            for field in ["delta", "d_low", "d_high", "validated"]:
                assert field in val, f"case_{i} validation missing '{field}'"
            assert isinstance(val["validated"], bool)


# ── Input data integrity tests ───────────────────────────────────────────


class TestInputDataIntegrity:
    """Verify results are consistent with SQLite database parameters."""

    def test_case_count_matches_database(self, results):
        """Number of result cases should match database entries."""
        conn = sqlite3.connect(DB_PATH)
        n = conn.execute("SELECT COUNT(*) FROM calibration_cases").fetchone()[0]
        conn.close()
        assert len(results) == n, (
            f"Expected {n} cases from database, got {len(results)}"
        )

    def test_guf1_estimates_match_model(self, results):
        """GUF1 estimate y = x1^2 + x2^2 must match database parameters."""
        conn = sqlite3.connect(DB_PATH)
        cases = conn.execute(
            "SELECT case_id, x1, x2 FROM calibration_cases ORDER BY case_id"
        ).fetchall()
        conn.close()
        for case_id, x1, x2 in cases:
            expected = x1 ** 2 + x2 ** 2
            actual = results[f"case_{case_id}"]["guf1"]["y"]
            assert abs(actual - expected) < 1e-12, (
                f"case_{case_id}: GUF1 y={actual} != x1^2+x2^2={expected}"
            )

    def test_ndig_matches_database(self, results):
        """Validation ndig must match database configuration."""
        conn = sqlite3.connect(DB_PATH)
        ndig = int(conn.execute(
            "SELECT value_real FROM analysis_config WHERE key='ndig'"
        ).fetchone()[0])
        conn.close()
        for i in range(1, 7):
            assert results[f"case_{i}"]["validation"]["ndig"] == ndig


# ── GUF1 exact value tests ──────────────────────────────────────────────


class TestGUF1ExactValues:
    """GUF1 computations are deterministic and exact."""

    def test_case1_estimate_zero(self, results):
        """x1=x2=0: y = 0^2 + 0^2 = 0"""
        assert results["case_1"]["guf1"]["y"] == 0.0

    def test_case1_uncertainty_zero(self, results):
        """x1=x2=0: first-order sensitivities vanish, so u(y)=0."""
        assert results["case_1"]["guf1"]["u_y"] == 0.0

    def test_case2_estimate(self, results):
        """x1=0.010, x2=0: y = 0.010^2 = 1e-4"""
        assert abs(results["case_2"]["guf1"]["y"] - 1e-4) < 1e-12

    def test_case2_uncertainty(self, results):
        """x1=0.010, x2=0: u(y) = 2*0.010*0.005 = 1e-4"""
        assert abs(results["case_2"]["guf1"]["u_y"] - 1e-4) < 1e-12

    def test_case3_estimate(self, results):
        """x1=0.050, x2=0: y = 0.050^2 = 2.5e-3"""
        assert abs(results["case_3"]["guf1"]["y"] - 2.5e-3) < 1e-12

    def test_case3_uncertainty(self, results):
        """x1=0.050, x2=0: u(y) = 2*0.050*0.005 = 5e-4"""
        assert abs(results["case_3"]["guf1"]["u_y"] - 5e-4) < 1e-12

    def test_guf1_invariant_to_correlation(self, results):
        """GUF1 u(y) must be independent of r when x2=0
        because the second sensitivity coefficient vanishes."""
        for uncorr, corr in [(1, 4), (2, 5), (3, 6)]:
            u_uncorr = results[f"case_{uncorr}"]["guf1"]["u_y"]
            u_corr = results[f"case_{corr}"]["guf1"]["u_y"]
            assert abs(u_uncorr - u_corr) < 1e-15, (
                f"GUF1 u(y) differs: case_{uncorr}={u_uncorr}, case_{corr}={u_corr}"
            )

    def test_guf1_coverage_symmetric(self, results):
        """GUF1 coverage must be symmetric about y with k=1.96."""
        for i in [2, 3, 5, 6]:  # skip cases where u=0
            guf1 = results[f"case_{i}"]["guf1"]
            y = guf1["y"]
            u = guf1["u_y"]
            lo, hi = guf1["coverage_95"]
            expected_half = 1.96 * u
            assert abs((y - lo) - expected_half) / expected_half < 0.01
            assert abs((hi - y) - expected_half) / expected_half < 0.01


# ── GUF2 exact value tests ──────────────────────────────────────────────


class TestGUF2ExactValues:
    """GUF2 computations are deterministic and verifiable analytically."""

    def test_case1_estimate(self, results):
        """x1=x2=0: second-order corrected estimate = 2*sigma^2 = 50e-6"""
        expected = 2.0 * SIGMA ** 2
        assert abs(results["case_1"]["guf2"]["y"] - expected) < 1e-12

    def test_case1_uncertainty_r0(self, results):
        """x1=x2=0, r=0: second-order u(y) = 2*sigma^2 = 50e-6"""
        expected = 2.0 * SIGMA ** 2
        actual = results["case_1"]["guf2"]["u_y"]
        assert abs(actual - expected) / expected < 0.001

    def test_case3_estimate(self, results):
        """x1=0.050: corrected estimate = 0.050^2 + 2*sigma^2 = 2.55e-3"""
        expected = 0.050 ** 2 + 2.0 * SIGMA ** 2
        assert abs(results["case_3"]["guf2"]["y"] - expected) < 1e-12

    def test_case3_uncertainty(self, results):
        """x1=0.050, r=0: second-order u(y) ~ 502e-6"""
        expected = math.sqrt(
            4.0 * 0.050 ** 2 * SIGMA ** 2 + 4.0 * SIGMA ** 4
        )
        actual = results["case_3"]["guf2"]["u_y"]
        assert abs(actual - expected) / expected < 0.001

    def test_case4_uncertainty_with_correlation(self, results):
        """x1=x2=0, r=0.9: second-order u(y) = sigma^2 * sqrt(4 + 4*r^2) ~ 67e-6"""
        r = 0.9
        expected = SIGMA ** 2 * math.sqrt(4.0 + 4.0 * r ** 2)
        actual = results["case_4"]["guf2"]["u_y"]
        assert abs(actual - expected) / expected < 0.001

    def test_guf2_estimate_independent_of_r(self, results):
        """GUF2 corrected estimate does not depend on r for this model."""
        for uncorr, corr in [(1, 4), (2, 5), (3, 6)]:
            y_uncorr = results[f"case_{uncorr}"]["guf2"]["y"]
            y_corr = results[f"case_{corr}"]["guf2"]["y"]
            assert abs(y_uncorr - y_corr) < 1e-12


# ── MCM approximate value tests ─────────────────────────────────────────


class TestMCMValues:
    """MCM results should match analytical values within statistical tolerance.
    For case 1 (x1=x2=0, r=0), delta_Y ~ Exp(rate=1/(2*sigma^2)):
    E = 2*sigma^2 = 50e-6, SD = 2*sigma^2 = 50e-6,
    shortest 95% CI = [0, -2*sigma^2*ln(0.05)] ~ [0, 150e-6]."""

    def test_case1_estimate(self, results):
        expected = 2.0 * SIGMA ** 2  # 50e-6
        actual = results["case_1"]["mcm"]["y"]
        assert abs(actual - expected) / expected < 0.15

    def test_case1_uncertainty(self, results):
        expected = 2.0 * SIGMA ** 2  # 50e-6
        actual = results["case_1"]["mcm"]["u_y"]
        assert abs(actual - expected) / expected < 0.15

    def test_case1_shortest_lower_near_zero(self, results):
        """Shortest 95% CI lower endpoint for exponential dist is ~0."""
        lo = results["case_1"]["mcm"]["shortest_95"][0]
        assert lo < 10e-6, f"Lower endpoint too large: {lo}"

    def test_case1_shortest_upper(self, results):
        """Upper endpoint ~ -2*sigma^2*ln(0.05) ~ 150e-6."""
        expected = -2.0 * SIGMA ** 2 * math.log(0.05)
        actual = results["case_1"]["mcm"]["shortest_95"][1]
        assert abs(actual - expected) / expected < 0.15

    def test_case3_estimate(self, results):
        """E[delta_Y] = x1^2 + 2*sigma^2 = 2550e-6"""
        expected = 0.050 ** 2 + 2.0 * SIGMA ** 2
        actual = results["case_3"]["mcm"]["y"]
        assert abs(actual - expected) / expected < 0.10

    def test_case3_uncertainty(self, results):
        """u(y) ~ sqrt(4*x1^2*sigma^2 + 4*sigma^4) ~ 502e-6"""
        expected = math.sqrt(
            4.0 * 0.050 ** 2 * SIGMA ** 2 + 4.0 * SIGMA ** 4
        )
        actual = results["case_3"]["mcm"]["u_y"]
        assert abs(actual - expected) / expected < 0.10

    def test_case4_uncertainty_larger_than_case1(self, results):
        """Correlation r=0.9 should increase u(y) compared to r=0."""
        u_r0 = results["case_1"]["mcm"]["u_y"]
        u_r09 = results["case_4"]["mcm"]["u_y"]
        assert u_r09 > u_r0 * 1.1, (
            f"Expected r=0.9 to give larger uncertainty: {u_r09} vs {u_r0}"
        )

    def test_case6_estimate(self, results):
        """x1=0.050, r=0.9: E[delta_Y] should still be ~ 2550e-6
        (expectation doesn't depend on r for x2=0)."""
        expected = 0.050 ** 2 + 2.0 * SIGMA ** 2
        actual = results["case_6"]["mcm"]["y"]
        assert abs(actual - expected) / expected < 0.10


# ── Coverage interval property tests ────────────────────────────────────


class TestCoverageIntervalProperties:
    """Verify mathematical properties of coverage intervals."""

    def test_intervals_ordered(self, results):
        """All coverage intervals must have lo < hi (except degenerate u=0)."""
        for i in range(1, 7):
            case = results[f"case_{i}"]
            for key in ["shortest_95", "symmetric_95"]:
                lo, hi = case["mcm"][key]
                assert lo < hi, f"case_{i} mcm {key}: {lo} >= {hi}"
            guf1 = case["guf1"]
            if guf1["u_y"] > 0:
                lo, hi = guf1["coverage_95"]
                assert lo < hi, f"case_{i} guf1: {lo} >= {hi}"

    def test_shortest_not_longer_than_symmetric(self, results):
        """By definition, shortest CI length <= symmetric CI length."""
        for i in range(1, 7):
            mcm = results[f"case_{i}"]["mcm"]
            short_len = mcm["shortest_95"][1] - mcm["shortest_95"][0]
            sym_len = mcm["symmetric_95"][1] - mcm["symmetric_95"][0]
            assert short_len <= sym_len * 1.05, (
                f"case_{i}: shortest ({short_len:.3e}) > symmetric ({sym_len:.3e})"
            )

    def test_case1_shortest_noticeably_shorter(self, results):
        """For case 1 (exponential-like dist), shortest CI should be
        significantly shorter than symmetric."""
        mcm = results["case_1"]["mcm"]
        short_len = mcm["shortest_95"][1] - mcm["shortest_95"][0]
        sym_len = mcm["symmetric_95"][1] - mcm["symmetric_95"][0]
        assert short_len < sym_len * 0.95, (
            f"Expected shortest ({short_len:.3e}) much shorter than "
            f"symmetric ({sym_len:.3e}) for skewed distribution"
        )

    def test_delta_y_nonnegative(self, results):
        """delta_Y = X1^2 + X2^2 >= 0, so shortest CI lower >= 0."""
        for i in range(1, 7):
            lo = results[f"case_{i}"]["mcm"]["shortest_95"][0]
            assert lo >= -1e-10, f"case_{i}: shortest lower bound negative: {lo}"

    def test_mcm_trials_reasonable(self, results):
        """Adaptive MCM should use a reasonable number of trials."""
        for i in range(1, 7):
            M = results[f"case_{i}"]["mcm"]["M_trials"]
            assert M >= 10000, f"case_{i}: too few trials ({M})"
            assert M < 5e7, f"case_{i}: too many trials ({M})"


# ── Validation tests ────────────────────────────────────────────────────


class TestValidation:
    """Verify GUF validation results."""

    def test_case1_not_validated(self, results):
        """Case 1 (x1=x2=0): GUF1 gives u(y)=0 and degenerate CI.
        MCM gives a non-degenerate distribution. Must NOT be validated."""
        assert results["case_1"]["validation"]["validated"] is False

    def test_case4_not_validated(self, results):
        """Case 4 (x1=x2=0, r=0.9): same GUF1 behavior as case 1.
        Must NOT be validated."""
        assert results["case_4"]["validation"]["validated"] is False

    def test_delta_positive_when_uy_positive(self, results):
        """Numerical tolerance delta must be > 0 when MCM u(y) > 0."""
        for i in range(1, 7):
            u_y = results[f"case_{i}"]["mcm"]["u_y"]
            delta = results[f"case_{i}"]["validation"]["delta"]
            if u_y > 0:
                assert delta > 0, (
                    f"case_{i}: delta={delta} but u_y={u_y}"
                )

    def test_d_values_nonnegative(self, results):
        """d_low and d_high are absolute differences, must be >= 0."""
        for i in range(1, 7):
            val = results[f"case_{i}"]["validation"]
            assert val["d_low"] >= 0
            assert val["d_high"] >= 0

    def test_validation_consistency(self, results):
        """validated == True iff d_low <= delta AND d_high <= delta."""
        for i in range(1, 7):
            val = results[f"case_{i}"]["validation"]
            expected = (
                val["d_low"] <= val["delta"] and
                val["d_high"] <= val["delta"]
            )
            assert val["validated"] == expected, (
                f"case_{i}: validated={val['validated']} but "
                f"d_low={val['d_low']}, d_high={val['d_high']}, "
                f"delta={val['delta']}"
            )


# ── Convergence plot tests ──────────────────────────────────────────────


class TestConvergencePlot:
    """Verify convergence diagnostic plot exists and is valid SVG."""

    PLOT_PATH = "/app/results/convergence.svg"

    def test_plot_exists(self):
        assert os.path.exists(self.PLOT_PATH), (
            f"Convergence plot not found at {self.PLOT_PATH}"
        )

    def test_plot_is_valid_svg(self):
        with open(self.PLOT_PATH) as f:
            content = f.read(10000)
        assert '<svg' in content.lower(), (
            "File does not contain SVG markup"
        )

    def test_plot_has_reasonable_size(self):
        size = os.path.getsize(self.PLOT_PATH)
        assert size > 1000, f"Plot file suspiciously small ({size} bytes)"
        assert size < 10_000_000, f"Plot file too large ({size} bytes)"
