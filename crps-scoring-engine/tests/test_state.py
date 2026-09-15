
import sys
import json
import os

sys.path.insert(0, "/app")

import numpy as np
import pytest
from scipy.stats import norm as sp_norm


class TestCRPSGEV:
    """Test CRPS for the Generalized Extreme Value distribution."""

    def test_gumbel_case(self):
        """GEV with shape=0 (Gumbel)."""
        from scoring_rules import crps_gev

        result = crps_gev(0.3, 0.0)
        assert np.isclose(result, 0.276440963, atol=1e-6), f"Gumbel CRPS={result}"

    def test_frechet_case(self):
        """GEV with shape>0 (Frechet)."""
        from scoring_rules import crps_gev

        result = crps_gev(0.3, 0.7)
        assert np.isclose(result, 0.458044365, atol=1e-6), f"Frechet CRPS={result}"

    def test_weibull_case(self):
        """GEV with shape<0 (Weibull)."""
        from scoring_rules import crps_gev

        result = crps_gev(0.3, -0.7)
        assert np.isclose(result, 0.207621488, atol=1e-6), f"Weibull CRPS={result}"

    def test_location_invariance(self):
        """CRPS(y+mu, xi, loc=mu) == CRPS(y, xi)."""
        from scoring_rules import crps_gev

        mu = 0.1
        result = crps_gev(0.3 + mu, 0.0, location=mu)
        assert np.isclose(result, 0.276440963, atol=1e-6)

    def test_scale_homogeneity_gumbel(self):
        """CRPS(y*sigma, xi, scale=sigma) == sigma * CRPS(y, xi)."""
        from scoring_rules import crps_gev

        sigma = 0.9
        result = crps_gev(0.3 * sigma, 0.0, scale=sigma)
        assert np.isclose(result, 0.276440963 * sigma, atol=1e-6)

    def test_scale_homogeneity_frechet(self):
        """Scale homogeneity for Frechet case."""
        from scoring_rules import crps_gev

        sigma = 0.9
        result = crps_gev(0.3 * sigma, 0.7, scale=sigma)
        assert np.isclose(result, 0.458044365 * sigma, atol=1e-6)

    def test_scale_homogeneity_weibull(self):
        """Scale homogeneity for Weibull case."""
        from scoring_rules import crps_gev

        sigma = 0.9
        result = crps_gev(0.3 * sigma, -0.7, scale=sigma)
        assert np.isclose(result, 0.207621488 * sigma, atol=1e-6)


class TestCRPSGPD:
    """Test CRPS for the Generalized Pareto Distribution."""

    def test_reference_value(self):
        """GPD with shape=0.9 against known reference value."""
        from scoring_rules import crps_gpd

        result = crps_gpd(0.3, 0.9)
        assert np.isclose(result, 0.6849332, atol=1e-4), f"GPD CRPS={result}"

    def test_scale_homogeneity(self):
        """CRPS(y*sigma, xi, loc=0, scale=sigma) == sigma * CRPS(y, xi)."""
        from scoring_rules import crps_gpd

        sigma = 2.5
        base = crps_gpd(0.3, 0.9)
        scaled = crps_gpd(0.3 * sigma, 0.9, location=0.0, scale=sigma)
        assert np.isclose(scaled, base * sigma, atol=1e-6)

    def test_exponential_case(self):
        """GPD with shape=0 reduces to standard exponential CRPS."""
        from scoring_rules import crps_gpd

        obs = 0.5
        result = crps_gpd(obs, 0.0)
        F = 1.0 - np.exp(-obs)
        expected = np.abs(obs) - 2.0 * F + 0.5
        assert np.isclose(result, expected, atol=1e-6), f"Exp CRPS={result} vs {expected}"

    def test_negative_shape(self):
        """GPD with shape < 0 has bounded upper support and finite CRPS."""
        from scoring_rules import crps_gpd

        result = crps_gpd(1.0, -0.5)
        assert np.isfinite(result), f"GPD negative shape CRPS not finite: {result}"
        assert result >= 0, f"GPD negative shape CRPS negative: {result}"

    def test_non_negative(self):
        """GPD CRPS must be non-negative for valid inputs."""
        from scoring_rules import crps_gpd

        rng = np.random.RandomState(42)
        for _ in range(30):
            obs = float(np.abs(rng.randn()))
            shape = float(rng.uniform(0.01, 0.95))
            result = crps_gpd(obs, shape)
            assert result >= -1e-10, f"GPD CRPS negative: {result}"

    def test_with_mass(self):
        """GPD with point mass at boundary must have finite non-negative CRPS."""
        from scoring_rules import crps_gpd

        result = crps_gpd(0.5, 0.3, mass=0.2)
        assert np.isfinite(result)
        assert result >= 0


class TestCRPSNormal:
    """Test CRPS for the normal distribution."""

    def test_non_negative(self):
        from scoring_rules import crps_normal

        rng = np.random.RandomState(42)
        obs = rng.randn(50)
        mu = obs + rng.randn(50) * 0.1
        sigma = np.abs(rng.randn(50)) * 0.3 + 0.01
        result = np.asarray(crps_normal(obs, mu, sigma))
        assert not np.any(np.isnan(result))
        assert not np.any(result < -1e-10)

    def test_near_zero_perfect_forecast(self):
        from scoring_rules import crps_normal

        rng = np.random.RandomState(42)
        obs = rng.randn(20)
        mu = obs + rng.randn(20) * 1e-6
        sigma = np.abs(rng.randn(20)) * 1e-6 + 1e-8
        result = np.asarray(crps_normal(obs, mu, sigma))
        assert not np.any(np.isnan(result))
        assert np.all(np.abs(result) < 1e-3)


class TestCRPSGTCNormal:
    """Test CRPS for the generalized truncated/censored normal distribution."""

    def test_full_gtcnormal(self):
        """Reference value from scoringrules test suite."""
        from scoring_rules import crps_gtcnormal

        result = crps_gtcnormal(
            0.9, -2.3, 4.1, lower=-7.3, upper=1.7, lmass=0.0, umass=0.21
        )
        assert np.isclose(result, 1.422805, atol=1e-4), f"gtcNormal CRPS={result}"

    def test_reduces_to_normal(self):
        """gtcNormal with infinite bounds and zero masses must equal normal CRPS."""
        from scoring_rules import crps_gtcnormal, crps_normal

        obs, mu, sigma = 0.9, -2.3, 4.1
        result_gtc = crps_gtcnormal(obs, mu, sigma)
        result_normal = crps_normal(obs, mu, sigma)
        assert np.isclose(
            result_gtc, result_normal, atol=1e-6
        ), f"gtcNormal={result_gtc} vs normal={result_normal}"

    def test_censored_normal(self):
        """Censored normal: lmass/umass are the tail probabilities."""
        from scoring_rules import crps_gtcnormal

        obs, mu, sigma, lower, upper = 1.8, 0.4, 1.1, 0.0, 2.0
        lmass = float(sp_norm.cdf((lower - mu) / sigma))
        umass = float(1.0 - sp_norm.cdf((upper - mu) / sigma))
        result = crps_gtcnormal(
            obs, mu, sigma, lower=lower, upper=upper, lmass=lmass, umass=umass
        )
        assert np.isclose(result, 0.8296078, atol=1e-4), f"cNormal CRPS={result}"

    def test_truncated_normal(self):
        """Truncated normal: lmass=0, umass=0 with finite bounds."""
        from scoring_rules import crps_gtcnormal

        obs, mu, sigma, lower, upper = -1.0, 2.9, 2.2, 1.5, 17.3
        result = crps_gtcnormal(obs, mu, sigma, lower=lower, upper=upper)
        assert np.isclose(result, 3.982434, atol=1e-4), f"tNormal CRPS={result}"


class TestCRPSMixNorm:
    """Test CRPS for mixture of normal distributions."""

    def test_equal_weights(self):
        """Equal weights (default) with 3 components."""
        from scoring_rules import crps_mixnorm

        result = crps_mixnorm(0.3, [0.0, -2.9, 0.9], [0.5, 1.4, 0.7])
        assert np.isclose(result, 0.4510451, atol=1e-4), f"MixNorm CRPS={result}"

    def test_unequal_weights(self):
        """Unequal weights with 3 components."""
        from scoring_rules import crps_mixnorm

        result = crps_mixnorm(
            0.3, [0.0, -2.9, 0.9], [0.5, 1.4, 0.7], w=[0.3, 0.1, 0.6]
        )
        assert np.isclose(result, 0.2354619, atol=1e-4), f"MixNorm CRPS={result}"

    def test_single_component_equals_normal(self):
        """Mixture with 1 component should equal normal CRPS."""
        from scoring_rules import crps_mixnorm, crps_normal

        obs, mu, sigma = 1.5, 0.3, 2.1
        result_mix = crps_mixnorm(obs, [mu], [sigma], w=[1.0])
        result_normal = crps_normal(obs, mu, sigma)
        assert np.isclose(
            result_mix, result_normal, atol=1e-6
        ), f"1-component mix={result_mix} vs normal={result_normal}"


class TestCRPSEnsemble:
    """Test ensemble CRPS estimators."""

    def setup_method(self):
        self.obs = -0.6042506
        self.fct = np.array(
            [
                1.7812118,
                0.5863797,
                0.7038174,
                -0.7743998,
                -0.2751647,
                1.1863249,
                1.2990966,
                -0.3242982,
                -0.5968781,
                0.9064937,
            ]
        )

    def test_qd_estimator_reference(self):
        """QD estimator against known reference value."""
        from scoring_rules import crps_ensemble

        result = crps_ensemble(self.obs, self.fct, estimator="qd")
        assert np.isclose(result, 0.6126602, atol=1e-4), f"QD CRPS={result}"

    def test_nrg_qd_equivalence(self):
        """NRG and QD estimators must agree for sorted ensembles."""
        from scoring_rules import crps_ensemble

        res_nrg = crps_ensemble(self.obs, self.fct, estimator="nrg")
        res_qd = crps_ensemble(self.obs, self.fct, estimator="qd")
        assert np.isclose(res_nrg, res_qd, atol=1e-6), f"nrg={res_nrg} vs qd={res_qd}"

    def test_fair_pwm_equivalence(self):
        """Fair and PWM estimators must agree for sorted ensembles."""
        from scoring_rules import crps_ensemble

        res_fair = crps_ensemble(self.obs, self.fct, estimator="fair")
        res_pwm = crps_ensemble(self.obs, self.fct, estimator="pwm")
        assert np.isclose(
            res_fair, res_pwm, atol=1e-6
        ), f"fair={res_fair} vs pwm={res_pwm}"

    def test_non_negative_batch(self):
        """All four estimators must produce non-negative CRPS."""
        from scoring_rules import crps_ensemble

        rng = np.random.RandomState(42)
        obs = rng.randn(50)
        fct = rng.randn(50, 21)
        for est in ["nrg", "fair", "pwm", "qd"]:
            result = np.asarray(crps_ensemble(obs, fct, estimator=est))
            assert np.all(result >= -1e-10), f"Non-negativity failed for {est}"

    def test_perfect_forecast_near_zero(self):
        """CRPS should be near zero when ensemble members approx observation."""
        from scoring_rules import crps_ensemble

        rng = np.random.RandomState(42)
        obs = rng.randn(20)
        fct = obs[:, None] + rng.randn(20, 51) * 1e-5
        for est in ["nrg", "fair", "pwm", "qd"]:
            result = np.asarray(crps_ensemble(obs, fct, estimator=est))
            assert np.all(
                np.abs(result) < 1e-3
            ), f"Perfect forecast test failed for {est}"

    def test_nrg_qd_equivalence_batch(self):
        """Batch equivalence of nrg and qd."""
        from scoring_rules import crps_ensemble

        rng = np.random.RandomState(123)
        obs = rng.randn(30)
        fct = rng.randn(30, 15)
        res_nrg = np.asarray(crps_ensemble(obs, fct, estimator="nrg"))
        res_qd = np.asarray(crps_ensemble(obs, fct, estimator="qd"))
        assert np.allclose(res_nrg, res_qd, atol=1e-6)

    def test_fair_pwm_equivalence_batch(self):
        """Batch equivalence of fair and pwm."""
        from scoring_rules import crps_ensemble

        rng = np.random.RandomState(123)
        obs = rng.randn(30)
        fct = rng.randn(30, 15)
        res_fair = np.asarray(crps_ensemble(obs, fct, estimator="fair"))
        res_pwm = np.asarray(crps_ensemble(obs, fct, estimator="pwm"))
        assert np.allclose(res_fair, res_pwm, atol=1e-6)

    def test_invalid_estimator_raises(self):
        """Unknown estimator must raise ValueError."""
        from scoring_rules import crps_ensemble

        with pytest.raises(ValueError):
            crps_ensemble(0.0, np.array([1.0, 2.0]), estimator="invalid")


class TestOWCRPS:
    """Test outcome-weighted CRPS."""

    def test_unit_weights_equals_nrg(self):
        """owCRPS with w(x)=1 must equal the NRG estimator."""
        from scoring_rules import crps_ensemble, owcrps_ensemble

        rng = np.random.RandomState(42)
        obs = rng.randn(10)
        fct = rng.randn(10, 15)

        w_func = lambda x: np.ones_like(x)
        result_ow = np.asarray(owcrps_ensemble(obs, fct, w_func))
        result_nrg = np.asarray(crps_ensemble(obs, fct, estimator="nrg"))
        assert np.allclose(
            result_ow, result_nrg, atol=1e-6
        ), f"owCRPS={result_ow[:3]} vs nrg={result_nrg[:3]}"

    def test_non_negative_with_indicator(self):
        """owCRPS with indicator weight must be non-negative."""
        from scoring_rules import owcrps_ensemble

        rng = np.random.RandomState(42)
        obs = rng.randn(20)
        fct = rng.randn(20, 15)
        w_func = lambda x: (x > -1.0).astype(float)
        result = np.asarray(owcrps_ensemble(obs, fct, w_func))
        assert np.all(result >= -1e-10)

    def test_zero_weight_observation(self):
        """owCRPS should be zero when observation has zero weight."""
        from scoring_rules import owcrps_ensemble

        obs = np.array([-5.0])  # well below threshold
        fct = np.array([[1.0, 2.0, 3.0, 4.0, 5.0]])
        w_func = lambda x: (x > 0.0).astype(float)
        result = owcrps_ensemble(obs, fct, w_func)
        result_val = float(np.squeeze(result))
        assert np.isclose(result_val, 0.0, atol=1e-10)


class TestTWCRPS:
    """Test threshold-weighted CRPS via chaining functions."""

    def test_identity_equals_nrg(self):
        """twCRPS with identity chaining v(x)=x must equal NRG estimator."""
        from scoring_rules import crps_ensemble, twcrps_ensemble

        rng = np.random.RandomState(42)
        obs = rng.randn(10)
        fct = rng.randn(10, 15)
        v_func = lambda x: x
        result_tw = np.asarray(twcrps_ensemble(obs, fct, v_func))
        result_nrg = np.asarray(crps_ensemble(obs, fct, estimator="nrg"))
        assert np.allclose(
            result_tw, result_nrg, atol=1e-6
        ), f"twCRPS={result_tw[:3]} vs nrg={result_nrg[:3]}"

    def test_non_negative(self):
        """twCRPS with threshold chaining must be non-negative."""
        from scoring_rules import twcrps_ensemble

        rng = np.random.RandomState(42)
        obs = rng.randn(20)
        fct = rng.randn(20, 15)
        v_func = lambda x: np.maximum(x, -1.0)
        result = np.asarray(twcrps_ensemble(obs, fct, v_func))
        assert np.all(result >= -1e-10)

    def test_threshold_differs_from_standard(self):
        """twCRPS with non-identity chaining should generally differ from standard CRPS."""
        from scoring_rules import crps_ensemble, twcrps_ensemble

        obs = np.array([0.5, -0.5, 1.5])
        fct = np.array(
            [
                [0.1, 0.2, 0.3, 0.4, 0.5],
                [-0.3, -0.1, 0.0, 0.2, 0.4],
                [0.8, 1.0, 1.2, 1.4, 1.6],
            ]
        )
        v_func = lambda x: np.maximum(x, 0.0)
        result_tw = np.asarray(twcrps_ensemble(obs, fct, v_func))
        result_nrg = np.asarray(crps_ensemble(obs, fct, estimator="nrg"))
        # They should differ when the chaining function is not identity
        assert not np.allclose(result_tw, result_nrg, atol=1e-6)


class TestEvaluationPipeline:
    """Test the full evaluation pipeline output."""

    def test_results_file_exists(self):
        assert os.path.exists("/app/results.json"), "results.json must exist at /app/"

    def test_results_structure(self):
        with open("/app/results.json") as f:
            results = json.load(f)
        assert "gev" in results, "results must contain 'gev' key"
        assert "gpd" in results, "results must contain 'gpd' key"
        assert "gtcnormal" in results, "results must contain 'gtcnormal' key"
        assert "mixnorm" in results, "results must contain 'mixnorm' key"
        assert "ensemble" in results, "results must contain 'ensemble' key"

    def test_gev_results_correct(self):
        with open("/app/results.json") as f:
            results = json.load(f)
        gev_map = {r["id"]: r["crps"] for r in results["gev"]}
        assert np.isclose(gev_map["gev_gumbel"], 0.276440963, atol=1e-5)
        assert np.isclose(gev_map["gev_frechet"], 0.458044365, atol=1e-5)
        assert np.isclose(gev_map["gev_weibull"], 0.207621488, atol=1e-5)

    def test_gev_location_scale_results(self):
        with open("/app/results.json") as f:
            results = json.load(f)
        gev_map = {r["id"]: r["crps"] for r in results["gev"]}
        assert np.isclose(gev_map["gev_loc_shift"], 0.276440963, atol=1e-5)
        assert np.isclose(gev_map["gev_scale_shift"], 0.276440963 * 0.9, atol=1e-5)
        assert np.isclose(
            gev_map["gev_frechet_scaled"], 0.458044365 * 0.9, atol=1e-5
        )

    def test_gpd_results_correct(self):
        with open("/app/results.json") as f:
            results = json.load(f)
        gpd_map = {r["id"]: r["crps"] for r in results["gpd"]}
        assert np.isclose(gpd_map["gpd_standard"], 0.6849332, atol=1e-4)

    def test_mixnorm_results_correct(self):
        with open("/app/results.json") as f:
            results = json.load(f)
        mix_map = {r["id"]: r["crps"] for r in results["mixnorm"]}
        assert np.isclose(mix_map["mix_equal_w"], 0.4510451, atol=1e-4)
        assert np.isclose(mix_map["mix_unequal_w"], 0.2354619, atol=1e-4)

    def test_ensemble_results_correct(self):
        with open("/app/results.json") as f:
            results = json.load(f)
        for r in results["ensemble"]:
            if r["id"] == "ens_10member":
                assert np.isclose(r["crps_qd"], 0.6126602, atol=1e-4)
                assert np.isclose(r["crps_nrg"], r["crps_qd"], atol=1e-5)
                assert np.isclose(r["crps_fair"], r["crps_pwm"], atol=1e-5)

    def test_gtcnormal_results(self):
        with open("/app/results.json") as f:
            results = json.load(f)
        gtc_map = {r["id"]: r["crps"] for r in results["gtcnormal"]}
        assert np.isclose(gtc_map["gtcn_full"], 1.422805, atol=1e-4)
