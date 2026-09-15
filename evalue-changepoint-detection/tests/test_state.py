
"""
Tests for the e-value change-point detection system.

Uses independent reference implementations to verify mathematical correctness
of mixture supermartingales, CUSUM detection, and confidence sequences.
"""

import json
import math
import os
import sys

import numpy as np
import pytest
from scipy import special, stats

sys.path.insert(0, "/app")


# ===== Reference implementations (independent of solution) =====


def ref_best_rho_two_sided(v_opt, alpha_opt):
    log_inv_alpha = np.log(1.0 / alpha_opt)
    return v_opt / (2 * log_inv_alpha + np.log(1 + 2 * log_inv_alpha))


def ref_best_rho_one_sided(v_opt, alpha_opt):
    return ref_best_rho_two_sided(v_opt, 2 * alpha_opt)


def ref_two_sided_log_superMG(s, v, rho):
    return 0.5 * np.log(rho / (v + rho)) + s * s / (2 * (v + rho))


def ref_one_sided_log_superMG(s, v, rho):
    sigma = np.sqrt(v + rho)
    return (
        0.5 * np.log(4 * rho / (v + rho))
        + s * s / (2 * (v + rho))
        + np.log(stats.norm.cdf(s / sigma))
    )


def ref_two_sided_bound(v, rho, log_threshold):
    return np.sqrt((v + rho) * (np.log(1 + v / rho) + 2 * log_threshold))


def ref_log_beta(a, b):
    return special.gammaln(a) + special.gammaln(b) - special.gammaln(a + b)


def ref_log_incomplete_beta(a, b, x):
    if x == 1:
        return ref_log_beta(a, b)
    val = special.betainc(a, b, x)
    if val <= 0:
        return -np.inf
    return np.log(val) + ref_log_beta(a, b)


def ref_gamma_exp_leading_constant(rho, c):
    rho_c_sq = rho / (c * c)
    return (
        rho_c_sq * np.log(rho_c_sq)
        - special.gammaln(rho_c_sq)
        - np.log(special.gammainc(rho_c_sq, rho_c_sq))
    )


def ref_gamma_exp_log_superMG(s, v, rho, c, leading_constant):
    c_sq = c * c
    cs_v_csq = (c * s + v) / c_sq
    v_rho_csq = (v + rho) / c_sq
    return (
        leading_constant
        + special.gammaln(v_rho_csq)
        + np.log(special.gammainc(v_rho_csq, cs_v_csq + rho / c_sq))
        - v_rho_csq * np.log(cs_v_csq + rho / c_sq)
        + cs_v_csq
    )


# ===== Test: TwoSidedNormalMixture =====


class TestTwoSidedNormalMixture:
    def test_rho_computation(self):
        from evalue.martingales import TwoSidedNormalMixture

        for v_opt, alpha_opt in [(100, 0.05), (50, 0.01), (200, 0.1), (10, 0.05)]:
            mix = TwoSidedNormalMixture(v_opt=v_opt, alpha_opt=alpha_opt)
            expected_rho = ref_best_rho_two_sided(v_opt, alpha_opt)
            assert np.isclose(
                mix.rho, expected_rho, rtol=1e-10
            ), f"rho mismatch for v_opt={v_opt}, alpha_opt={alpha_opt}: {mix.rho} != {expected_rho}"

    def test_log_superMG_values(self):
        from evalue.martingales import TwoSidedNormalMixture

        mix = TwoSidedNormalMixture(v_opt=100, alpha_opt=0.05)
        rho = ref_best_rho_two_sided(100, 0.05)

        test_cases = [
            (0, 10),
            (5, 50),
            (-5, 50),
            (10, 100),
            (0, 1),
            (3, 20),
            (15, 200),
            (0.1, 0.5),
            (50, 500),
        ]
        for s, v in test_cases:
            expected = ref_two_sided_log_superMG(s, v, rho)
            actual = mix.log_superMG(s, v)
            assert np.isclose(
                actual, expected, rtol=1e-10
            ), f"log_superMG({s},{v}): {actual} != {expected}"

    def test_symmetry(self):
        from evalue.martingales import TwoSidedNormalMixture

        mix = TwoSidedNormalMixture(v_opt=100, alpha_opt=0.05)
        for s in [0.5, 1, 5, 10, 20, 50]:
            for v in [1, 10, 100, 500]:
                pos = mix.log_superMG(s, v)
                neg = mix.log_superMG(-s, v)
                assert np.isclose(
                    pos, neg, rtol=1e-12
                ), f"Symmetry failed at s={s}, v={v}: {pos} != {neg}"

    def test_at_s_zero(self):
        from evalue.martingales import TwoSidedNormalMixture

        mix = TwoSidedNormalMixture(v_opt=100, alpha_opt=0.05)
        for v in [1, 10, 50, 100, 500]:
            val = mix.log_superMG(0, v)
            assert val < 0, f"log_superMG(0,{v}) = {val} should be < 0"

    def test_bound_closed_form(self):
        from evalue.martingales import TwoSidedNormalMixture

        mix = TwoSidedNormalMixture(v_opt=100, alpha_opt=0.05)
        rho = ref_best_rho_two_sided(100, 0.05)

        for v in [10, 50, 100, 500]:
            log_thresh = np.log(1 / 0.05)
            actual = mix.bound(v, log_thresh)
            expected = ref_two_sided_bound(v, rho, log_thresh)
            assert np.isclose(
                actual, expected, rtol=1e-10
            ), f"bound({v}): {actual} != {expected}"

    def test_increasing_with_s_squared(self):
        from evalue.martingales import TwoSidedNormalMixture

        mix = TwoSidedNormalMixture(v_opt=100, alpha_opt=0.05)
        v = 50
        prev = mix.log_superMG(0, v)
        for s in [1, 2, 5, 10, 20]:
            cur = mix.log_superMG(s, v)
            assert cur > prev, f"Not increasing at s={s}: {cur} <= {prev}"
            prev = cur


# ===== Test: OneSidedNormalMixture =====


class TestOneSidedNormalMixture:
    def test_rho_uses_double_alpha(self):
        from evalue.martingales import OneSidedNormalMixture

        mix = OneSidedNormalMixture(v_opt=100, alpha_opt=0.05)
        expected_rho = ref_best_rho_one_sided(100, 0.05)
        assert np.isclose(mix.rho, expected_rho, rtol=1e-10)

    def test_log_superMG_values(self):
        from evalue.martingales import OneSidedNormalMixture

        mix = OneSidedNormalMixture(v_opt=100, alpha_opt=0.05)
        rho = ref_best_rho_one_sided(100, 0.05)

        test_cases = [(5, 50), (10, 100), (-5, 50), (0, 10), (20, 200)]
        for s, v in test_cases:
            expected = ref_one_sided_log_superMG(s, v, rho)
            actual = mix.log_superMG(s, v)
            assert np.isclose(
                actual, expected, rtol=1e-10
            ), f"log_superMG({s},{v}): {actual} != {expected}"

    def test_one_sided_vs_two_sided(self):
        """For positive s, one-sided should eventually dominate two-sided."""
        from evalue.martingales import OneSidedNormalMixture, TwoSidedNormalMixture

        one = OneSidedNormalMixture(v_opt=100, alpha_opt=0.05)
        two = TwoSidedNormalMixture(v_opt=100, alpha_opt=0.05)

        v = 100
        s_large = 20
        val_one = one.log_superMG(s_large, v)
        val_two = two.log_superMG(s_large, v)
        assert val_one > val_two, f"One-sided should dominate for large positive s"

        val_one_neg = one.log_superMG(-s_large, v)
        val_two_neg = two.log_superMG(-s_large, v)
        assert (
            val_one_neg < val_two_neg
        ), f"One-sided should be much smaller for negative s"

    def test_bound_via_root_finding(self):
        from evalue.martingales import OneSidedNormalMixture

        mix = OneSidedNormalMixture(v_opt=100, alpha_opt=0.05)
        v = 100
        log_thresh = np.log(1 / 0.05)
        b = mix.bound(v, log_thresh)

        val = mix.log_superMG(b, v)
        assert np.isclose(
            val, log_thresh, atol=1e-6
        ), f"Bound inversion failed: log_superMG({b},{v})={val} != {log_thresh}"


# ===== Test: BetaBinomialMixture =====


class TestBetaBinomialMixture:
    def test_s_upper_bound(self):
        from evalue.martingales import BetaBinomialMixture

        g, h = 0.5, 0.5
        mix = BetaBinomialMixture(g=g, h=h, v_opt=50, alpha_opt=0.05, is_one_sided=False)
        for v in [10, 50, 100]:
            assert np.isclose(
                mix.s_upper_bound(v), v / g, rtol=1e-10
            ), f"s_upper_bound({v}) != {v/g}"

    def test_log_superMG_reference(self):
        """Verify BetaBinomialMixture log_superMG against direct formula."""
        from evalue.martingales import BetaBinomialMixture

        g, h = 0.5, 0.5
        mix = BetaBinomialMixture(g=g, h=h, v_opt=50, alpha_opt=0.05, is_one_sided=False)

        rho_bb = ref_best_rho_two_sided(50, 0.05)
        r = max(rho_bb - g * h, 1e-3 * g * h)
        gh = g + h

        norm_a = r / (g * gh)
        norm_b = r / (h * gh)
        normalizer = ref_log_incomplete_beta(norm_a, norm_b, 1)

        test_cases = [(0, 10), (2, 20), (5, 50)]
        for s, v in test_cases:
            a_param = (r + v - g * s) / (g * gh)
            b_param = (r + v + h * s) / (h * gh)

            if a_param > 0 and b_param > 0:
                expected = (
                    v / (g * h) * np.log(gh)
                    - (v + h * s) / (h * gh) * np.log(g)
                    - (v - g * s) / (g * gh) * np.log(h)
                    + ref_log_incomplete_beta(a_param, b_param, 1)
                    - normalizer
                )
                actual = mix.log_superMG(s, v)
                assert np.isclose(
                    actual, expected, rtol=1e-8
                ), f"BetaBinomial log_superMG({s},{v}): {actual} != {expected}"

    def test_near_zero_s(self):
        """At s=0, the supermartingale should be close to (but not exactly) 0 in log space."""
        from evalue.martingales import BetaBinomialMixture

        mix = BetaBinomialMixture(
            g=0.5, h=0.5, v_opt=50, alpha_opt=0.05, is_one_sided=False
        )
        for v in [10, 50, 100]:
            val = mix.log_superMG(0, v)
            assert val < 1.0, f"log_superMG(0,{v}) = {val} unreasonably large"
            assert np.isfinite(val), f"log_superMG(0,{v}) = {val} is not finite"


# ===== Test: GammaExponentialMixture =====


class TestGammaExponentialMixture:
    def test_log_superMG_reference(self):
        from evalue.martingales import GammaExponentialMixture

        v_opt, alpha_opt, c = 100, 0.05, 1.0
        mix = GammaExponentialMixture(v_opt=v_opt, alpha_opt=alpha_opt, c=c)

        rho = ref_best_rho_one_sided(v_opt, alpha_opt)
        lc = ref_gamma_exp_leading_constant(rho, c)

        test_cases = [(1, 10), (5, 50), (10, 100), (0.5, 5)]
        for s, v in test_cases:
            expected = ref_gamma_exp_log_superMG(s, v, rho, c, lc)
            actual = mix.log_superMG(s, v)
            assert np.isclose(
                actual, expected, rtol=1e-8
            ), f"GammaExp log_superMG({s},{v}): {actual} != {expected}"

    def test_bound_inversion(self):
        from evalue.martingales import GammaExponentialMixture

        mix = GammaExponentialMixture(v_opt=100, alpha_opt=0.05, c=1.0)
        v = 100
        log_thresh = np.log(1 / 0.025)
        b = mix.bound(v, log_thresh)

        val = mix.log_superMG(b, v)
        assert np.isclose(
            val, log_thresh, atol=1e-5
        ), f"GammaExp bound inversion: log_superMG({b},{v})={val} != {log_thresh}"


# ===== Test: CusumDetector =====


class TestCusumDetector:
    def test_accumulation(self):
        from evalue.cusum import CusumDetector

        det = CusumDetector(threshold=100)
        for i in range(6):
            result = det.update(2.0)
            assert result is None, f"Unexpected alarm at step {i+1}"
        result = det.update(2.0)
        assert result == 7, f"Expected alarm at step 7, got {result}"

    def test_reset_after_alarm(self):
        from evalue.cusum import CusumDetector

        det = CusumDetector(threshold=10)
        result = det.update(100.0)
        assert result == 1

        stat = det.get_statistic()
        assert stat == 1.0, f"After alarm, stat should be 1, got {stat}"

        for _ in range(5):
            result = det.update(1.1)
            assert result is None

    def test_floor_at_one(self):
        from evalue.cusum import CusumDetector

        det = CusumDetector(threshold=20)
        for _ in range(100):
            det.update(0.5)
        assert det.get_statistic() == 1.0, "Stat should be floored at 1"

    def test_get_alarms(self):
        from evalue.cusum import CusumDetector

        det = CusumDetector(threshold=10)
        det.update(20.0)  # alarm at t=1
        det.update(0.5)  # no alarm
        det.update(15.0)  # alarm at t=3

        alarms = det.get_alarms()
        assert alarms == [1, 3], f"Expected [1, 3], got {alarms}"


# ===== Test: ConfidenceSequence =====


class TestConfidenceSequence:
    def test_bounds_contain_mean(self):
        from evalue.confseq import ConfidenceSequence

        cs = ConfidenceSequence(alpha=0.05, v_opt=100, c=1.0, alpha_opt=0.05)
        np.random.seed(123)
        data = np.random.normal(0, 1, 200)

        for x in data:
            lower, upper = cs.update(x)

        assert lower < 0 < upper, f"CI [{lower}, {upper}] does not contain true mean 0"

    def test_width_decreases(self):
        from evalue.confseq import ConfidenceSequence

        cs = ConfidenceSequence(alpha=0.05, v_opt=100, c=1.0, alpha_opt=0.05)
        np.random.seed(456)
        data = np.random.normal(5, 1, 500)

        widths = []
        checkpoints = [20, 50, 100, 200, 500]
        for i, x in enumerate(data):
            lower, upper = cs.update(x)
            if (i + 1) in checkpoints:
                widths.append(upper - lower)

        assert widths[-1] < widths[0], (
            f"CI width should decrease: first={widths[0]:.4f}, last={widths[-1]:.4f}"
        )

    def test_lower_less_than_upper(self):
        from evalue.confseq import ConfidenceSequence

        cs = ConfidenceSequence(alpha=0.05, v_opt=100, c=1.0, alpha_opt=0.05)
        np.random.seed(789)
        for _ in range(100):
            x = np.random.normal(0, 1)
            lower, upper = cs.update(x)
            assert lower < upper, f"Invalid bounds: lower={lower} >= upper={upper}"


# ===== Test: Results file =====


class TestResults:
    @pytest.fixture(autouse=True)
    def load_results(self):
        results_path = "/app/results.json"
        assert os.path.exists(results_path), "results.json does not exist at /app/results.json"
        with open(results_path) as f:
            self.results = json.load(f)

    def test_all_streams_present(self):
        for name in ["stream_1", "stream_2", "stream_3", "stream_4", "stream_5"]:
            assert name in self.results, f"Missing {name} in results"

    def test_result_structure(self):
        required_keys = {"change_detected", "change_points", "final_e_process", "n_alarms"}
        for name in ["stream_1", "stream_2", "stream_3", "stream_4", "stream_5"]:
            r = self.results[name]
            assert required_keys.issubset(
                r.keys()
            ), f"{name} missing keys: {required_keys - set(r.keys())}"
            assert isinstance(r["change_detected"], bool), f"{name}.change_detected not bool"
            assert isinstance(r["change_points"], list), f"{name}.change_points not list"
            assert isinstance(r["n_alarms"], int), f"{name}.n_alarms not int"

    def test_null_stream_no_detection(self):
        """The stationary stream should have no change detected."""
        r = self.results["stream_4"]
        assert (
            r["change_detected"] is False
        ), f"Stream 4 (stationary) should not detect change, got {r}"

    def test_streams_with_change_detected(self):
        """Streams with genuine shifts should be detected."""
        for name in ["stream_1", "stream_2", "stream_5"]:
            r = self.results[name]
            assert (
                r["change_detected"] is True
            ), f"{name} should detect change but didn't: {r}"

    def test_stream5_early_detection(self):
        """Stream 5 has a large shift; detection should occur relatively quickly."""
        r = self.results["stream_5"]
        assert len(r["change_points"]) > 0, "Stream 5 should have at least one alarm"
        first_alarm = r["change_points"][0]
        assert first_alarm <= 400, (
            f"Stream 5 first alarm at {first_alarm}, expected before 400"
        )

    def test_stream2_detection(self):
        """Stream 2 has a shift; first detection should be reasonable."""
        r = self.results["stream_2"]
        assert len(r["change_points"]) > 0, "Stream 2 should have at least one alarm"
        first_alarm = r["change_points"][0]
        assert 200 <= first_alarm <= 700, (
            f"Stream 2 first alarm at {first_alarm}, expected in [200, 700]"
        )

    def test_confidence_sequence_present(self):
        assert "confidence_sequence" in self.results, "Missing confidence_sequence in results"
        cs = self.results["confidence_sequence"]
        for n in ["50", "100", "200", "500", "1000"]:
            assert n in cs, f"Missing checkpoint n={n} in confidence_sequence"
            entry = cs[n]
            assert "lower" in entry and "upper" in entry and "mean" in entry
            assert entry["lower"] < entry["upper"], (
                f"CI at n={n}: lower={entry['lower']} >= upper={entry['upper']}"
            )

    def test_confidence_sequence_coverage_early(self):
        """Before the change point, the CI should cover the true null mean."""
        cs = self.results["confidence_sequence"]
        for n in ["50", "100", "200"]:
            entry = cs[n]
            assert entry["lower"] < 0 < entry["upper"], (
                f"CI at n={n} [{entry['lower']:.4f}, {entry['upper']:.4f}] "
                f"does not contain true mean 0"
            )
