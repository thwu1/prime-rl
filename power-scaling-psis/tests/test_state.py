"""Tests for power-scaling prior sensitivity analysis with PSIS.

"""

import json
import os

import numpy as np
import pytest


@pytest.fixture(scope="module")
def results():
    result_dir = "/app/results"
    files = {}
    for name in ["pareto_k", "sensitivity", "weighted_moments", "ess"]:
        path = os.path.join(result_dir, f"{name}.json")
        with open(path) as f:
            files[name] = json.load(f)
    return files


@pytest.fixture(scope="module")
def data():
    samples = dict(np.load("/app/data/samples.npz"))
    log_priors = dict(np.load("/app/data/log_prior_components.npz"))
    with open("/app/data/model_spec.json") as f:
        spec = json.load(f)
    return samples, log_priors, spec


# ---------------------------------------------------------------------------
# Output structure
# ---------------------------------------------------------------------------
class TestOutputFiles:
    def test_files_exist(self):
        for name in ["pareto_k", "sensitivity", "weighted_moments", "ess"]:
            path = f"/app/results/{name}.json"
            assert os.path.exists(path), f"Missing output file {path}"

    def test_files_valid_json(self, results):
        for name, content in results.items():
            assert isinstance(content, dict), f"{name}.json should be a JSON object"


# ---------------------------------------------------------------------------
# Pareto k-hat
# ---------------------------------------------------------------------------
class TestParetoK:
    def test_all_entries_present(self, results, data):
        _, _, spec = data
        pk = results["pareto_k"]
        for comp in spec["prior_components"]:
            for alpha in spec["alpha_grid"]:
                key = f"{comp}_alpha_{alpha}"
                assert key in pk, f"Missing key {key} in pareto_k.json"

    def test_k_values_finite(self, results, data):
        _, _, spec = data
        pk = results["pareto_k"]
        for comp in spec["prior_components"]:
            for alpha in spec["alpha_grid"]:
                key = f"{comp}_alpha_{alpha}"
                assert np.isfinite(pk[key]), f"k-hat not finite for {key}"

    def test_k_near_zero_at_alpha_near_one(self, results, data):
        """When alpha is close to 1, weights are nearly uniform so k-hat ~ 0."""
        _, _, spec = data
        pk = results["pareto_k"]
        for comp in spec["prior_components"]:
            for alpha in [0.99, 1.01]:
                key = f"{comp}_alpha_{alpha}"
                assert pk[key] < 0.35, (
                    f"k-hat too large for near-unity alpha: {key}={pk[key]:.4f}"
                )

    def test_k_monotonicity(self, results, data):
        """k-hat should generally increase as alpha deviates further from 1."""
        _, _, spec = data
        pk = results["pareto_k"]
        for comp in spec["prior_components"]:
            k_near = pk[f"{comp}_alpha_0.99"]
            k_far = pk[f"{comp}_alpha_0.5"]
            assert k_far >= k_near - 0.05, (
                f"Monotonicity violated for {comp}: "
                f"k(0.99)={k_near:.3f} vs k(0.5)={k_far:.3f}"
            )


# ---------------------------------------------------------------------------
# Effective sample size
# ---------------------------------------------------------------------------
class TestESS:
    def test_all_entries_present(self, results, data):
        _, _, spec = data
        ess = results["ess"]
        for comp in spec["prior_components"]:
            for alpha in spec["alpha_grid"]:
                key = f"{comp}_alpha_{alpha}"
                assert key in ess, f"Missing key {key} in ess.json"

    def test_ess_bounds(self, results, data):
        _, _, spec = data
        ess = results["ess"]
        S = spec["n_samples_total"]
        for key, val in ess.items():
            assert 0 < val <= S * 1.01, f"ESS out of bounds for {key}: {val}"

    def test_ess_monotonicity(self, results, data):
        """ESS should generally decrease as alpha deviates from 1."""
        _, _, spec = data
        ess = results["ess"]
        for comp in spec["prior_components"]:
            ess_near = ess[f"{comp}_alpha_0.99"]
            ess_far = ess[f"{comp}_alpha_0.5"]
            assert ess_near >= ess_far - 200, (
                f"ESS monotonicity violated for {comp}: "
                f"ESS(0.99)={ess_near:.0f} vs ESS(0.5)={ess_far:.0f}"
            )

    def test_ess_vs_raw_is(self, results, data):
        """PSIS ESS should be >= raw IS ESS (smoothing reduces extreme weights)."""
        _, log_priors, spec = data
        ess = results["ess"]
        for comp in spec["prior_components"]:
            lp = log_priors[comp]
            for alpha in spec["alpha_grid"]:
                log_w = (alpha - 1.0) * lp
                w = np.exp(log_w - np.max(log_w))
                w /= w.sum()
                ess_raw = 1.0 / np.sum(w ** 2)

                key = f"{comp}_alpha_{alpha}"
                ess_psis = ess[key]
                assert ess_psis >= ess_raw * 0.8, (
                    f"PSIS ESS unexpectedly low vs raw IS for {key}: "
                    f"PSIS={ess_psis:.1f}, raw={ess_raw:.1f}"
                )


# ---------------------------------------------------------------------------
# Sensitivity scores
# ---------------------------------------------------------------------------
class TestSensitivity:
    def test_all_entries_present(self, results, data):
        _, _, spec = data
        sens = results["sensitivity"]
        for param in spec["parameters"]:
            assert param in sens, f"Missing parameter {param} in sensitivity.json"
            for comp in spec["prior_components"]:
                assert comp in sens[param], (
                    f"Missing component {comp} for param {param}"
                )

    def test_sensitivity_values_finite(self, results, data):
        _, _, spec = data
        sens = results["sensitivity"]
        for param in spec["parameters"]:
            for comp in spec["prior_components"]:
                assert np.isfinite(sens[param][comp]), (
                    f"Sensitivity not finite: {param}/{comp}"
                )

    def test_sensitivity_correct(self, results, data):
        """Verify sensitivity = Cov(param, log_prior) / SD(param)."""
        samples, log_priors, spec = data
        sens = results["sensitivity"]
        for param in spec["scalar_parameters"]:
            s = samples[param]
            sd_param = np.std(s, ddof=1)
            for comp in spec["prior_components"]:
                lp = log_priors[comp]
                expected = np.cov(s, lp)[0, 1] / sd_param
                actual = sens[param][comp]
                tol = max(0.001, 0.01 * abs(expected))
                assert abs(actual - expected) < tol, (
                    f"Sensitivity mismatch for {param}/{comp}: "
                    f"expected={expected:.6f}, got={actual:.6f}"
                )

    def test_mu0_most_sensitive_to_grand_mean(self, results, data):
        """mu_0 should be most sensitive to its own prior (grand_mean)."""
        sens = results["sensitivity"]
        mu0_sens = sens["mu_0"]
        gm_val = abs(mu0_sens["grand_mean"])
        for comp in ["noise_sd", "group_sd"]:
            assert gm_val > abs(mu0_sens[comp]), (
                f"mu_0 should be most sensitive to grand_mean "
                f"({gm_val:.4f}), not {comp} ({abs(mu0_sens[comp]):.4f})"
            )


# ---------------------------------------------------------------------------
# Weighted moments
# ---------------------------------------------------------------------------
class TestWeightedMoments:
    def test_structure(self, results, data):
        _, _, spec = data
        wm = results["weighted_moments"]
        param = spec["parameters"][0]
        comp = spec["prior_components"][0]
        alpha = spec["alpha_grid"][0]
        key = f"{param}_alpha_{alpha}_prior_{comp}"
        assert key in wm, f"Missing weighted moment entry: {key}"
        assert "mean" in wm[key] and "var" in wm[key], (
            f"Entry {key} must have 'mean' and 'var'"
        )

    def test_moments_near_alpha_1(self, results, data):
        """Near alpha=1, weighted moments should match unweighted moments."""
        samples, _, spec = data
        wm = results["weighted_moments"]
        for param in spec["scalar_parameters"]:
            s = samples[param]
            raw_mean = float(np.mean(s))
            raw_sd = float(np.std(s))
            for comp in spec["prior_components"]:
                for alpha in [0.99, 1.01]:
                    key = f"{param}_alpha_{alpha}_prior_{comp}"
                    if key in wm:
                        assert abs(wm[key]["mean"] - raw_mean) < 0.5 * raw_sd, (
                            f"Weighted mean too far from raw mean for {key}: "
                            f"weighted={wm[key]['mean']:.4f}, raw={raw_mean:.4f}"
                        )

    def test_weighted_mean_direction_grand_mean(self, results, data):
        """Weakening grand_mean prior (alpha<1) should increase mu_0;
        strengthening it (alpha>1) should decrease mu_0."""
        samples, _, spec = data
        wm = results["weighted_moments"]
        raw_mean = float(np.mean(samples["mu_0"]))

        key_weak = "mu_0_alpha_0.5_prior_grand_mean"
        assert wm[key_weak]["mean"] > raw_mean, (
            f"Weakening grand_mean prior should increase mu_0: "
            f"weighted={wm[key_weak]['mean']:.4f}, raw={raw_mean:.4f}"
        )

        key_strong = "mu_0_alpha_1.5_prior_grand_mean"
        assert wm[key_strong]["mean"] < raw_mean, (
            f"Strengthening grand_mean prior should decrease mu_0: "
            f"weighted={wm[key_strong]['mean']:.4f}, raw={raw_mean:.4f}"
        )

    def test_psis_vs_raw_is(self, results, data):
        """For low k-hat, PSIS and raw IS weighted means should agree closely."""
        samples, log_priors, spec = data
        wm = results["weighted_moments"]
        pk = results["pareto_k"]
        for comp in spec["prior_components"]:
            lp = log_priors[comp]
            for alpha in spec["alpha_grid"]:
                pk_key = f"{comp}_alpha_{alpha}"
                if pk[pk_key] < 0.5:
                    log_w = (alpha - 1.0) * lp
                    w = np.exp(log_w - np.max(log_w))
                    w /= w.sum()
                    for param in spec["scalar_parameters"]:
                        s = samples[param]
                        raw_is_mean = float(np.dot(w, s))
                        wm_key = f"{param}_alpha_{alpha}_prior_{comp}"
                        psis_mean = wm[wm_key]["mean"]
                        assert abs(psis_mean - raw_is_mean) < 0.1 * np.std(s), (
                            f"PSIS vs raw IS mismatch for {wm_key}: "
                            f"PSIS={psis_mean:.4f}, rawIS={raw_is_mean:.4f}"
                        )


# ---------------------------------------------------------------------------
# Banned packages
# ---------------------------------------------------------------------------
class TestConstraints:
    def test_no_priorsense(self):
        try:
            import priorsense  # noqa: F401
            pytest.fail("priorsense should not be installed")
        except ImportError:
            pass

    def test_no_arviz(self):
        try:
            import arviz  # noqa: F401
            pytest.fail("arviz should not be installed")
        except ImportError:
            pass
