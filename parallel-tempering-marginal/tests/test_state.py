"""
Tests for log marginal likelihood estimation and posterior summaries
for the unidentifiable binomial model.
"""

import json
import math
import numpy as np
from scipy.special import gammaln, digamma, betaln
from scipy import integrate


def load_data():
    with open('/app/data.json') as f:
        return json.load(f)


def load_results():
    with open('/app/results.json') as f:
        return json.load(f)


def analytical_log_marginal_likelihood(n, k):
    """
    Analytical log marginal likelihood for the unidentifiable binomial model.

    The joint density of p = p1*p2 when p1,p2 ~ Uniform(0,1)
    has PDF f(p) = -log(p). The marginal likelihood integral becomes:
    P(data) = C(n,k) * integral_0^1 p^k (1-p)^(n-k) (-log p) dp
            = C(n,k) * B(k+1, n-k+1) * [psi(n+2) - psi(k+1)]
    """
    log_binom = gammaln(n + 1) - gammaln(k + 1) - gammaln(n - k + 1)
    log_beta_val = betaln(k + 1, n - k + 1)
    psi_diff = digamma(n + 2) - digamma(k + 1)
    assert psi_diff > 0, "digamma difference must be positive"
    return log_binom + log_beta_val + np.log(psi_diff)


def quadrature_log_marginal_likelihood(n, k):
    """Cross-check using numerical double integration."""
    log_binom = gammaln(n + 1) - gammaln(k + 1) - gammaln(n - k + 1)

    def integrand(p2, p1):
        p = p1 * p2
        if p <= 0.0 or p >= 1.0:
            return 0.0
        return p ** k * (1.0 - p) ** (n - k)

    result, _ = integrate.dblquad(
        integrand, 0.0, 1.0, 0.0, 1.0,
        epsabs=1e-12, epsrel=1e-12
    )
    return log_binom + np.log(result)


def analytical_posterior_mean_p(n, k):
    """
    Analytical E[p1*p2 | data] using beta/digamma identities.
    """
    log_beta_ratio = betaln(k + 2, n - k + 1) - betaln(k + 1, n - k + 1)
    beta_ratio = np.exp(log_beta_ratio)
    psi_num = digamma(n + 3) - digamma(k + 2)
    psi_den = digamma(n + 2) - digamma(k + 1)
    return beta_ratio * psi_num / psi_den


def analytical_posterior_second_moment_p(n, k):
    """
    Analytical E[(p1*p2)^2 | data] using beta/digamma identities.
    """
    log_beta_ratio = betaln(k + 3, n - k + 1) - betaln(k + 1, n - k + 1)
    beta_ratio = np.exp(log_beta_ratio)
    psi_num = digamma(n + 4) - digamma(k + 3)
    psi_den = digamma(n + 2) - digamma(k + 1)
    return beta_ratio * psi_num / psi_den


def analytical_posterior_std_p(n, k):
    """
    Analytical std(p1*p2 | data) from first and second moments.
    """
    mean_p = analytical_posterior_mean_p(n, k)
    second_moment = analytical_posterior_second_moment_p(n, k)
    variance = second_moment - mean_p ** 2
    assert variance > 0, f"Variance must be positive, got {variance}"
    return np.sqrt(variance)


class TestAnalyticalFormulas:
    """Sanity-check that analytical formulas agree with numerical quadrature."""

    def test_log_ml_analytical_vs_quadrature(self):
        data = load_data()
        n, k = data['n_trials'], data['n_successes']
        val_analytical = analytical_log_marginal_likelihood(n, k)
        val_quadrature = quadrature_log_marginal_likelihood(n, k)
        assert abs(val_analytical - val_quadrature) < 0.01, (
            f"Analytical ({val_analytical:.6f}) and quadrature ({val_quadrature:.6f}) "
            f"disagree by {abs(val_analytical - val_quadrature):.6f}"
        )

    def test_posterior_mean_analytical_sanity(self):
        data = load_data()
        n, k = data['n_trials'], data['n_successes']
        mean_p = analytical_posterior_mean_p(n, k)
        assert 0 < mean_p < 1, f"Posterior mean {mean_p} out of (0,1)"
        assert abs(mean_p - k / n) < 0.15, (
            f"Posterior mean {mean_p} is unexpectedly far from MLE {k/n}"
        )

    def test_posterior_std_analytical_sanity(self):
        data = load_data()
        n, k = data['n_trials'], data['n_successes']
        std_p = analytical_posterior_std_p(n, k)
        assert 0 < std_p < 0.5, f"Posterior std {std_p} out of expected range"


class TestResultsExist:
    """Verify results.json exists and has required fields."""

    def test_results_file_exists(self):
        results = load_results()
        assert isinstance(results, dict), "results.json must contain a JSON object"

    def test_required_fields(self):
        results = load_results()
        required = ['log_marginal_likelihood', 'posterior_mean_p', 'posterior_std_p']
        for field in required:
            assert field in results, f"Missing required field: {field}"

    def test_field_types(self):
        results = load_results()
        assert isinstance(results['log_marginal_likelihood'], (int, float)), \
            "log_marginal_likelihood must be numeric"
        assert isinstance(results['posterior_mean_p'], (int, float)), \
            "posterior_mean_p must be numeric"
        assert isinstance(results['posterior_std_p'], (int, float)), \
            "posterior_std_p must be numeric"

    def test_all_finite(self):
        results = load_results()
        for key in ['log_marginal_likelihood', 'posterior_mean_p', 'posterior_std_p']:
            assert math.isfinite(results[key]), f"{key} must be finite, got {results[key]}"


class TestLogMarginalLikelihood:
    """Verify the log marginal likelihood estimate."""

    def test_accuracy(self):
        data = load_data()
        results = load_results()
        n, k = data['n_trials'], data['n_successes']
        true_val = analytical_log_marginal_likelihood(n, k)
        est = results['log_marginal_likelihood']
        tolerance = 1.5
        assert abs(est - true_val) < tolerance, (
            f"Estimate {est:.4f} is too far from "
            f"true log marginal likelihood {true_val:.4f} "
            f"(difference: {abs(est - true_val):.4f}, tolerance: {tolerance})"
        )

    def test_reasonable_range(self):
        results = load_results()
        est = results['log_marginal_likelihood']
        assert -20.0 < est < 0.0, (
            f"log_marginal_likelihood {est} is outside plausible range (-20, 0)"
        )


class TestPosteriorMean:
    """Verify the posterior mean of p = p1*p2."""

    def test_accuracy(self):
        data = load_data()
        results = load_results()
        n, k = data['n_trials'], data['n_successes']
        true_mean = analytical_posterior_mean_p(n, k)
        est = results['posterior_mean_p']
        tolerance = 0.1
        assert abs(est - true_mean) < tolerance, (
            f"Estimated posterior mean {est:.4f} too far from "
            f"true value {true_mean:.4f} "
            f"(difference: {abs(est - true_mean):.4f}, tolerance: {tolerance})"
        )

    def test_in_unit_interval(self):
        results = load_results()
        est = results['posterior_mean_p']
        assert 0.0 < est < 1.0, f"Posterior mean must be in (0,1), got {est}"


class TestPosteriorStd:
    """Verify the posterior standard deviation of p = p1*p2."""

    def test_accuracy(self):
        data = load_data()
        results = load_results()
        n, k = data['n_trials'], data['n_successes']
        true_std = analytical_posterior_std_p(n, k)
        est = results['posterior_std_p']
        tolerance = 0.05
        assert abs(est - true_std) < tolerance, (
            f"Estimated posterior std {est:.4f} too far from "
            f"true value {true_std:.4f} "
            f"(difference: {abs(est - true_std):.4f}, tolerance: {tolerance})"
        )

    def test_positive(self):
        results = load_results()
        assert results['posterior_std_p'] > 0, (
            f"Posterior std must be positive, got {results['posterior_std_p']}"
        )

    def test_reasonable_range(self):
        results = load_results()
        est = results['posterior_std_p']
        assert 0.001 < est < 0.3, (
            f"Posterior std {est} is outside reasonable range (0.001, 0.3)"
        )
