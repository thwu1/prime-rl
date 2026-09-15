
"""
Verification tests for robust extreme value analysis pipeline.
Validates the structure and statistical properties of results.json
produced by the agent's pipeline.
"""

import json
import math
import pytest

RESULTS_PATH = '/app/results.json'


@pytest.fixture(scope='module')
def results():
    with open(RESULTS_PATH) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------
class TestSchema:
    def test_top_level_keys(self, results):
        for key in ['l_stats', 'fits', 'best_model', 'return_levels',
                     'l_comoment', 'influence']:
            assert key in results, f"Missing top-level key: {key}"

    def test_l_stats_structure(self, results):
        for trim in ['trim_0_0', 'trim_1_1', 'trim_2_2']:
            assert trim in results['l_stats'], f"Missing l_stats key: {trim}"
            for stat in ['l_loc', 'l_scale', 'l_skew', 'l_kurt']:
                assert stat in results['l_stats'][trim], \
                    f"Missing {stat} in l_stats[{trim}]"

    def test_fits_structure(self, results):
        for dist in ['gev', 'gumbel']:
            assert dist in results['fits'], f"Missing fit: {dist}"
            for field in ['params', 'j_test_pvalue', 'aicc']:
                assert field in results['fits'][dist], \
                    f"Missing {field} in fits[{dist}]"

    def test_return_levels_structure(self, results):
        for model in ['best_model', 'l_poly']:
            assert model in results['return_levels'], \
                f"Missing return_levels key: {model}"
            for rl in ['rl_100', 'rl_1000']:
                assert rl in results['return_levels'][model], \
                    f"Missing {rl} in return_levels[{model}]"

    def test_l_comoment_structure(self, results):
        for key in ['l_corr', 'l_coscale']:
            assert key in results['l_comoment'], \
                f"Missing l_comoment key: {key}"

    def test_influence_structure(self, results):
        assert 'eval_points' in results['influence']
        assert 'values' in results['influence']


# ---------------------------------------------------------------------------
# L-statistic property tests
# ---------------------------------------------------------------------------
class TestLStatistics:
    def test_l_skewness_bounds(self, results):
        """L-skewness (tau_3) must be in [-1, 1]."""
        for trim in ['trim_0_0', 'trim_1_1', 'trim_2_2']:
            skew = results['l_stats'][trim]['l_skew']
            assert -1 <= skew <= 1, \
                f"L-skew ({trim}) = {skew} out of [-1, 1]"

    def test_l_kurtosis_bounds(self, results):
        """L-kurtosis (tau_4) must be in (-1, 1)."""
        for trim in ['trim_0_0', 'trim_1_1', 'trim_2_2']:
            kurt = results['l_stats'][trim]['l_kurt']
            assert -1 < kurt < 1, \
                f"L-kurt ({trim}) = {kurt} out of (-1, 1)"

    def test_l_scale_positive(self, results):
        """L-scale (lambda_2) must be positive."""
        for trim in ['trim_0_0', 'trim_1_1', 'trim_2_2']:
            scale = results['l_stats'][trim]['l_scale']
            assert scale > 0, \
                f"L-scale ({trim}) = {scale} should be positive"

    def test_trimming_reduces_scale(self, results):
        """Trimming should reduce L-scale when data has outlier
        contamination, because outliers inflate variability."""
        scale_0 = results['l_stats']['trim_0_0']['l_scale']
        scale_1 = results['l_stats']['trim_1_1']['l_scale']
        assert scale_1 < scale_0, \
            (f"Expected trimmed L-scale ({scale_1}) < untrimmed ({scale_0}) "
             f"for contaminated data")

    def test_l_location_reasonable(self, results):
        """Trimmed L-location should be near the true GEV location."""
        l_loc = results['l_stats']['trim_1_1']['l_loc']
        assert 50 < l_loc < 200, \
            f"L-loc (trim 1,1) = {l_loc} is unreasonable"

    def test_l_stats_are_numeric(self, results):
        """All L-statistics must be finite numbers."""
        for trim in ['trim_0_0', 'trim_1_1', 'trim_2_2']:
            for stat in ['l_loc', 'l_scale', 'l_skew', 'l_kurt']:
                val = results['l_stats'][trim][stat]
                assert isinstance(val, (int, float)), \
                    f"{stat} ({trim}) is not numeric: {val}"
                assert math.isfinite(val), \
                    f"{stat} ({trim}) = {val} is not finite"


# ---------------------------------------------------------------------------
# Distribution fit tests
# ---------------------------------------------------------------------------
class TestFits:
    def test_gev_param_count(self, results):
        """GEV must have 3 parameters: shape (c), loc, scale."""
        assert len(results['fits']['gev']['params']) == 3

    def test_gumbel_param_count(self, results):
        """Gumbel must have 2 or 3 parameters.
        If 3, the shape parameter must be ~0."""
        params = results['fits']['gumbel']['params']
        if len(params) == 3:
            assert abs(params[0]) < 0.01, \
                f"Gumbel shape should be ~0, got {params[0]}"
        else:
            assert len(params) == 2

    def test_gev_shape_proximity(self, results):
        """GEV shape parameter should be close to the true value of -0.3.
        With (1,1) trimming and 500 samples, allow a wide but bounded
        tolerance."""
        c = results['fits']['gev']['params'][0]
        assert -0.7 < c < 0.05, \
            f"GEV shape {c} too far from true value -0.3"

    def test_gev_loc_proximity(self, results):
        """GEV loc should be in a reasonable range around the true value
        of 100."""
        loc = results['fits']['gev']['params'][1]
        assert 60 < loc < 150, \
            f"GEV loc {loc} too far from true value 100"

    def test_gev_scale_proximity(self, results):
        """GEV scale should be in a reasonable range around the true value
        of 30."""
        scale = results['fits']['gev']['params'][2]
        assert 10 < scale < 60, \
            f"GEV scale {scale} too far from true value 30"

    def test_j_test_pvalue_range(self, results):
        """J-test p-values must be in [0, 1]."""
        for dist in ['gev', 'gumbel']:
            pval = results['fits'][dist]['j_test_pvalue']
            assert 0 <= pval <= 1, \
                f"{dist} J-test p-value {pval} not in [0, 1]"

    def test_aicc_finite(self, results):
        """AICc values must be finite real numbers."""
        for dist in ['gev', 'gumbel']:
            aicc = results['fits'][dist]['aicc']
            assert math.isfinite(aicc), \
                f"{dist} AICc = {aicc} is not finite"

    def test_best_model_has_lowest_aicc(self, results):
        """The declared best_model must have the lowest AICc."""
        best = results['best_model']
        best_aicc = results['fits'][best]['aicc']
        for dist, fit_data in results['fits'].items():
            assert best_aicc <= fit_data['aicc'] + 1e-8, \
                (f"best_model={best} (AICc={best_aicc}) does not have "
                 f"lowest AICc; {dist} has {fit_data['aicc']}")

    def test_gev_preferred_over_gumbel(self, results):
        """The true distribution has nonzero shape (-0.3), so GEV should
        be preferred over Gumbel by AICc when AICc is computed from the
        profile negative log-likelihood."""
        assert results['fits']['gev']['aicc'] < results['fits']['gumbel']['aicc'], \
            "GEV should have lower AICc than Gumbel for this dataset"

    def test_best_model_valid(self, results):
        """best_model must be one of the fitted distributions."""
        assert results['best_model'] in results['fits']

    def test_aicc_in_loglik_range(self, results):
        """AICc from log-likelihood for this dataset should be in the
        thousands (not single-digit GMM-based values)."""
        for dist in ['gev', 'gumbel']:
            aicc = results['fits'][dist]['aicc']
            assert aicc > 100, \
                (f"{dist} AICc = {aicc} is suspiciously small; "
                 f"expected log-likelihood-based AICc in the thousands")


# ---------------------------------------------------------------------------
# Return level tests
# ---------------------------------------------------------------------------
class TestReturnLevels:
    def test_positive(self, results):
        """Return levels should be positive for this hydrological data."""
        for model in ['best_model', 'l_poly']:
            for rl_key in ['rl_100', 'rl_1000']:
                rl = results['return_levels'][model][rl_key]
                assert rl > 0, \
                    f"{model} {rl_key} = {rl} should be positive"

    def test_finite(self, results):
        """Return levels must be finite."""
        for model in ['best_model', 'l_poly']:
            for rl_key in ['rl_100', 'rl_1000']:
                rl = results['return_levels'][model][rl_key]
                assert math.isfinite(rl), \
                    f"{model} {rl_key} = {rl} is not finite"

    def test_monotonic(self, results):
        """1000-year return level must exceed 100-year return level."""
        for model in ['best_model', 'l_poly']:
            rl_100 = results['return_levels'][model]['rl_100']
            rl_1000 = results['return_levels'][model]['rl_1000']
            assert rl_1000 > rl_100, \
                (f"{model}: rl_1000 ({rl_1000}) should exceed "
                 f"rl_100 ({rl_100})")

    def test_best_model_rl_reasonable(self, results):
        """100-year return level from the best model should be in a
        reasonable hydrological range given the GEV(c=-0.3, loc=100,
        scale=30) generating process."""
        rl_100 = results['return_levels']['best_model']['rl_100']
        assert 100 < rl_100 < 500, \
            f"100-year RL = {rl_100} seems unreasonable"


# ---------------------------------------------------------------------------
# L-comoment tests
# ---------------------------------------------------------------------------
class TestLComoment:
    def test_l_corr_shape(self, results):
        """L-correlation matrix must be 2x2."""
        corr = results['l_comoment']['l_corr']
        assert len(corr) == 2 and len(corr[0]) == 2 and len(corr[1]) == 2

    def test_l_corr_diagonal_unity(self, results):
        """Diagonal of L-correlation matrix must equal 1."""
        corr = results['l_comoment']['l_corr']
        assert abs(corr[0][0] - 1.0) < 0.01, \
            f"l_corr[0,0] = {corr[0][0]}, expected 1.0"
        assert abs(corr[1][1] - 1.0) < 0.01, \
            f"l_corr[1,1] = {corr[1][1]}, expected 1.0"

    def test_l_corr_offdiag_bounds(self, results):
        """Off-diagonal L-correlation must be in [-1, 1]."""
        corr = results['l_comoment']['l_corr']
        assert -1 <= corr[0][1] <= 1, \
            f"l_corr[0,1] = {corr[0][1]} out of [-1, 1]"
        assert -1 <= corr[1][0] <= 1, \
            f"l_corr[1,0] = {corr[1][0]} out of [-1, 1]"

    def test_l_corr_positive(self, results):
        """Data has positive dependence; off-diagonal entries should be
        positive."""
        corr = results['l_comoment']['l_corr']
        assert corr[0][1] > 0, \
            f"l_corr[0,1] = {corr[0][1]}, expected positive"
        assert corr[1][0] > 0, \
            f"l_corr[1,0] = {corr[1][0]}, expected positive"

    def test_l_corr_asymmetric(self, results):
        """L-correlation matrix should be asymmetric because the two
        marginals are different GEV distributions."""
        corr = results['l_comoment']['l_corr']
        diff = abs(corr[0][1] - corr[1][0])
        assert diff > 0.001, \
            (f"L-correlation matrix should be asymmetric: "
             f"[0,1]={corr[0][1]}, [1,0]={corr[1][0]}, diff={diff}")

    def test_l_coscale_shape(self, results):
        """L-coscale matrix must be 2x2."""
        cs = results['l_comoment']['l_coscale']
        assert len(cs) == 2 and len(cs[0]) == 2 and len(cs[1]) == 2

    def test_l_coscale_diagonal_positive(self, results):
        """Diagonal of L-coscale (univariate L-scale) must be positive."""
        cs = results['l_comoment']['l_coscale']
        assert cs[0][0] > 0, \
            f"l_coscale[0,0] = {cs[0][0]} should be positive"
        assert cs[1][1] > 0, \
            f"l_coscale[1,1] = {cs[1][1]} should be positive"


# ---------------------------------------------------------------------------
# Influence function tests
# ---------------------------------------------------------------------------
class TestInfluence:
    def test_count(self, results):
        """Must have exactly 20 evaluation points and 20 values."""
        assert len(results['influence']['eval_points']) == 20
        assert len(results['influence']['values']) == 20

    def test_finite(self, results):
        """All influence function values must be finite."""
        for i, v in enumerate(results['influence']['values']):
            assert math.isfinite(v), \
                f"Influence value at index {i} = {v} is not finite"

    def test_points_sorted(self, results):
        """Evaluation points must be in ascending order."""
        pts = results['influence']['eval_points']
        for i in range(len(pts) - 1):
            assert pts[i] < pts[i + 1], \
                f"eval_points not sorted at index {i}: {pts[i]} >= {pts[i+1]}"

    def test_not_constant(self, results):
        """Influence function should vary across the data range."""
        vals = results['influence']['values']
        assert max(vals) - min(vals) > 1e-10, \
            "Influence function appears constant"

    def test_eval_points_span_data(self, results):
        """Evaluation points should span a wide range (not degenerate)."""
        pts = results['influence']['eval_points']
        span = pts[-1] - pts[0]
        assert span > 10, \
            f"Evaluation point span = {span} is too narrow"
