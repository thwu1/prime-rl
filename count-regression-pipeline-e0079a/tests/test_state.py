
"""
Tests for count regression model comparison pipeline.
Reference values from Stata 11 (tpoisson/tnbreg) and R pscl::hurdle(),
cross-validated in the statsmodels validation corpus.
Conditional means E[Y|Y>c] computed from Stata reference parameters
at estimation-sample covariate means.
"""

import json
import os

import numpy as np
import pytest


@pytest.fixture(scope="module")
def results():
    path = "/app/results.json"
    assert os.path.exists(path), f"Results file {path} does not exist"
    with open(path) as f:
        data = json.load(f)
    return data


# -- Truncated Poisson, truncation = 0 ----------------------------------------

class TestTruncPoisson0:
    """Zero-truncated Poisson validated against Stata tpoisson."""

    PARAMS = {"aget": 0.01227632422998, "totchr": 0.20994371600381, "const": 1.5417559978312}
    BSE = {"aget": 0.00504328169164, "totchr": 0.00449374445996, "const": 0.01547272444235}
    LLF = -12557.82361740294
    AIC = 25121.647234806
    N_OBS = 3237
    COND_MEAN_ATMEANS = 7.2482494599573

    def test_params(self, results):
        r = results["trunc_poisson_0"]["params"]
        for key, expected in self.PARAMS.items():
            assert key in r, f"Missing param '{key}'"
            np.testing.assert_allclose(r[key], expected, atol=1e-3,
                                       err_msg=f"trunc_poisson_0 param {key}")

    def test_bse(self, results):
        r = results["trunc_poisson_0"]["bse"]
        for key, expected in self.BSE.items():
            assert key in r, f"Missing bse '{key}'"
            np.testing.assert_allclose(r[key], expected, atol=1e-3,
                                       err_msg=f"trunc_poisson_0 bse {key}")

    def test_llf(self, results):
        np.testing.assert_allclose(
            results["trunc_poisson_0"]["llf"], self.LLF, rtol=1e-4,
            err_msg="trunc_poisson_0 llf")

    def test_aic(self, results):
        np.testing.assert_allclose(
            results["trunc_poisson_0"]["aic"], self.AIC, rtol=1e-4,
            err_msg="trunc_poisson_0 aic")

    def test_n_obs(self, results):
        assert results["trunc_poisson_0"]["n_obs"] == self.N_OBS

    def test_conditional_mean_atmeans(self, results):
        np.testing.assert_allclose(
            results["trunc_poisson_0"]["conditional_mean_atmeans"],
            self.COND_MEAN_ATMEANS, rtol=0.02,
            err_msg="trunc_poisson_0 conditional_mean_atmeans")


# -- Truncated NB2, truncation = 0 --------------------------------------------

class TestTruncNegbin0:
    """Zero-truncated NB2 validated against Stata tnbreg."""

    PARAMS = {"aget": 0.01798960271895, "totchr": 0.23731215078822,
              "const": 1.4035619564653, "alpha": 0.5883738271406221}
    BSE = {"aget": 0.01237555909354, "totchr": 0.01166878414467,
           "const": 0.0366296524502}
    LLF = -9335.541732372312
    AIC = 18679.083464745
    N_OBS = 3237
    COND_MEAN_ATMEANS = 7.2045302352894

    def test_params(self, results):
        r = results["trunc_negbin_0"]["params"]
        for key in ["aget", "totchr", "const"]:
            assert key in r, f"Missing param '{key}'"
            np.testing.assert_allclose(r[key], self.PARAMS[key], atol=1e-3,
                                       err_msg=f"trunc_negbin_0 param {key}")

    def test_alpha(self, results):
        r = results["trunc_negbin_0"]["params"]
        assert "alpha" in r, "Missing alpha parameter"
        np.testing.assert_allclose(r["alpha"], self.PARAMS["alpha"], rtol=0.02,
                                   err_msg="trunc_negbin_0 alpha")

    def test_alpha_positive(self, results):
        alpha = results["trunc_negbin_0"]["params"]["alpha"]
        assert np.isfinite(alpha) and alpha > 0, (
            f"trunc_negbin_0 alpha must be positive and finite, got {alpha}")

    def test_bse(self, results):
        r = results["trunc_negbin_0"]["bse"]
        for key in ["aget", "totchr", "const"]:
            assert key in r, f"Missing bse '{key}'"
            np.testing.assert_allclose(r[key], self.BSE[key], atol=1e-2,
                                       err_msg=f"trunc_negbin_0 bse {key}")

    def test_llf(self, results):
        np.testing.assert_allclose(
            results["trunc_negbin_0"]["llf"], self.LLF, rtol=1e-4,
            err_msg="trunc_negbin_0 llf")

    def test_aic(self, results):
        np.testing.assert_allclose(
            results["trunc_negbin_0"]["aic"], self.AIC, rtol=1e-4,
            err_msg="trunc_negbin_0 aic")

    def test_n_obs(self, results):
        assert results["trunc_negbin_0"]["n_obs"] == self.N_OBS

    def test_conditional_mean_atmeans(self, results):
        np.testing.assert_allclose(
            results["trunc_negbin_0"]["conditional_mean_atmeans"],
            self.COND_MEAN_ATMEANS, rtol=0.02,
            err_msg="trunc_negbin_0 conditional_mean_atmeans")


# -- Truncated Poisson, truncation = 1 ----------------------------------------

class TestTruncPoisson1:
    """Poisson truncated at 1, validated against Stata tpoisson ll(1)."""

    PARAMS = {"aget": 0.00741559993424, "totchr": 0.18069681610939,
              "const": 1.6905464469665}
    BSE = {"aget": 0.00511787438189, "totchr": 0.00462967674542,
           "const": 0.01602194453256}
    LLF = -11046.46816018163
    AIC = 22098.936320363
    N_OBS = 2925
    COND_MEAN_ATMEANS = 7.9996766078498

    def test_params(self, results):
        r = results["trunc_poisson_1"]["params"]
        for key, expected in self.PARAMS.items():
            assert key in r, f"Missing param '{key}'"
            np.testing.assert_allclose(r[key], expected, atol=1e-3,
                                       err_msg=f"trunc_poisson_1 param {key}")

    def test_bse(self, results):
        r = results["trunc_poisson_1"]["bse"]
        for key, expected in self.BSE.items():
            assert key in r, f"Missing bse '{key}'"
            np.testing.assert_allclose(r[key], expected, atol=1e-3,
                                       err_msg=f"trunc_poisson_1 bse {key}")

    def test_llf(self, results):
        np.testing.assert_allclose(
            results["trunc_poisson_1"]["llf"], self.LLF, rtol=1e-4,
            err_msg="trunc_poisson_1 llf")

    def test_aic(self, results):
        np.testing.assert_allclose(
            results["trunc_poisson_1"]["aic"], self.AIC, rtol=1e-4,
            err_msg="trunc_poisson_1 aic")

    def test_n_obs(self, results):
        assert results["trunc_poisson_1"]["n_obs"] == self.N_OBS

    def test_conditional_mean_atmeans(self, results):
        np.testing.assert_allclose(
            results["trunc_poisson_1"]["conditional_mean_atmeans"],
            self.COND_MEAN_ATMEANS, rtol=0.02,
            err_msg="trunc_poisson_1 conditional_mean_atmeans")


# -- Truncated NB2, truncation = 1 --------------------------------------------

class TestTruncNegbin1:
    """NB2 truncated at 1, validated against Stata tnbreg ll(1)."""

    PARAMS = {"aget": 0.01248138313122, "totchr": 0.22357307664024,
              "const": 1.4174570100091, "alpha": 0.6463397153671251}
    BSE = {"aget": 0.01373594189048, "totchr": 0.01291927204045,
           "const": 0.0439841469348}
    LLF = -8359.758837862872
    AIC = 16727.517675726
    N_OBS = 2925
    COND_MEAN_ATMEANS = 7.9492812640074

    def test_params(self, results):
        r = results["trunc_negbin_1"]["params"]
        for key in ["aget", "totchr", "const"]:
            assert key in r, f"Missing param '{key}'"
            np.testing.assert_allclose(r[key], self.PARAMS[key], atol=1e-3,
                                       err_msg=f"trunc_negbin_1 param {key}")

    def test_alpha(self, results):
        r = results["trunc_negbin_1"]["params"]
        assert "alpha" in r, "Missing alpha parameter"
        np.testing.assert_allclose(r["alpha"], self.PARAMS["alpha"], rtol=0.02,
                                   err_msg="trunc_negbin_1 alpha")

    def test_alpha_positive(self, results):
        alpha = results["trunc_negbin_1"]["params"]["alpha"]
        assert np.isfinite(alpha) and alpha > 0, (
            f"trunc_negbin_1 alpha must be positive and finite, got {alpha}")

    def test_bse(self, results):
        r = results["trunc_negbin_1"]["bse"]
        for key in ["aget", "totchr", "const"]:
            assert key in r, f"Missing bse '{key}'"
            np.testing.assert_allclose(r[key], self.BSE[key], atol=1e-2,
                                       err_msg=f"trunc_negbin_1 bse {key}")

    def test_llf(self, results):
        np.testing.assert_allclose(
            results["trunc_negbin_1"]["llf"], self.LLF, rtol=1e-4,
            err_msg="trunc_negbin_1 llf")

    def test_aic(self, results):
        np.testing.assert_allclose(
            results["trunc_negbin_1"]["aic"], self.AIC, rtol=1e-4,
            err_msg="trunc_negbin_1 aic")

    def test_n_obs(self, results):
        assert results["trunc_negbin_1"]["n_obs"] == self.N_OBS

    def test_conditional_mean_atmeans(self, results):
        np.testing.assert_allclose(
            results["trunc_negbin_1"]["conditional_mean_atmeans"],
            self.COND_MEAN_ATMEANS, rtol=0.02,
            err_msg="trunc_negbin_1 conditional_mean_atmeans")


# -- Hurdle Poisson-Poisson ---------------------------------------------------

class TestHurdlePP:
    """Hurdle Poisson-Poisson validated against R pscl::hurdle()."""

    ZERO_PARAMS = {"const": 0.216740121452838, "aget": 0.0189277243223132,
                   "totchr": 0.386748883124962}
    COUNT_PARAMS = {"const": 1.54175599063303, "aget": 0.0122763123129474,
                    "totchr": 0.209943725275436}
    LLF = -13612.9091771797
    PREDICTED_MEAN = 6.530525236464
    PREDICTED_PROBS = [0.07266312350019, 0.005744258908698,
                       0.02020842274659, 0.04739576870239]

    def test_zero_params(self, results):
        r = results["hurdle_pp"]["zero_params"]
        for key, expected in self.ZERO_PARAMS.items():
            assert key in r, f"Missing zero_param '{key}'"
            np.testing.assert_allclose(r[key], expected, atol=5e-3,
                                       err_msg=f"hurdle zero_param {key}")

    def test_count_params(self, results):
        r = results["hurdle_pp"]["count_params"]
        for key, expected in self.COUNT_PARAMS.items():
            assert key in r, f"Missing count_param '{key}'"
            np.testing.assert_allclose(r[key], expected, atol=1e-3,
                                       err_msg=f"hurdle count_param {key}")

    def test_count_params_match_trunc_poisson_0(self, results):
        """Count part of Poisson-Poisson hurdle must equal zero-truncated Poisson."""
        tp0 = results["trunc_poisson_0"]["params"]
        cp = results["hurdle_pp"]["count_params"]
        for key in ["aget", "totchr", "const"]:
            np.testing.assert_allclose(
                cp[key], tp0[key], rtol=1e-3,
                err_msg=f"hurdle count_param {key} should match trunc_poisson_0")

    def test_llf(self, results):
        np.testing.assert_allclose(
            results["hurdle_pp"]["llf"], self.LLF, rtol=1e-3,
            err_msg="hurdle_pp llf")

    def test_predicted_mean(self, results):
        np.testing.assert_allclose(
            results["hurdle_pp"]["predicted_mean_atmeans"],
            self.PREDICTED_MEAN, rtol=0.02,
            err_msg="hurdle predicted_mean_atmeans")

    def test_predicted_probs(self, results):
        probs = results["hurdle_pp"]["predicted_probs_atmeans"]
        assert len(probs) == 4, "Need 4 predicted probabilities"
        np.testing.assert_allclose(
            probs, self.PREDICTED_PROBS, atol=0.01,
            err_msg="hurdle predicted_probs_atmeans")

    def test_decomposition(self, results):
        d = results["hurdle_pp"]["decomposition"]
        assert "zero_llf" in d and "count_llf" in d and "total_llf" in d
        np.testing.assert_allclose(
            d["zero_llf"] + d["count_llf"], d["total_llf"], atol=0.1,
            err_msg="hurdle decomposition: zero_llf + count_llf != total_llf")
        np.testing.assert_allclose(
            d["total_llf"], results["hurdle_pp"]["llf"], atol=0.1,
            err_msg="hurdle decomposition total_llf != llf")
        np.testing.assert_allclose(
            d["count_llf"], -12557.82, rtol=1e-3,
            err_msg="hurdle count_llf should match trunc_poisson_0 llf")


# -- Likelihood Ratio Tests ---------------------------------------------------

class TestLRTests:
    """LR test comparing NB vs Poisson at each truncation point."""

    LR_STAT_0 = 6444.56377006125
    LR_STAT_1 = 5373.418644637513

    def test_lr_test_0(self, results):
        lr = results["lr_test_0"]
        np.testing.assert_allclose(
            lr["statistic"], self.LR_STAT_0, rtol=1e-3,
            err_msg="lr_test_0 statistic")
        assert lr["df"] == 1, "LR test df should be 1"

    def test_lr_test_1(self, results):
        lr = results["lr_test_1"]
        np.testing.assert_allclose(
            lr["statistic"], self.LR_STAT_1, rtol=1e-3,
            err_msg="lr_test_1 statistic")
        assert lr["df"] == 1, "LR test df should be 1"

    def test_lr_statistics_positive(self, results):
        assert results["lr_test_0"]["statistic"] > 0, "LR stat 0 must be positive"
        assert results["lr_test_1"]["statistic"] > 0, "LR stat 1 must be positive"


# -- Vuong Test ----------------------------------------------------------------

class TestVuongTest:
    """Non-nested test: trunc_poisson_0 vs trunc_negbin_0.
    NB2 has dramatically better fit, so statistic should be
    strongly negative (favoring the second model)."""

    def test_vuong_statistic_sign(self, results):
        v = results["vuong_test_0"]
        stat = v["statistic"]
        assert np.isfinite(stat), "Vuong statistic should be finite"
        assert stat < -5, (
            f"Vuong statistic should be strongly negative (favoring NB), got {stat}")

    def test_vuong_pvalue(self, results):
        v = results["vuong_test_0"]
        pval = v["pvalue"]
        assert 0 < pval < 0.05, (
            f"Vuong p-value should be significant, got {pval}")


# -- Structure checks ---------------------------------------------------------

class TestStructure:
    """Verify all required keys exist in the JSON."""

    REQUIRED_TOP_KEYS = [
        "trunc_poisson_0", "trunc_negbin_0",
        "trunc_poisson_1", "trunc_negbin_1",
        "hurdle_pp", "lr_test_0", "lr_test_1", "vuong_test_0",
    ]

    def test_top_level_keys(self, results):
        for key in self.REQUIRED_TOP_KEYS:
            assert key in results, f"Missing top-level key '{key}'"

    def test_truncated_model_keys(self, results):
        for model_key in ["trunc_poisson_0", "trunc_negbin_0",
                          "trunc_poisson_1", "trunc_negbin_1"]:
            m = results[model_key]
            for k in ["params", "bse", "llf", "aic", "n_obs",
                       "conditional_mean_atmeans"]:
                assert k in m, f"Missing '{k}' in {model_key}"

    def test_hurdle_keys(self, results):
        h = results["hurdle_pp"]
        for k in ["zero_params", "count_params", "llf",
                   "predicted_mean_atmeans", "predicted_probs_atmeans",
                   "decomposition"]:
            assert k in h, f"Missing '{k}' in hurdle_pp"

    def test_lr_test_keys(self, results):
        for key in ["lr_test_0", "lr_test_1"]:
            lr = results[key]
            assert "statistic" in lr, f"Missing 'statistic' in {key}"
            assert "df" in lr, f"Missing 'df' in {key}"

    def test_vuong_test_keys(self, results):
        v = results["vuong_test_0"]
        assert "statistic" in v, "Missing 'statistic' in vuong_test_0"
        assert "pvalue" in v, "Missing 'pvalue' in vuong_test_0"
