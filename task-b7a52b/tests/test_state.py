"""
Tests for the particle physics statistical analysis task.

"""
import json
import os
import math
import pytest


RESULTS_PATH = "/app/results.json"

# Reference values computed from an independent implementation
REF = {
    "mu_hat": 1.0233,
    "mu_hat_error": 0.4897,
    "significance": 2.1879,
    "p_value": 0.01434,
    "cls_mu1": 1.0,
    "upper_limit_95": 1.853,
}


@pytest.fixture(scope="module")
def results():
    assert os.path.isfile(RESULTS_PATH), (
        f"Results file not found at {RESULTS_PATH}. "
        "The analysis must write output to /app/results.json."
    )
    with open(RESULTS_PATH) as f:
        data = json.load(f)
    return data


REQUIRED_KEYS = [
    "mu_hat",
    "mu_hat_error",
    "significance",
    "p_value",
    "cls_mu1",
    "upper_limit_95",
]


def test_results_file_has_required_keys(results):
    """All required output keys must be present."""
    for key in REQUIRED_KEYS:
        assert key in results, f"Missing required key: {key}"


def test_mu_hat(results):
    """Best-fit signal strength should be close to reference."""
    mu_hat = results["mu_hat"]
    assert isinstance(mu_hat, (int, float)), "mu_hat must be numeric"
    assert mu_hat >= 0, "mu_hat must be non-negative"
    assert abs(mu_hat - REF["mu_hat"]) < 0.12, (
        f"mu_hat = {mu_hat}, expected ~{REF['mu_hat']} (tolerance 0.12)"
    )


def test_mu_hat_error(results):
    """Uncertainty on mu_hat should be in a reasonable range."""
    err = results["mu_hat_error"]
    assert isinstance(err, (int, float)), "mu_hat_error must be numeric"
    assert err > 0, "mu_hat_error must be positive"
    assert abs(err - REF["mu_hat_error"]) < 0.15, (
        f"mu_hat_error = {err}, expected ~{REF['mu_hat_error']} (tolerance 0.15)"
    )


def test_significance(results):
    """Observed significance in standard deviations."""
    sig = results["significance"]
    assert isinstance(sig, (int, float)), "significance must be numeric"
    assert sig >= 0, "significance must be non-negative"
    assert abs(sig - REF["significance"]) < 0.25, (
        f"significance = {sig}, expected ~{REF['significance']} (tolerance 0.25)"
    )


def test_p_value(results):
    """P-value for background-only hypothesis."""
    pv = results["p_value"]
    assert isinstance(pv, (int, float)), "p_value must be numeric"
    assert 0 < pv < 1, "p_value must be between 0 and 1"
    ratio = pv / REF["p_value"]
    assert 0.4 < ratio < 2.5, (
        f"p_value = {pv}, expected ~{REF['p_value']} (ratio tolerance 0.4-2.5)"
    )


def test_cls_mu1(results):
    """CLs at mu=1 should be close to 1.0 since mu_hat > 1."""
    cls = results["cls_mu1"]
    assert isinstance(cls, (int, float)), "cls_mu1 must be numeric"
    assert 0 <= cls <= 1.0 + 1e-6, "cls_mu1 must be between 0 and 1"
    assert cls > 0.4, (
        f"cls_mu1 = {cls}, expected ~1.0 (mu_hat > 1 means no exclusion power at mu=1)"
    )


def test_upper_limit_95(results):
    """95% CLs upper limit on signal strength."""
    ul = results["upper_limit_95"]
    assert isinstance(ul, (int, float)), "upper_limit_95 must be numeric"
    assert ul > 0, "upper_limit_95 must be positive"
    assert abs(ul - REF["upper_limit_95"]) < 0.35, (
        f"upper_limit_95 = {ul}, expected ~{REF['upper_limit_95']} (tolerance 0.35)"
    )


def test_physical_consistency(results):
    """Check internal consistency of results."""
    sig = results["significance"]
    pv = results["p_value"]
    mu_hat = results["mu_hat"]
    ul = results["upper_limit_95"]

    # significance and p_value should be consistent
    from scipy.stats import norm
    expected_pv = 1 - norm.cdf(sig)
    ratio = pv / expected_pv if expected_pv > 0 else float("inf")
    assert 0.5 < ratio < 2.0, (
        f"p_value={pv} and significance={sig} are inconsistent "
        f"(expected p_value from significance: {expected_pv})"
    )

    # Upper limit should be above mu_hat
    assert ul > mu_hat - 0.1, (
        f"upper_limit_95={ul} should be >= mu_hat={mu_hat}"
    )
