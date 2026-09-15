
import json
import numpy as np
import pytest
import lmo
from scipy.stats import genextreme

TRUE_SHAPE = -0.05
TRUE_LOC = 100.0
TRUE_SCALE = 30.0


@pytest.fixture
def data():
    return np.load("/app/data.npy")


@pytest.fixture
def results():
    with open("/app/results.json") as f:
        return json.load(f)


# ---------- Structure tests ----------


class TestStructure:
    def test_l_stats_keys(self, results):
        assert "l_stats" in results
        for key in ["trim_00", "trim_11", "trim_22"]:
            assert key in results["l_stats"], f"Missing l_stats.{key}"
            assert len(results["l_stats"][key]) == 4, f"l_stats.{key} should have 4 elements"

    def test_gev_fits_keys(self, results):
        assert "gev_fits" in results
        for key in ["trim_00", "trim_11", "trim_22"]:
            assert key in results["gev_fits"], f"Missing gev_fits.{key}"
            fit = results["gev_fits"][key]
            for param in ["shape", "loc", "scale"]:
                assert param in fit, f"Missing gev_fits.{key}.{param}"
                assert isinstance(fit[param], (int, float)), f"gev_fits.{key}.{param} must be numeric"

    def test_return_levels_keys(self, results):
        assert "return_levels" in results
        for key in ["trim_00_100yr", "trim_11_100yr", "trim_22_100yr", "trim_11_1000yr"]:
            assert key in results["return_levels"], f"Missing return_levels.{key}"

    def test_covariance_key(self, results):
        assert "l_moment_cov_trim_11" in results

    def test_theoretical_l_stats_key(self, results):
        assert "theoretical_l_stats_trim_11" in results
        tls = results["theoretical_l_stats_trim_11"]
        assert len(tls) == 4, "theoretical_l_stats_trim_11 should have 4 elements"

    def test_nonparametric_key(self, results):
        assert "nonparametric_rl_100yr" in results

    def test_influence_keys(self, results):
        assert "influence_diagnostics" in results
        diag = results["influence_diagnostics"]
        assert "gross_error_sensitivity_tau3" in diag
        assert "rejection_point_tau3" in diag


# ---------- Anti-cheat: independently verify L-stats ----------


class TestLStatsAntiCheat:
    """Independently compute L-stats from data and compare with reported values."""

    def test_l_stats_trim_00(self, results, data):
        ref = lmo.l_stats(data, trim=(0, 0))
        reported = np.array(results["l_stats"]["trim_00"], dtype=float)
        np.testing.assert_allclose(reported, ref, rtol=1e-3, atol=1e-6)

    def test_l_stats_trim_11(self, results, data):
        ref = lmo.l_stats(data, trim=(1, 1))
        reported = np.array(results["l_stats"]["trim_11"], dtype=float)
        np.testing.assert_allclose(reported, ref, rtol=1e-3, atol=1e-6)

    def test_l_stats_trim_22(self, results, data):
        ref = lmo.l_stats(data, trim=(2, 2))
        reported = np.array(results["l_stats"]["trim_22"], dtype=float)
        np.testing.assert_allclose(reported, ref, rtol=1e-3, atol=1e-6)


# ---------- Trimming effect ----------


class TestTrimmingEffect:
    def test_untrimmed_l_loc_inflated(self, results):
        """Contamination at high values inflates untrimmed L-location."""
        l1_00 = results["l_stats"]["trim_00"][0]
        l1_11 = results["l_stats"]["trim_11"][0]
        assert l1_00 > l1_11, "Untrimmed L-location should exceed trimmed due to contamination"

    def test_trimmed_fit_closer_to_true(self, results):
        """Trimmed GEV fit should be closer to true parameters than untrimmed."""
        fit_00 = results["gev_fits"]["trim_00"]
        fit_11 = results["gev_fits"]["trim_11"]

        dist_00 = (
            abs(fit_00["shape"] - TRUE_SHAPE)
            + abs(fit_00["loc"] - TRUE_LOC) / TRUE_LOC
            + abs(fit_00["scale"] - TRUE_SCALE) / TRUE_SCALE
        )
        dist_11 = (
            abs(fit_11["shape"] - TRUE_SHAPE)
            + abs(fit_11["loc"] - TRUE_LOC) / TRUE_LOC
            + abs(fit_11["scale"] - TRUE_SCALE) / TRUE_SCALE
        )
        assert dist_11 < dist_00, (
            f"Trimmed fit distance {dist_11:.4f} should be less than "
            f"untrimmed distance {dist_00:.4f}"
        )


# ---------- GEV fit quality ----------


class TestGEVFitQuality:
    def test_trimmed_shape_range(self, results):
        shape = results["gev_fits"]["trim_11"]["shape"]
        assert -0.60 < shape < 0.20, f"Trimmed shape {shape} outside expected range"

    def test_trimmed_loc_range(self, results):
        loc = results["gev_fits"]["trim_11"]["loc"]
        assert 60 < loc < 160, f"Trimmed loc {loc} outside expected range"

    def test_trimmed_scale_range(self, results):
        scale = results["gev_fits"]["trim_11"]["scale"]
        assert 10 < scale < 70, f"Trimmed scale {scale} outside expected range"


# ---------- Return level consistency ----------


class TestReturnLevels:
    def test_return_levels_match_fit(self, results):
        """Return levels must be consistent with reported GEV parameters."""
        for trim_name in ["trim_00", "trim_11", "trim_22"]:
            fit = results["gev_fits"][trim_name]
            dist = genextreme(c=fit["shape"], loc=fit["loc"], scale=fit["scale"])
            expected_rl = dist.ppf(0.99)
            reported_rl = results["return_levels"][f"{trim_name}_100yr"]
            np.testing.assert_allclose(
                reported_rl, expected_rl, rtol=1e-3,
                err_msg=f"100yr RL mismatch for {trim_name}"
            )

    def test_1000yr_matches_fit(self, results):
        fit = results["gev_fits"]["trim_11"]
        dist = genextreme(c=fit["shape"], loc=fit["loc"], scale=fit["scale"])
        expected = dist.ppf(0.999)
        reported = results["return_levels"]["trim_11_1000yr"]
        np.testing.assert_allclose(reported, expected, rtol=1e-3)

    def test_1000yr_greater_than_100yr(self, results):
        rl_100 = results["return_levels"]["trim_11_100yr"]
        rl_1000 = results["return_levels"]["trim_11_1000yr"]
        assert rl_1000 > rl_100

    def test_trimmed_100yr_range(self, results):
        rl = results["return_levels"]["trim_11_100yr"]
        assert 100 < rl < 800, f"Trimmed 100yr RL {rl} outside expected range"


# ---------- Covariance matrix ----------


class TestCovarianceMatrix:
    def test_dimensions(self, results):
        cov = np.array(results["l_moment_cov_trim_11"])
        assert cov.shape == (4, 4), f"Covariance shape {cov.shape} should be (4, 4)"

    def test_symmetric(self, results):
        cov = np.array(results["l_moment_cov_trim_11"])
        np.testing.assert_allclose(cov, cov.T, atol=1e-10)

    def test_positive_semidefinite(self, results):
        cov = np.array(results["l_moment_cov_trim_11"])
        eigvals = np.linalg.eigvalsh(cov)
        assert np.all(eigvals >= -1e-10), f"Negative eigenvalue found: {eigvals.min()}"

    def test_diagonal_positive(self, results):
        cov = np.array(results["l_moment_cov_trim_11"])
        assert np.all(np.diag(cov) > 0), "Diagonal elements must be positive"


# ---------- Theoretical L-stats verification ----------


class TestTheoreticalLStats:
    """Verify theoretical L-stats from the fitted GEV against independently computed values."""

    def test_l1_reasonable(self, results):
        l1 = results["theoretical_l_stats_trim_11"][0]
        assert 50 < l1 < 250, f"Theoretical L1 {l1} outside expected range"

    def test_l2_positive(self, results):
        l2 = results["theoretical_l_stats_trim_11"][1]
        assert l2 > 0, "Theoretical L2 must be positive"

    def test_tau3_close_to_sample(self, results):
        """Theoretical tau3 should be close to sample tau3 for a well-fitting model."""
        theo_tau3 = results["theoretical_l_stats_trim_11"][2]
        sample_tau3 = results["l_stats"]["trim_11"][2]
        assert abs(theo_tau3 - sample_tau3) < 0.15, (
            f"Theoretical tau3 ({theo_tau3:.4f}) too far from "
            f"sample tau3 ({sample_tau3:.4f})"
        )

    def test_tau4_close_to_sample(self, results):
        """Theoretical tau4 should be close to sample tau4 for a well-fitting model."""
        theo_tau4 = results["theoretical_l_stats_trim_11"][3]
        sample_tau4 = results["l_stats"]["trim_11"][3]
        assert abs(theo_tau4 - sample_tau4) < 0.15, (
            f"Theoretical tau4 ({theo_tau4:.4f}) too far from "
            f"sample tau4 ({sample_tau4:.4f})"
        )

    def test_independently_computed(self, results):
        """Anti-cheat: independently recompute theoretical L-stats from reported GEV fit."""
        fit = results["gev_fits"]["trim_11"]
        rv = genextreme(c=fit["shape"], loc=fit["loc"], scale=fit["scale"])
        theo_lm = np.array([
            float(rv.l_moment(r, trim=(1, 1)))
            for r in range(1, 5)
        ])
        expected = [
            float(theo_lm[0]),
            float(theo_lm[1]),
            float(theo_lm[2] / theo_lm[1]),
            float(theo_lm[3] / theo_lm[1]),
        ]
        reported = results["theoretical_l_stats_trim_11"]
        np.testing.assert_allclose(reported, expected, rtol=1e-2)


# ---------- Nonparametric reconstruction ----------


class TestNonparametric:
    def test_value_positive(self, results):
        rl = results["nonparametric_rl_100yr"]
        assert rl > 0, "Nonparametric 100yr RL must be positive"

    def test_reasonable_range(self, results):
        rl = results["nonparametric_rl_100yr"]
        assert 50 < rl < 1000, f"Nonparametric 100yr RL {rl} outside plausible range"

    def test_close_to_parametric(self, results):
        np_rl = results["nonparametric_rl_100yr"]
        p_rl = results["return_levels"]["trim_11_100yr"]
        ratio = np_rl / p_rl
        assert 0.3 < ratio < 3.0, (
            f"Nonparametric RL ({np_rl:.1f}) too far from "
            f"parametric RL ({p_rl:.1f}), ratio={ratio:.2f}"
        )


# ---------- Influence diagnostics ----------


class TestInfluenceDiagnostics:
    def test_ges_positive(self, results):
        ges = results["influence_diagnostics"]["gross_error_sensitivity_tau3"]
        assert ges > 0, "Gross-error sensitivity must be positive"

    def test_ges_finite(self, results):
        ges = results["influence_diagnostics"]["gross_error_sensitivity_tau3"]
        assert np.isfinite(ges), "Gross-error sensitivity must be finite for trimmed L-moments"

    def test_rejection_point_positive_or_nan(self, results):
        """Rejection point should be positive (ideally finite for trimmed L-moments,
        but numerical issues can produce nan in some environments)."""
        rp = results["influence_diagnostics"]["rejection_point_tau3"]
        if np.isfinite(rp):
            assert rp > 0, "Rejection point must be positive when finite"

    def test_rejection_point_bounded(self, results):
        rp = results["influence_diagnostics"]["rejection_point_tau3"]
        if np.isfinite(rp):
            assert rp < 10000, f"Rejection point {rp} seems unreasonably large"
