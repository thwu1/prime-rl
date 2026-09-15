
import pytest
import json
import os
import numpy as np
from scipy import special, optimize, stats

RTOL = 1e-6


# ===== Reference implementations =====

class RefTwoSidedNormalMixture:
    """Reference: Howard et al. (2021), Section 3.2."""

    def __init__(self, v_opt, alpha_opt):
        la = np.log(1.0 / alpha_opt)
        self.rho = v_opt / (2.0 * la + np.log(1.0 + 2.0 * la))

    def log_superMG(self, s, v):
        return 0.5 * np.log(self.rho / (v + self.rho)) + s ** 2 / (2.0 * (v + self.rho))

    def bound(self, v, log_threshold):
        return np.sqrt(
            (v + self.rho) * (np.log(1.0 + v / self.rho) + 2.0 * log_threshold)
        )


class RefOneSidedNormalMixture:
    """Reference: Howard et al. (2021), Section 3.3."""

    def __init__(self, v_opt, alpha_opt):
        # One-sided uses two-sided rho with doubled alpha
        self.rho = RefTwoSidedNormalMixture(v_opt, 2.0 * alpha_opt).rho

    def log_superMG(self, s, v):
        return (
            0.5 * np.log(4.0 * self.rho / (v + self.rho))
            + s ** 2 / (2.0 * (v + self.rho))
            + np.log(stats.norm.cdf(s / np.sqrt(v + self.rho)))
        )

    def bound(self, v, log_threshold):
        def root_fn(s):
            return self.log_superMG(s, v) - log_threshold

        s_upper = max(float(v), 1.0)
        for _ in range(50):
            if self.log_superMG(s_upper, v) > log_threshold:
                break
            s_upper *= 2.0
        if root_fn(s_upper) < 0:
            return s_upper
        return optimize.bisect(root_fn, 0.0, s_upper, xtol=2 ** -40)


class RefGammaExponentialMixture:
    """Reference: Howard et al. (2021), Section 4."""

    def __init__(self, v_opt, alpha_opt, c):
        self.rho = RefOneSidedNormalMixture(v_opt, alpha_opt).rho
        self.c = c
        rho_c_sq = self.rho / (c * c)
        self.leading_constant = (
            rho_c_sq * np.log(rho_c_sq)
            - special.gammaln(rho_c_sq)
            - np.log(special.gammainc(rho_c_sq, rho_c_sq))
        )

    def log_superMG(self, s, v):
        c_sq = self.c ** 2
        cs_v_csq = (self.c * s + v) / c_sq
        v_rho_csq = (v + self.rho) / c_sq
        return (
            self.leading_constant
            + special.gammaln(v_rho_csq)
            + np.log(special.gammainc(v_rho_csq, cs_v_csq + self.rho / c_sq))
            - v_rho_csq * np.log(cs_v_csq + self.rho / c_sq)
            + cs_v_csq
        )

    def bound(self, v, log_threshold):
        def root_fn(s):
            return self.log_superMG(s, v) - log_threshold

        s_upper = max(float(v), 1.0)
        for _ in range(50):
            if self.log_superMG(s_upper, v) > log_threshold:
                break
            s_upper *= 2.0
        if root_fn(s_upper) < 0:
            return s_upper
        return optimize.bisect(root_fn, 0.0, s_upper, xtol=2 ** -40)


# ===== Fixtures =====


@pytest.fixture(scope="module")
def results():
    with open("/app/results.json") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def problem():
    with open("/app/problem.json") as f:
        return json.load(f)


# ===== Structural Tests =====


class TestStructure:
    def test_results_file_exists(self):
        assert os.path.exists("/app/results.json"), "results.json not found at /app/"

    def test_all_parts_present(self, results):
        for part in ["part1", "part2", "part3", "part4", "part5"]:
            assert part in results, f"Missing {part} in results.json"

    def test_part1_keys(self, results):
        p1 = results["part1"]
        for family in ["two_sided_normal", "one_sided_normal", "gamma_exponential"]:
            assert family in p1, f"Missing {family} in part1"
            assert "rho" in p1[family], f"Missing rho in part1.{family}"
            assert "log_superMG_values" in p1[family], (
                f"Missing log_superMG_values in part1.{family}"
            )

    def test_part1_gamma_leading_constant(self, results):
        assert "leading_constant" in results["part1"]["gamma_exponential"]

    def test_part2_keys(self, results):
        p2 = results["part2"]
        assert "two_sided_normal_bounds" in p2
        assert "gamma_exponential_bounds" in p2

    def test_part2_comparison_keys(self, results):
        p2 = results["part2"]
        assert "tighter_family" in p2, "Missing tighter_family in part2"
        assert "crossover_detected" in p2, "Missing crossover_detected in part2"

    def test_part3_keys(self, results):
        p3 = results["part3"]
        for key in ["e_values_at_checkpoints", "reject_at_checkpoints", "first_rejection_time"]:
            assert key in p3, f"Missing {key} in part3"

    def test_part4_keys(self, results):
        p4 = results["part4"]
        for key in ["arithmetic_mean", "geometric_mean", "f_combination", "calibrated_p_values"]:
            assert key in p4, f"Missing {key} in part4"

    def test_part5_keys(self, results):
        p5 = results["part5"]
        for key in ["lower_bounds", "upper_bounds", "widths"]:
            assert key in p5, f"Missing {key} in part5"

    def test_array_lengths(self, results, problem):
        n_eval = len(problem["part1_mixture_supermartingales"]["two_sided_normal"]["eval_points"])
        for family in ["two_sided_normal", "one_sided_normal", "gamma_exponential"]:
            assert len(results["part1"][family]["log_superMG_values"]) == n_eval

        n_v = len(problem["part2_mixture_bounds"]["two_sided_normal"]["v_values"])
        assert len(results["part2"]["two_sided_normal_bounds"]) == n_v
        assert len(results["part2"]["gamma_exponential_bounds"]) == n_v
        assert len(results["part2"]["tighter_family"]) == n_v

        n_cp3 = len(problem["part3_sequential_test"]["checkpoints"])
        assert len(results["part3"]["e_values_at_checkpoints"]) == n_cp3
        assert len(results["part3"]["reject_at_checkpoints"]) == n_cp3

        n_sets = len(problem["part4_evalue_merging"]["sets"])
        assert len(results["part4"]["arithmetic_mean"]) == n_sets
        assert len(results["part4"]["geometric_mean"]) == n_sets
        assert len(results["part4"]["f_combination"]) == n_sets
        assert len(results["part4"]["calibrated_p_values"]) == n_sets

        n_cp5 = len(problem["part5_confidence_sequence"]["checkpoints"])
        assert len(results["part5"]["lower_bounds"]) == n_cp5
        assert len(results["part5"]["upper_bounds"]) == n_cp5
        assert len(results["part5"]["widths"]) == n_cp5


# ===== Part 1: Mixture Supermartingale Values =====


class TestPart1TwoSidedNormal:
    def test_rho(self, results, problem):
        cfg = problem["part1_mixture_supermartingales"]["two_sided_normal"]
        ref = RefTwoSidedNormalMixture(cfg["v_opt"], cfg["alpha_opt"])
        actual = results["part1"]["two_sided_normal"]["rho"]
        np.testing.assert_allclose(actual, ref.rho, rtol=RTOL)

    def test_log_superMG_values(self, results, problem):
        cfg = problem["part1_mixture_supermartingales"]["two_sided_normal"]
        ref = RefTwoSidedNormalMixture(cfg["v_opt"], cfg["alpha_opt"])
        expected = [ref.log_superMG(pt[0], pt[1]) for pt in cfg["eval_points"]]
        actual = results["part1"]["two_sided_normal"]["log_superMG_values"]
        np.testing.assert_allclose(actual, expected, rtol=RTOL)

    def test_log_superMG_nonnegative_at_zero(self, problem):
        """log_superMG(0, v) should be non-positive (M(0,v) <= 1)."""
        cfg = problem["part1_mixture_supermartingales"]["two_sided_normal"]
        ref = RefTwoSidedNormalMixture(cfg["v_opt"], cfg["alpha_opt"])
        for v in [10.0, 50.0, 100.0, 500.0]:
            assert ref.log_superMG(0, v) <= 1e-12, (
                f"log_superMG(0, {v}) should be <= 0"
            )


class TestPart1OneSidedNormal:
    def test_rho(self, results, problem):
        cfg = problem["part1_mixture_supermartingales"]["one_sided_normal"]
        ref = RefOneSidedNormalMixture(cfg["v_opt"], cfg["alpha_opt"])
        actual = results["part1"]["one_sided_normal"]["rho"]
        np.testing.assert_allclose(actual, ref.rho, rtol=RTOL)

    def test_log_superMG_values(self, results, problem):
        cfg = problem["part1_mixture_supermartingales"]["one_sided_normal"]
        ref = RefOneSidedNormalMixture(cfg["v_opt"], cfg["alpha_opt"])
        expected = [ref.log_superMG(pt[0], pt[1]) for pt in cfg["eval_points"]]
        actual = results["part1"]["one_sided_normal"]["log_superMG_values"]
        np.testing.assert_allclose(actual, expected, rtol=RTOL)

    def test_rho_relation_to_twosided(self, problem):
        """OneSidedNormal rho should equal TwoSidedNormal rho at doubled alpha."""
        cfg = problem["part1_mixture_supermartingales"]["one_sided_normal"]
        osn = RefOneSidedNormalMixture(cfg["v_opt"], cfg["alpha_opt"])
        tsn_doubled = RefTwoSidedNormalMixture(cfg["v_opt"], 2 * cfg["alpha_opt"])
        np.testing.assert_allclose(osn.rho, tsn_doubled.rho, rtol=1e-12)


class TestPart1GammaExponential:
    def test_rho(self, results, problem):
        cfg = problem["part1_mixture_supermartingales"]["gamma_exponential"]
        ref = RefGammaExponentialMixture(cfg["v_opt"], cfg["alpha_opt"], cfg["c"])
        actual = results["part1"]["gamma_exponential"]["rho"]
        np.testing.assert_allclose(actual, ref.rho, rtol=RTOL)

    def test_leading_constant(self, results, problem):
        cfg = problem["part1_mixture_supermartingales"]["gamma_exponential"]
        ref = RefGammaExponentialMixture(cfg["v_opt"], cfg["alpha_opt"], cfg["c"])
        actual = results["part1"]["gamma_exponential"]["leading_constant"]
        np.testing.assert_allclose(actual, ref.leading_constant, rtol=RTOL)

    def test_log_superMG_values(self, results, problem):
        cfg = problem["part1_mixture_supermartingales"]["gamma_exponential"]
        ref = RefGammaExponentialMixture(cfg["v_opt"], cfg["alpha_opt"], cfg["c"])
        expected = [ref.log_superMG(pt[0], pt[1]) for pt in cfg["eval_points"]]
        actual = results["part1"]["gamma_exponential"]["log_superMG_values"]
        np.testing.assert_allclose(actual, expected, rtol=RTOL)

    def test_rho_matches_onesided(self, problem):
        """GammaExponential rho should match OneSidedNormal rho."""
        cfg = problem["part1_mixture_supermartingales"]["gamma_exponential"]
        ge = RefGammaExponentialMixture(cfg["v_opt"], cfg["alpha_opt"], cfg["c"])
        osn = RefOneSidedNormalMixture(cfg["v_opt"], cfg["alpha_opt"])
        np.testing.assert_allclose(ge.rho, osn.rho, rtol=1e-12)


# ===== Part 2: Mixture Bounds =====


class TestPart2Bounds:
    def test_two_sided_normal_bounds(self, results, problem):
        cfg = problem["part2_mixture_bounds"]["two_sided_normal"]
        ref = RefTwoSidedNormalMixture(cfg["v_opt"], cfg["alpha_opt"])
        log_thresh = np.log(1.0 / cfg["alpha"])
        expected = [ref.bound(v, log_thresh) for v in cfg["v_values"]]
        actual = results["part2"]["two_sided_normal_bounds"]
        np.testing.assert_allclose(actual, expected, rtol=RTOL)

    def test_gamma_exponential_bounds(self, results, problem):
        cfg = problem["part2_mixture_bounds"]["gamma_exponential"]
        ref = RefGammaExponentialMixture(cfg["v_opt"], cfg["alpha_opt"], cfg["c"])
        log_thresh = np.log(1.0 / cfg["alpha"])
        expected = [ref.bound(v, log_thresh) for v in cfg["v_values"]]
        actual = results["part2"]["gamma_exponential_bounds"]
        np.testing.assert_allclose(actual, expected, rtol=RTOL)

    def test_two_sided_bounds_increasing(self, results):
        bounds = results["part2"]["two_sided_normal_bounds"]
        for i in range(len(bounds) - 1):
            assert bounds[i] < bounds[i + 1], (
                f"TwoSidedNormal bound not increasing: {bounds[i]} >= {bounds[i+1]}"
            )

    def test_gamma_exponential_bounds_increasing(self, results):
        bounds = results["part2"]["gamma_exponential_bounds"]
        for i in range(len(bounds) - 1):
            assert bounds[i] < bounds[i + 1], (
                f"GammaExponential bound not increasing: {bounds[i]} >= {bounds[i+1]}"
            )

    def test_bounds_positive(self, results):
        for key in ["two_sided_normal_bounds", "gamma_exponential_bounds"]:
            for val in results["part2"][key]:
                assert val > 0, f"Bound value must be positive, got {val} in {key}"

    def test_tighter_family(self, results, problem):
        """tighter_family should correctly identify which family produces the smaller bound."""
        cfg_tsn = problem["part2_mixture_bounds"]["two_sided_normal"]
        cfg_ge = problem["part2_mixture_bounds"]["gamma_exponential"]

        ref_tsn = RefTwoSidedNormalMixture(cfg_tsn["v_opt"], cfg_tsn["alpha_opt"])
        ref_ge = RefGammaExponentialMixture(cfg_ge["v_opt"], cfg_ge["alpha_opt"], cfg_ge["c"])

        log_thresh_tsn = np.log(1.0 / cfg_tsn["alpha"])
        log_thresh_ge = np.log(1.0 / cfg_ge["alpha"])

        for i, v in enumerate(cfg_tsn["v_values"]):
            tsn_b = ref_tsn.bound(v, log_thresh_tsn)
            ge_b = ref_ge.bound(v, log_thresh_ge)
            expected = "two_sided_normal" if tsn_b <= ge_b else "gamma_exponential"
            actual = results["part2"]["tighter_family"][i]
            assert actual == expected, (
                f"tighter_family mismatch at v={v}: got {actual}, expected {expected}"
            )

    def test_tighter_family_values(self, results):
        for val in results["part2"]["tighter_family"]:
            assert val in ("two_sided_normal", "gamma_exponential"), (
                f"Invalid tighter_family value: {val}"
            )

    def test_crossover_detected(self, results):
        """crossover_detected should be True iff tighter family differs across v_values."""
        tighter = results["part2"]["tighter_family"]
        expected = len(set(tighter)) > 1
        actual = results["part2"]["crossover_detected"]
        assert actual == expected, (
            f"crossover_detected: got {actual}, expected {expected}"
        )


# ===== Part 3: Sequential Mean Test =====


class TestPart3SequentialTest:
    def _generate_data(self, problem):
        cfg = problem["part3_sequential_test"]
        rng = np.random.default_rng(cfg["seed"])
        return rng.normal(cfg["true_mean"], cfg["true_std"], cfg["n_observations"]), cfg

    def test_e_values_at_checkpoints(self, results, problem):
        data, cfg = self._generate_data(problem)
        ref = RefTwoSidedNormalMixture(cfg["v_opt"], cfg["alpha_opt"])

        for i, cp in enumerate(cfg["checkpoints"]):
            s_t = float(np.sum(data[:cp] - cfg["null_value"]))
            v_t = float(cp)
            expected = float(np.exp(ref.log_superMG(s_t, v_t)))
            actual = results["part3"]["e_values_at_checkpoints"][i]
            np.testing.assert_allclose(
                actual, expected, rtol=RTOL,
                err_msg=f"E-value mismatch at checkpoint t={cp}"
            )

    def test_reject_at_checkpoints(self, results, problem):
        data, cfg = self._generate_data(problem)
        ref = RefTwoSidedNormalMixture(cfg["v_opt"], cfg["alpha_opt"])

        for i, cp in enumerate(cfg["checkpoints"]):
            s_t = float(np.sum(data[:cp] - cfg["null_value"]))
            v_t = float(cp)
            e_val = np.exp(ref.log_superMG(s_t, v_t))
            expected = bool(e_val >= 1.0 / cfg["alpha"])
            actual = results["part3"]["reject_at_checkpoints"][i]
            assert actual == expected, f"Rejection mismatch at checkpoint t={cp}"

    def test_first_rejection_time(self, results, problem):
        data, cfg = self._generate_data(problem)
        ref = RefTwoSidedNormalMixture(cfg["v_opt"], cfg["alpha_opt"])

        expected_frt = None
        for t in range(1, cfg["n_observations"] + 1):
            s_t = float(np.sum(data[:t] - cfg["null_value"]))
            v_t = float(t)
            e_t = np.exp(ref.log_superMG(s_t, v_t))
            if e_t >= 1.0 / cfg["alpha"]:
                expected_frt = t
                break

        actual = results["part3"]["first_rejection_time"]
        assert actual == expected_frt, (
            f"First rejection time: got {actual}, expected {expected_frt}"
        )

    def test_e_values_positive(self, results):
        for val in results["part3"]["e_values_at_checkpoints"]:
            assert val > 0, f"E-value must be positive, got {val}"

    def test_e_values_increase_with_signal(self, results, problem):
        """With positive true_mean and null_value=0, e-values should generally grow."""
        cfg = problem["part3_sequential_test"]
        if cfg["true_mean"] > cfg["null_value"]:
            evals = results["part3"]["e_values_at_checkpoints"]
            # Last checkpoint e-value should exceed first
            assert evals[-1] > evals[0], (
                "E-values should grow when true mean differs from null"
            )


# ===== Part 4: E-value Merging =====


class TestPart4Merging:
    def test_arithmetic_mean(self, results, problem):
        for i, ev_set in enumerate(problem["part4_evalue_merging"]["sets"]):
            expected = float(np.mean(ev_set))
            actual = results["part4"]["arithmetic_mean"][i]
            np.testing.assert_allclose(
                actual, expected, rtol=RTOL,
                err_msg=f"Arithmetic mean mismatch for set {i}"
            )

    def test_geometric_mean(self, results, problem):
        for i, ev_set in enumerate(problem["part4_evalue_merging"]["sets"]):
            ev = np.array(ev_set)
            expected = float(np.exp(np.mean(np.log(ev))))
            actual = results["part4"]["geometric_mean"][i]
            np.testing.assert_allclose(
                actual, expected, rtol=RTOL,
                err_msg=f"Geometric mean mismatch for set {i}"
            )

    def test_f_combination(self, results, problem):
        for i, ev_set in enumerate(problem["part4_evalue_merging"]["sets"]):
            K = len(ev_set)
            expected = float(K * min(ev_set))
            actual = results["part4"]["f_combination"][i]
            np.testing.assert_allclose(
                actual, expected, rtol=RTOL,
                err_msg=f"F-combination mismatch for set {i}"
            )

    def test_calibrated_p_values(self, results, problem):
        for i, ev_set in enumerate(problem["part4_evalue_merging"]["sets"]):
            arith = float(np.mean(ev_set))
            expected = float(min(1.0, 1.0 / arith))
            actual = results["part4"]["calibrated_p_values"][i]
            np.testing.assert_allclose(
                actual, expected, rtol=RTOL,
                err_msg=f"Calibrated p-value mismatch for set {i}"
            )

    def test_arithmetic_mean_nonnegative(self, results):
        for val in results["part4"]["arithmetic_mean"]:
            assert val >= 0, "Arithmetic mean of e-values must be non-negative"

    def test_geometric_mean_nonnegative(self, results):
        for val in results["part4"]["geometric_mean"]:
            assert val >= 0, "Geometric mean of e-values must be non-negative"

    def test_calibrated_p_in_unit_interval(self, results):
        for val in results["part4"]["calibrated_p_values"]:
            assert 0 <= val <= 1.0, f"Calibrated p-value must be in [0,1], got {val}"

    def test_unit_evalues_merge_to_one(self, results, problem):
        """All-ones e-values should merge to exactly 1.0 for all methods."""
        sets = problem["part4_evalue_merging"]["sets"]
        # Find the set that is all ones
        for i, ev_set in enumerate(sets):
            if all(v == 1.0 for v in ev_set):
                np.testing.assert_allclose(
                    results["part4"]["arithmetic_mean"][i], 1.0, rtol=RTOL
                )
                np.testing.assert_allclose(
                    results["part4"]["geometric_mean"][i], 1.0, rtol=RTOL
                )
                K = len(ev_set)
                np.testing.assert_allclose(
                    results["part4"]["f_combination"][i], float(K), rtol=RTOL
                )


# ===== Part 5: Confidence Sequences =====


class TestPart5ConfidenceSequence:
    def _generate_data(self, problem):
        cfg = problem["part5_confidence_sequence"]
        rng = np.random.default_rng(cfg["seed"])
        return rng.normal(cfg["true_mean"], cfg["true_std"], cfg["n_observations"]), cfg

    def test_bounds_values(self, results, problem):
        data, cfg = self._generate_data(problem)
        # Two-sided CI: use alpha_opt/2 for mixture, log_threshold = log(2/alpha)
        ref = RefGammaExponentialMixture(cfg["v_opt"], cfg["alpha_opt"] / 2.0, cfg["c"])

        for i, cp in enumerate(cfg["checkpoints"]):
            obs = data[:cp]
            n = len(obs)
            x_bar = float(np.mean(obs))
            emp_var = float(np.var(obs, ddof=1))
            intrinsic_time = n * emp_var
            log_thresh = np.log(2.0 / cfg["alpha"])
            bnd = ref.bound(intrinsic_time, log_thresh)
            radius = bnd / n

            np.testing.assert_allclose(
                results["part5"]["lower_bounds"][i],
                x_bar - radius, rtol=RTOL,
                err_msg=f"Lower bound mismatch at checkpoint t={cp}"
            )
            np.testing.assert_allclose(
                results["part5"]["upper_bounds"][i],
                x_bar + radius, rtol=RTOL,
                err_msg=f"Upper bound mismatch at checkpoint t={cp}"
            )
            np.testing.assert_allclose(
                results["part5"]["widths"][i],
                2.0 * radius, rtol=RTOL,
                err_msg=f"Width mismatch at checkpoint t={cp}"
            )

    def test_lower_less_than_upper(self, results, problem):
        cfg = problem["part5_confidence_sequence"]
        for i, cp in enumerate(cfg["checkpoints"]):
            lower = results["part5"]["lower_bounds"][i]
            upper = results["part5"]["upper_bounds"][i]
            assert lower < upper, (
                f"Lower bound {lower} >= upper bound {upper} at checkpoint t={cp}"
            )

    def test_widths_consistent(self, results, problem):
        """Width should equal upper - lower."""
        cfg = problem["part5_confidence_sequence"]
        for i, cp in enumerate(cfg["checkpoints"]):
            width = results["part5"]["widths"][i]
            diff = results["part5"]["upper_bounds"][i] - results["part5"]["lower_bounds"][i]
            np.testing.assert_allclose(
                width, diff, rtol=RTOL,
                err_msg=f"Width inconsistent at checkpoint t={cp}"
            )

    def test_widths_eventually_shrink(self, results):
        """Confidence intervals should narrow as sample size grows."""
        widths = results["part5"]["widths"]
        assert widths[-1] < widths[0], (
            f"Width at last checkpoint ({widths[-1]}) should be less than "
            f"first ({widths[0]})"
        )

    def test_widths_positive(self, results):
        for val in results["part5"]["widths"]:
            assert val > 0, f"Width must be positive, got {val}"
