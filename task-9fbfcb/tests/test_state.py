
"""
Verification tests for ProUCL 5.2 UCL analysis engine.
Tests independently compute expected values using scipy/numpy and compare
against the agent's output in /app/results/analysis.json.
"""

import json
import math
import csv
import os
import numpy as np
from scipy import stats
import pytest


# ---------------------------------------------------------------------------
# Reference KM implementation for left-censored data
# ---------------------------------------------------------------------------

def km_left_censored(values, censored_flags, detection_limits):
    """
    Kaplan-Meier estimator for left-censored environmental data.
    Returns (km_mean, km_sd, km_se, S_final).
    """
    n = len(values)
    obs = []
    for i in range(n):
        if censored_flags[i]:
            obs.append((detection_limits[i], False))
        else:
            obs.append((values[i], True))

    # Sort descending; for ties, detects before censored
    obs.sort(key=lambda x: (-x[0], not x[1]))

    n_risk = n
    S = 1.0
    km_mean = 0.0
    km_mean_sq = 0.0

    i = 0
    while i < len(obs):
        v = obs[i][0]
        d = 0
        c = 0
        while i < len(obs) and obs[i][0] == v:
            if obs[i][1]:
                d += 1
            else:
                c += 1
            i += 1

        if n_risk > 0:
            S_new = S * (1 - d / n_risk)
        else:
            S_new = S
        mass = S - S_new
        if d > 0:
            km_mean += v * mass
            km_mean_sq += v ** 2 * mass
        n_risk -= (d + c)
        S = S_new

    km_var = km_mean_sq - km_mean ** 2
    km_sd = math.sqrt(max(km_var, 0))
    km_se = km_sd / math.sqrt(n)
    return km_mean, km_sd, km_se, S


def load_csv(path):
    """Load a CSV dataset, return parallel lists."""
    values = []
    censored = []
    dls = []
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            values.append(float(row["value"]))
            censored.append(int(row["censored"]))
            dl_str = row["detection_limit"].strip()
            dls.append(float(dl_str) if dl_str else None)
    return values, censored, dls


# ---------------------------------------------------------------------------
# Load agent output
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def results():
    path = "/app/results/analysis.json"
    assert os.path.exists(path), "Output file /app/results/analysis.json does not exist"
    with open(path) as f:
        data = json.load(f)
    return data


# ---------------------------------------------------------------------------
# Structural tests
# ---------------------------------------------------------------------------

class TestOutputStructure:
    def test_output_exists(self, results):
        assert isinstance(results, dict)

    def test_all_datasets_present(self, results):
        for name in ["site_alpha", "site_beta", "site_gamma", "site_delta"]:
            assert name in results, f"Missing dataset {name} in output"

    def test_uncensored_fields(self, results):
        for name in ["site_alpha", "site_beta"]:
            r = results[name]
            for field in [
                "n_total", "n_detect", "n_nondetect", "mean", "sd",
                "distribution", "recommended_method", "recommended_ucl",
            ]:
                assert field in r, f"Missing field '{field}' in {name}"
            assert "ucls" in r
            assert "gof" in r

    def test_censored_fields(self, results):
        for name in ["site_gamma", "site_delta"]:
            r = results[name]
            for field in [
                "n_total", "n_detect", "n_nondetect",
                "km_mean", "km_sd", "km_se",
                "recommended_method", "recommended_ucl",
            ]:
                assert field in r, f"Missing field '{field}' in {name}"
            assert "ucls" in r


# ---------------------------------------------------------------------------
# Site Alpha — Normal, uncensored (n=20)
# ---------------------------------------------------------------------------

ALPHA_DATA = [
    12.3, 14.1, 11.8, 13.5, 15.2, 12.7, 13.9, 11.2, 14.8, 13.1,
    12.5, 14.3, 13.7, 12.9, 13.4, 11.9, 14.6, 13.2, 12.1, 13.8,
]


class TestSiteAlpha:
    def test_counts(self, results):
        r = results["site_alpha"]
        assert r["n_total"] == 20
        assert r["n_detect"] == 20
        assert r["n_nondetect"] == 0

    def test_mean(self, results):
        r = results["site_alpha"]
        expected = float(np.mean(ALPHA_DATA))
        assert abs(r["mean"] - expected) < 0.02

    def test_sd(self, results):
        r = results["site_alpha"]
        expected = float(np.std(ALPHA_DATA, ddof=1))
        assert abs(r["sd"] - expected) < 0.02

    def test_gof_normal_passes(self, results):
        """This nearly-symmetric data should pass Shapiro-Wilk at alpha=0.01."""
        _, p = stats.shapiro(ALPHA_DATA)
        r = results["site_alpha"]
        assert r["gof"]["normal_pass"] == (p > 0.01)

    def test_distribution_normal(self, results):
        r = results["site_alpha"]
        assert r["distribution"].lower() == "normal"

    def test_recommended_method(self, results):
        r = results["site_alpha"]
        method = r["recommended_method"].lower()
        assert "student" in method or "t" in method

    def test_t_ucl_value(self, results):
        n = len(ALPHA_DATA)
        mean = float(np.mean(ALPHA_DATA))
        se = float(stats.sem(ALPHA_DATA))
        t_crit = float(stats.t.ppf(0.95, n - 1))
        expected = mean + t_crit * se
        r = results["site_alpha"]
        assert abs(r["recommended_ucl"] - expected) / expected < 0.03

    def test_ucls_contain_t(self, results):
        r = results["site_alpha"]
        assert "t_ucl" in r["ucls"]

    def test_ucl_greater_than_mean(self, results):
        r = results["site_alpha"]
        assert r["recommended_ucl"] > r["mean"]


# ---------------------------------------------------------------------------
# Site Beta — Right-skewed, uncensored (n=25)
# ---------------------------------------------------------------------------

BETA_DATA = [
    0.8, 1.4, 2.1, 2.9, 3.5, 4.3, 4.9, 5.8, 6.5, 7.4,
    8.3, 9.5, 10.8, 12.4, 14.2, 16.5, 19.1, 22.3, 26.4, 31.2,
    37.5, 45.8, 56.3, 71.2, 92.4,
]


class TestSiteBeta:
    def test_counts(self, results):
        r = results["site_beta"]
        assert r["n_total"] == 25
        assert r["n_detect"] == 25
        assert r["n_nondetect"] == 0

    def test_mean(self, results):
        r = results["site_beta"]
        expected = float(np.mean(BETA_DATA))
        assert abs(r["mean"] - expected) / expected < 0.01

    def test_sd(self, results):
        r = results["site_beta"]
        expected = float(np.std(BETA_DATA, ddof=1))
        assert abs(r["sd"] - expected) / expected < 0.01

    def test_not_classified_normal(self, results):
        """Highly skewed data must not be classified as Normal."""
        r = results["site_beta"]
        assert r["distribution"].lower() != "normal"

    def test_gof_normal_fails(self, results):
        """Shapiro-Wilk at alpha=0.01 should reject normality for this data."""
        _, p = stats.shapiro(BETA_DATA)
        r = results["site_beta"]
        expected_fail = p <= 0.01
        assert expected_fail, "Sanity check: beta data should fail normality"
        assert r["gof"]["normal_pass"] is False

    def test_recommended_ucl_consistent(self, results):
        """Recommended UCL method should match the distribution classification."""
        r = results["site_beta"]
        dist = r["distribution"].lower()
        method = r["recommended_method"].lower()
        if dist == "gamma":
            assert "gamma" in method or "adj" in method
        elif dist == "lognormal":
            assert "gamma" in method or "adj" in method or "t" in method
        elif dist == "nonparametric":
            assert "student" in method or "t" in method

    def test_ucl_greater_than_mean(self, results):
        r = results["site_beta"]
        assert r["recommended_ucl"] > r["mean"]

    def test_ucl_reasonable_range(self, results):
        """UCL should be between mean and some reasonable upper bound."""
        r = results["site_beta"]
        mean = float(np.mean(BETA_DATA))
        sd = float(np.std(BETA_DATA, ddof=1))
        assert r["recommended_ucl"] > mean
        assert r["recommended_ucl"] < mean + 5 * sd


# ---------------------------------------------------------------------------
# Site Gamma — Censored, 5 NDs out of 20 (25%), two DLs
# ---------------------------------------------------------------------------

GAMMA_DETECTED = [5.2, 3.8, 7.1, 4.5, 6.3, 5.9, 3.2, 4.8, 6.7, 5.1, 4.4, 5.6, 3.9, 7.3, 4.1]
GAMMA_DLS = [1.0, 2.0, 1.0, 2.0, 1.0]  # detection limits of the 5 NDs


class TestSiteGamma:
    def test_counts(self, results):
        r = results["site_gamma"]
        assert r["n_total"] == 20
        assert r["n_detect"] == 15
        assert r["n_nondetect"] == 5

    def test_km_mean(self, results):
        """Verify KM mean against reference implementation."""
        values, censored, dls = load_csv("/app/data/site_gamma.csv")
        ref_mean, _, _, _ = km_left_censored(values, censored, dls)

        r = results["site_gamma"]
        assert abs(r["km_mean"] - ref_mean) / max(abs(ref_mean), 0.001) < 0.03

    def test_km_sd(self, results):
        """Verify KM SD against reference."""
        values, censored, dls = load_csv("/app/data/site_gamma.csv")
        _, ref_sd, _, _ = km_left_censored(values, censored, dls)

        r = results["site_gamma"]
        assert abs(r["km_sd"] - ref_sd) / max(abs(ref_sd), 0.001) < 0.05

    def test_km_se(self, results):
        values, censored, dls = load_csv("/app/data/site_gamma.csv")
        _, _, ref_se, _ = km_left_censored(values, censored, dls)

        r = results["site_gamma"]
        assert abs(r["km_se"] - ref_se) / max(abs(ref_se), 0.001) < 0.05

    def test_km_S_final(self, results):
        values, censored, dls = load_csv("/app/data/site_gamma.csv")
        _, _, _, ref_S = km_left_censored(values, censored, dls)

        r = results["site_gamma"]
        assert abs(r["km_S_final"] - ref_S) < 0.02

    def test_km_not_inappropriate(self, results):
        """DLs are 1.0 and 2.0 — not order-of-magnitude difference.
        KM t-UCL should exceed DL/2 mean, so flag should be False."""
        r = results["site_gamma"]
        assert r["km_inappropriate"] is False

    def test_recommended_method_km(self, results):
        r = results["site_gamma"]
        method = r["recommended_method"].lower()
        assert "km" in method

    def test_km_t_ucl_value(self, results):
        """Verify KM (t) UCL independently."""
        values, censored, dls = load_csv("/app/data/site_gamma.csv")
        km_mean, _, km_se, _ = km_left_censored(values, censored, dls)
        n = len(values)
        t_crit = float(stats.t.ppf(0.95, n - 1))
        expected_ucl = km_mean + t_crit * km_se
        r = results["site_gamma"]
        assert "km_t_ucl" in r["ucls"]
        assert abs(r["ucls"]["km_t_ucl"] - expected_ucl) / max(abs(expected_ucl), 0.001) < 0.05

    def test_detected_mean(self, results):
        r = results["site_gamma"]
        expected = float(np.mean(GAMMA_DETECTED))
        assert abs(r["detected_mean"] - expected) < 0.02

    def test_dl_half_mean(self, results):
        """DL/2 substitution: NDs replaced by DL/2, then overall mean."""
        sub_values = list(GAMMA_DETECTED) + [dl / 2.0 for dl in GAMMA_DLS]
        expected = float(np.mean(sub_values))
        r = results["site_gamma"]
        assert abs(r["dl_half_mean"] - expected) < 0.02


# ---------------------------------------------------------------------------
# Site Delta — Censored, 12 NDs out of 25 (48%), three DLs (0.5, 1.0, 10.0)
# Order-of-magnitude difference in DLs triggers KM inappropriate flag
# ---------------------------------------------------------------------------

DELTA_DETECTED = [1.2, 1.5, 1.8, 2.1, 2.3, 2.5, 2.8, 3.1, 3.5, 3.9, 4.2, 4.8, 5.3]
DELTA_DLS = [0.5, 0.5, 1.0, 1.0, 1.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0]


class TestSiteDelta:
    def test_counts(self, results):
        r = results["site_delta"]
        assert r["n_total"] == 25
        assert r["n_detect"] == 13
        assert r["n_nondetect"] == 12

    def test_km_mean(self, results):
        values, censored, dls = load_csv("/app/data/site_delta.csv")
        ref_mean, _, _, _ = km_left_censored(values, censored, dls)

        r = results["site_delta"]
        assert abs(r["km_mean"] - ref_mean) / max(abs(ref_mean), 0.001) < 0.03

    def test_km_sd(self, results):
        values, censored, dls = load_csv("/app/data/site_delta.csv")
        _, ref_sd, _, _ = km_left_censored(values, censored, dls)

        r = results["site_delta"]
        assert abs(r["km_sd"] - ref_sd) / max(abs(ref_sd), 0.001) < 0.05

    def test_km_S_final(self, results):
        values, censored, dls = load_csv("/app/data/site_delta.csv")
        _, _, _, ref_S = km_left_censored(values, censored, dls)

        r = results["site_delta"]
        assert abs(r["km_S_final"] - ref_S) < 0.02

    def test_km_inappropriate_true(self, results):
        """DLs span 0.5 to 10.0 (20x). With many NDs at DL=10.0,
        the DL/2 substitution mean should exceed at least one KM UCL."""
        r = results["site_delta"]
        assert r["km_inappropriate"] is True

    def test_dl_half_mean(self, results):
        sub_values = list(DELTA_DETECTED) + [dl / 2.0 for dl in DELTA_DLS]
        expected = float(np.mean(sub_values))
        r = results["site_delta"]
        assert abs(r["dl_half_mean"] - expected) < 0.05

    def test_km_t_ucl_below_dl_half_mean(self, results):
        """KM (t) UCL should be below DL/2 substitution mean
        (this is what makes km_inappropriate True)."""
        r = results["site_delta"]
        assert r["ucls"]["km_t_ucl"] < r["dl_half_mean"]

    def test_recommended_method_km(self, results):
        r = results["site_delta"]
        method = r["recommended_method"].lower()
        assert "km" in method

    def test_km_t_ucl_value(self, results):
        values, censored, dls = load_csv("/app/data/site_delta.csv")
        km_mean, _, km_se, _ = km_left_censored(values, censored, dls)
        n = len(values)
        t_crit = float(stats.t.ppf(0.95, n - 1))
        expected_ucl = km_mean + t_crit * km_se
        r = results["site_delta"]
        assert abs(r["ucls"]["km_t_ucl"] - expected_ucl) / max(abs(expected_ucl), 0.001) < 0.05

    def test_detected_mean(self, results):
        r = results["site_delta"]
        expected = float(np.mean(DELTA_DETECTED))
        assert abs(r["detected_mean"] - expected) < 0.02


# ---------------------------------------------------------------------------
# Cross-dataset sanity checks
# ---------------------------------------------------------------------------

class TestCrossDataset:
    def test_all_ucls_positive(self, results):
        for name in ["site_alpha", "site_beta", "site_gamma", "site_delta"]:
            r = results[name]
            assert r["recommended_ucl"] > 0, f"{name}: recommended_ucl not positive"

    def test_all_ucls_greater_than_mean_or_km_mean(self, results):
        for name in ["site_alpha", "site_beta"]:
            r = results[name]
            assert r["recommended_ucl"] > r["mean"], f"{name}: UCL <= mean"
        for name in ["site_gamma", "site_delta"]:
            r = results[name]
            assert r["recommended_ucl"] > r["km_mean"], f"{name}: UCL <= km_mean"

    def test_percent_nd_values(self, results):
        assert results["site_alpha"]["percent_nd"] == 0.0
        assert results["site_beta"]["percent_nd"] == 0.0
        assert results["site_gamma"]["percent_nd"] == 25.0
        assert results["site_delta"]["percent_nd"] == 48.0

    def test_distribution_valid_values(self, results):
        valid = {"normal", "gamma", "lognormal", "nonparametric"}
        for name in results:
            dist = results[name]["distribution"].lower()
            assert dist in valid, f"{name}: invalid distribution '{dist}'"
