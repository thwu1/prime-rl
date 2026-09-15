"""Tests for MCMC convergence diagnostics pipeline.

Verifies correctness of diagnostic computations by comparing the agent's
output against reference implementations.

"""
import json
import os

import numpy as np
import pytest
from scipy import stats
from scipy.special import logsumexp


DATA_DIR = "/app/data"
OUTPUT_FILE = "/app/output/diagnostics.json"


# ========================================================================
# Reference implementations (ground truth)
# ========================================================================


def ref_autocovariance(x):
    """Autocovariance using FFT with biased normalization."""
    n = len(x)
    x_c = x - np.mean(x)
    fft_x = np.fft.fft(x_c, n=2 * n)
    acov = np.fft.ifft(fft_x * np.conj(fft_x))[:n].real / n
    return acov


def ref_split_chains(chains):
    """Split each chain in half."""
    n_chains, n_draws = chains.shape
    half = n_draws // 2
    split = np.empty((2 * n_chains, half))
    for i in range(n_chains):
        split[2 * i] = chains[i, :half]
        split[2 * i + 1] = chains[i, half : 2 * half]
    return split


def ref_rank_normalize(x):
    """Rank-normalize using Blom's approximation."""
    flat = x.ravel()
    n = len(flat)
    ranks = stats.rankdata(flat)
    z = stats.norm.ppf((ranks - 3 / 8) / (n + 1 / 4))
    return z.reshape(x.shape)


def ref_ess_core(chains):
    """ESS with initial positive sequence estimator."""
    n_chains, n_draws = chains.shape

    acov = np.array([ref_autocovariance(chains[i]) for i in range(n_chains)])
    mean_acov = np.mean(acov, axis=0)

    W = np.mean(np.var(chains, axis=1, ddof=1))
    chain_means = np.mean(chains, axis=1)
    B = n_draws * np.var(chain_means, ddof=1)
    var_hat = ((n_draws - 1) / n_draws) * W + B / n_draws

    if var_hat < 1e-25:
        return float(n_chains * n_draws)

    rho_hat = 1.0 - (W - mean_acov) / var_hat

    # Initial positive sequence: pair consecutive values, stop at first negative pair
    sum_rho = 0.0
    t = 0
    while t < n_draws - 1:
        pair_sum = rho_hat[t] + rho_hat[t + 1]
        if pair_sum < 0:
            break
        sum_rho += pair_sum
        t += 2

    tau_hat = max(
        -1.0 + 2.0 * sum_rho, 1.0 / np.log10(max(n_chains * n_draws, 10))
    )
    ess = n_chains * n_draws / tau_hat
    return max(float(ess), 1.0)


def ref_rhat(chains):
    """Rank-normalized split-R-hat."""
    split = ref_split_chains(chains)
    z = ref_rank_normalize(split)
    n_chains, n_draws = z.shape
    W = np.mean(np.var(z, axis=1, ddof=1))
    chain_means = np.mean(z, axis=1)
    B = n_draws * np.var(chain_means, ddof=1)
    var_hat = ((n_draws - 1) / n_draws) * W + B / n_draws
    if W < 1e-25:
        return 1.0
    return float(np.sqrt(var_hat / W))


def ref_bulk_ess(chains):
    """Bulk ESS on rank-normalized split chains."""
    split = ref_split_chains(chains)
    z = ref_rank_normalize(split)
    return ref_ess_core(z)


def ref_tail_ess(chains):
    """Tail ESS using quantile indicators on split chains."""
    split = ref_split_chains(chains)
    pooled = split.ravel()
    q05 = np.quantile(pooled, 0.05)
    q95 = np.quantile(pooled, 0.95)

    I_low = (split <= q05).astype(float)
    I_high = (split <= q95).astype(float)

    ess_low = ref_ess_core(I_low)
    ess_high = ref_ess_core(I_high)

    return min(ess_low, ess_high)


def ref_waic(log_lik):
    """WAIC with logsumexp for numerical stability."""
    n_chains, n_draws, n_obs = log_lik.shape
    pooled = log_lik.reshape(-1, n_obs)
    S = pooled.shape[0]

    lppd_i = logsumexp(pooled, axis=0) - np.log(S)
    lppd = np.sum(lppd_i)

    p_waic_i = np.var(pooled, axis=0, ddof=1)
    p_waic = np.sum(p_waic_i)

    waic = -2 * (lppd - p_waic)
    return {"waic": float(waic), "lppd": float(lppd), "p_waic": float(p_waic)}


# ========================================================================
# Helper functions
# ========================================================================


def load_chains(model_dir):
    """Load chain data for a model."""
    chains = []
    i = 0
    while os.path.exists(os.path.join(model_dir, f"chain_{i}.npy")):
        chains.append(np.load(os.path.join(model_dir, f"chain_{i}.npy")))
        i += 1
    return np.stack(chains)


def load_output():
    """Load agent's output."""
    with open(OUTPUT_FILE) as f:
        return json.load(f)


def get_param_names(model_name):
    with open(os.path.join(DATA_DIR, "param_names.json")) as f:
        return json.load(f)[model_name]


# ========================================================================
# Tests
# ========================================================================


class TestOutputStructure:
    """Verify output file exists and has correct structure."""

    def test_output_exists(self):
        assert os.path.exists(OUTPUT_FILE), f"Output file {OUTPUT_FILE} not found"

    def test_output_valid_json(self):
        with open(OUTPUT_FILE) as f:
            data = json.load(f)
        assert isinstance(data, dict)

    def test_output_has_models(self):
        data = load_output()
        assert "model_a" in data, "Missing model_a in output"
        assert "model_b" in data, "Missing model_b in output"
        assert "model_comparison" in data, "Missing model_comparison in output"

    def test_model_has_diagnostics(self):
        data = load_output()
        for model in ["model_a", "model_b"]:
            for key in ["rhat", "bulk_ess", "tail_ess", "mcse_mean", "waic", "convergence"]:
                assert key in data[model], f"Missing {key} in {model}"


class TestRhat:
    """Verify R-hat values match rank-normalized split-R-hat reference."""

    def test_rhat_model_a(self):
        data = load_output()
        chains_all = load_chains(os.path.join(DATA_DIR, "model_a"))
        param_names = get_param_names("model_a")

        for p, name in enumerate(param_names):
            ref_val = ref_rhat(chains_all[:, :, p])
            agent_val = data["model_a"]["rhat"][name]
            assert abs(agent_val - ref_val) < 0.03, (
                f"R-hat for {name} in model_a: expected {ref_val:.4f}, got {agent_val:.4f}"
            )

    def test_rhat_model_b(self):
        data = load_output()
        chains_all = load_chains(os.path.join(DATA_DIR, "model_b"))
        param_names = get_param_names("model_b")

        for p, name in enumerate(param_names):
            ref_val = ref_rhat(chains_all[:, :, p])
            agent_val = data["model_b"]["rhat"][name]
            assert abs(agent_val - ref_val) < 0.03, (
                f"R-hat for {name} in model_b: expected {ref_val:.4f}, got {agent_val:.4f}"
            )

    def test_rhat_detects_nonconvergence(self):
        """Model A's log_tau must have high R-hat (> 1.05)."""
        data = load_output()
        rhat_log_tau = data["model_a"]["rhat"]["log_tau"]
        assert rhat_log_tau > 1.05, (
            f"R-hat for log_tau in model_a should indicate non-convergence "
            f"(> 1.05), got {rhat_log_tau:.4f}"
        )

    def test_rhat_model_b_converged(self):
        """All Model B parameters should have R-hat < 1.02."""
        data = load_output()
        for name, val in data["model_b"]["rhat"].items():
            assert val < 1.02, (
                f"R-hat for {name} in model_b should be < 1.02, got {val:.4f}"
            )


class TestESS:
    """Verify effective sample size computations."""

    def test_bulk_ess_model_a(self):
        data = load_output()
        chains_all = load_chains(os.path.join(DATA_DIR, "model_a"))
        param_names = get_param_names("model_a")

        for p, name in enumerate(param_names):
            ref_val = ref_bulk_ess(chains_all[:, :, p])
            agent_val = data["model_a"]["bulk_ess"][name]
            rel_diff = abs(agent_val - ref_val) / max(ref_val, 1)
            assert rel_diff < 0.20, (
                f"Bulk ESS for {name} in model_a: expected {ref_val:.1f}, "
                f"got {agent_val:.1f} (rel diff {rel_diff:.2%})"
            )

    def test_bulk_ess_model_b(self):
        data = load_output()
        chains_all = load_chains(os.path.join(DATA_DIR, "model_b"))
        param_names = get_param_names("model_b")

        for p, name in enumerate(param_names):
            ref_val = ref_bulk_ess(chains_all[:, :, p])
            agent_val = data["model_b"]["bulk_ess"][name]
            rel_diff = abs(agent_val - ref_val) / max(ref_val, 1)
            assert rel_diff < 0.20, (
                f"Bulk ESS for {name} in model_b: expected {ref_val:.1f}, "
                f"got {agent_val:.1f} (rel diff {rel_diff:.2%})"
            )

    def test_tail_ess_model_b(self):
        data = load_output()
        chains_all = load_chains(os.path.join(DATA_DIR, "model_b"))
        param_names = get_param_names("model_b")

        for p, name in enumerate(param_names):
            ref_val = ref_tail_ess(chains_all[:, :, p])
            agent_val = data["model_b"]["tail_ess"][name]
            rel_diff = abs(agent_val - ref_val) / max(ref_val, 1)
            assert rel_diff < 0.25, (
                f"Tail ESS for {name} in model_b: expected {ref_val:.1f}, "
                f"got {agent_val:.1f} (rel diff {rel_diff:.2%})"
            )

    def test_ess_all_positive(self):
        """All ESS values must be positive."""
        data = load_output()
        for model in ["model_a", "model_b"]:
            for name, val in data[model]["bulk_ess"].items():
                assert val > 0, f"Bulk ESS for {name} in {model} must be positive, got {val}"
            for name, val in data[model]["tail_ess"].items():
                assert val > 0, f"Tail ESS for {name} in {model} must be positive, got {val}"

    def test_model_b_ess_high(self):
        """Model B should have high bulk ESS (> 400) for all parameters."""
        data = load_output()
        for name, val in data["model_b"]["bulk_ess"].items():
            assert val > 400, (
                f"Bulk ESS for {name} in model_b should be > 400, got {val:.0f}"
            )


class TestWAIC:
    """Verify WAIC computation."""

    def test_waic_finite(self):
        """WAIC must be finite (not NaN or Inf) — tests numerical stability."""
        data = load_output()
        for model in ["model_a", "model_b"]:
            waic = data[model]["waic"]["waic"]
            assert np.isfinite(waic), (
                f"WAIC for {model} must be finite, got {waic}. "
                f"This typically indicates missing logsumexp for numerical stability."
            )
            lppd = data[model]["waic"]["lppd"]
            assert np.isfinite(lppd), f"lppd for {model} must be finite, got {lppd}"
            p_waic = data[model]["waic"]["p_waic"]
            assert np.isfinite(p_waic), f"p_waic for {model} must be finite, got {p_waic}"

    def test_waic_model_a(self):
        """WAIC for model_a should match reference."""
        data = load_output()
        log_lik = np.load(os.path.join(DATA_DIR, "model_a", "log_lik.npy"))
        ref = ref_waic(log_lik)
        agent_waic = data["model_a"]["waic"]["waic"]
        rel_diff = abs(agent_waic - ref["waic"]) / max(abs(ref["waic"]), 1)
        assert rel_diff < 0.05, (
            f"WAIC for model_a: expected {ref['waic']:.2f}, got {agent_waic:.2f}"
        )

    def test_waic_model_b(self):
        """WAIC for model_b should match reference."""
        data = load_output()
        log_lik = np.load(os.path.join(DATA_DIR, "model_b", "log_lik.npy"))
        ref = ref_waic(log_lik)
        agent_waic = data["model_b"]["waic"]["waic"]
        rel_diff = abs(agent_waic - ref["waic"]) / max(abs(ref["waic"]), 1)
        assert rel_diff < 0.05, (
            f"WAIC for model_b: expected {ref['waic']:.2f}, got {agent_waic:.2f}"
        )

    def test_p_waic_uses_sample_variance(self):
        """p_waic must use sample variance (ddof=1), not population variance."""
        data = load_output()
        log_lik = np.load(os.path.join(DATA_DIR, "model_b", "log_lik.npy"))
        pooled = log_lik.reshape(-1, log_lik.shape[2])
        # Reference with ddof=1
        p_waic_correct = float(np.sum(np.var(pooled, axis=0, ddof=1)))
        # What ddof=0 would give
        p_waic_wrong = float(np.sum(np.var(pooled, axis=0, ddof=0)))
        agent_p_waic = data["model_b"]["waic"]["p_waic"]

        # Agent should be closer to ddof=1 result
        err_correct = abs(agent_p_waic - p_waic_correct)
        err_wrong = abs(agent_p_waic - p_waic_wrong)
        assert err_correct < err_wrong, (
            f"p_waic should use sample variance (ddof=1). "
            f"Got {agent_p_waic:.4f}, ddof=1 gives {p_waic_correct:.4f}, "
            f"ddof=0 gives {p_waic_wrong:.4f}"
        )


class TestModelComparison:
    """Verify model comparison results."""

    def test_preferred_model(self):
        """Model B should be preferred (lower WAIC)."""
        data = load_output()
        assert data["model_comparison"]["preferred_model"] == "model_b", (
            "Model B (non-centered) should be preferred due to lower WAIC"
        )

    def test_delta_waic_positive(self):
        """Delta WAIC should be positive."""
        data = load_output()
        assert data["model_comparison"]["delta_waic"] > 0


class TestConvergenceReport:
    """Verify convergence classification."""

    def test_log_tau_not_converged(self):
        """log_tau in Model A must NOT be classified as converged."""
        data = load_output()
        report = data["model_a"]["convergence"]
        converged = report.get("converged", [])
        assert "log_tau" not in converged, (
            "log_tau must NOT be in converged list for model_a — "
            "it has high R-hat due to chains at different levels"
        )

    def test_log_tau_is_failed(self):
        """log_tau in Model A should be classified as failed."""
        data = load_output()
        report = data["model_a"]["convergence"]
        failed = report.get("failed", [])
        assert "log_tau" in failed, (
            "log_tau should be in failed list for model_a"
        )

    def test_model_b_all_converged(self):
        """All Model B parameters should be converged."""
        data = load_output()
        report = data["model_b"]["convergence"]
        converged = set(report.get("converged", []))
        param_names = get_param_names("model_b")

        for name in param_names:
            assert name in converged, (
                f"{name} should be converged in model_b, "
                f"converged list: {sorted(converged)}"
            )

    def test_report_has_required_keys(self):
        """Convergence report must have converged/marginal/failed keys."""
        data = load_output()
        for model in ["model_a", "model_b"]:
            report = data[model]["convergence"]
            for key in ["converged", "marginal", "failed"]:
                assert key in report, f"Missing '{key}' in {model} convergence report"
            # Each should be a list
            for key in ["converged", "marginal", "failed"]:
                assert isinstance(report[key], list), (
                    f"'{key}' in {model} convergence report should be a list"
                )


class TestMCSE:
    """Verify Monte Carlo Standard Error computation."""

    def test_mcse_positive(self):
        """All MCSE values must be positive."""
        data = load_output()
        for model in ["model_a", "model_b"]:
            for name, val in data[model]["mcse_mean"].items():
                assert val > 0, f"MCSE for {name} in {model} must be positive, got {val}"

    def test_mcse_log_tau_high(self):
        """MCSE for log_tau in Model A should be relatively high (poor convergence)."""
        data = load_output()
        mcse_log_tau = data["model_a"]["mcse_mean"]["log_tau"]
        mcse_mu = data["model_a"]["mcse_mean"]["mu"]
        # log_tau has much worse convergence, so its MCSE should be notably higher
        assert mcse_log_tau > mcse_mu, (
            f"MCSE for log_tau ({mcse_log_tau:.4f}) should exceed "
            f"MCSE for mu ({mcse_mu:.4f}) in model_a"
        )
