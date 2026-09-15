"""Tests for the multi-file clinical trial data processing pipeline.

Runs the R pipeline then validates every output section against
independently computed expected values.
"""


import csv
import json
import math
import os
import statistics
import subprocess

import pytest

INPUT_CSV = "/app/data/measurements.csv"
OUTPUT_JSON = "/app/output/results.json"
PIPELINE = "/app/pipeline.R"
TOL = 1e-4


def _read_csv():
    with open(INPUT_CSV) as f:
        return list(csv.DictReader(f))


def _safe_float(val):
    """Return float or None for empty / non-numeric strings."""
    if val is None or val.strip() == "":
        return None
    try:
        return float(val)
    except ValueError:
        return None


def _median(vals):
    """Compute median matching R's median() behaviour exactly."""
    s = sorted(vals)
    n = len(s)
    if n % 2 == 1:
        return s[n // 2]
    return (s[n // 2 - 1] + s[n // 2]) / 2


# ── run pipeline once for entire session ────────────────────────
@pytest.fixture(scope="session")
def pipeline_run():
    result = subprocess.run(
        ["Rscript", PIPELINE],
        capture_output=True,
        text=True,
        timeout=120,
    )
    return result


@pytest.fixture(scope="session")
def output(pipeline_run):
    assert pipeline_run.returncode == 0, (
        f"Pipeline failed (exit {pipeline_run.returncode}):\n"
        f"{pipeline_run.stderr}"
    )
    assert os.path.exists(OUTPUT_JSON), "results.json not created"
    with open(OUTPUT_JSON) as f:
        return json.load(f)


@pytest.fixture(scope="session")
def rows():
    return _read_csv()


# ── Section 1: Concentration ────────────────────────────────────
class TestConcentration:
    @staticmethod
    def _expected(rows):
        vals = [v for r in rows
                if (v := _safe_float(r["concentration"])) is not None]
        mean_c = sum(vals) / len(vals)
        median_c = _median(vals)
        return mean_c, median_c, len(vals)

    def test_n_valid(self, output, rows):
        _, _, n = self._expected(rows)
        assert output["concentration"]["n_valid"] == n

    def test_mean(self, output, rows):
        mean_c, _, _ = self._expected(rows)
        assert abs(output["concentration"]["mean_concentration"] - mean_c) < TOL

    def test_median(self, output, rows):
        _, median_c, _ = self._expected(rows)
        assert abs(
            output["concentration"]["median_concentration"] - median_c
        ) < TOL


# ── Section 2: Data Quality ─────────────────────────────────────
class TestQuality:
    def test_n_complete(self, output, rows):
        expected = sum(1 for r in rows if r["measurement"].strip() != "")
        assert output["quality"]["n_complete"] == expected

    def test_n_missing(self, output, rows):
        expected = sum(1 for r in rows if r["measurement"].strip() == "")
        assert output["quality"]["n_missing"] == expected

    def test_completeness_pct(self, output, rows):
        n_complete = sum(1 for r in rows if r["measurement"].strip() != "")
        expected = round(n_complete / len(rows) * 100, 2)
        assert abs(output["quality"]["completeness_pct"] - expected) < 0.01


# ── Section 3: Treatment Comparison ─────────────────────────────
class TestTreatment:
    @staticmethod
    def _expected(rows):
        drug = [
            float(r["measurement"])
            for r in rows
            if r["treatment"] == "drug" and r["measurement"].strip() != ""
        ]
        plac = [
            float(r["measurement"])
            for r in rows
            if r["treatment"] == "placebo" and r["measurement"].strip() != ""
        ]
        dm = sum(drug) / len(drug)
        pm = sum(plac) / len(plac)
        return dm, pm, dm - pm, len(rows)

    def test_drug_mean(self, output, rows):
        dm, _, _, _ = self._expected(rows)
        assert abs(output["treatment"]["drug_mean"] - dm) < TOL

    def test_placebo_mean(self, output, rows):
        _, pm, _, _ = self._expected(rows)
        assert abs(output["treatment"]["placebo_mean"] - pm) < TOL

    def test_effect_size(self, output, rows):
        _, _, es, _ = self._expected(rows)
        assert abs(output["treatment"]["effect_size"] - es) < TOL

    def test_n_analyzed(self, output, rows):
        _, _, _, n = self._expected(rows)
        assert output["treatment"]["n_analyzed"] == n


# ── Section 4: Site-Weighted Effect ─────────────────────────────
class TestWeightedEffect:
    SITES = ["alpha", "beta", "gamma"]

    @staticmethod
    def _site_effect(rows, site):
        sr = [
            r
            for r in rows
            if r["site"] == site and r["measurement"].strip() != ""
        ]
        d = [float(r["measurement"]) for r in sr if r["treatment"] == "drug"]
        p = [float(r["measurement"]) for r in sr if r["treatment"] == "placebo"]
        return sum(d) / len(d) - sum(p) / len(p), len(sr)

    def test_site_effects(self, output, rows):
        for s in self.SITES:
            eff, _ = self._site_effect(rows, s)
            got = output["weighted_effect"]["site_effects"][s]
            assert abs(got - eff) < TOL, f"site_effect[{s}] wrong"

    def test_site_sizes(self, output, rows):
        for s in self.SITES:
            _, n = self._site_effect(rows, s)
            got = output["weighted_effect"]["site_sample_sizes"][s]
            assert got == n, f"site_size[{s}] wrong"

    def test_overall_effect(self, output, rows):
        effects = [self._site_effect(rows, s)[0] for s in self.SITES]
        expected = sum(effects) / len(effects)
        assert (
            abs(output["weighted_effect"]["overall_weighted_effect"] - expected)
            < TOL
        )

    def test_weight_used(self, output):
        assert abs(output["weighted_effect"]["weight_used"] - 0.3) < TOL


# ── Section 5: Normalization ────────────────────────────────────
class TestNormalization:
    SITES = ["alpha", "beta", "gamma"]

    def test_normalized_means(self, output, rows):
        for s in self.SITES:
            baselines = [float(r["baseline"]) for r in rows if r["site"] == s]
            mean_bl = sum(baselines) / len(baselines)

            meas = [
                float(r["measurement"])
                for r in rows
                if r["site"] == s and r["measurement"].strip() != ""
            ]
            mean_m = sum(meas) / len(meas)

            expected = mean_m / mean_bl
            got = output["normalization"]["normalized_site_means"][s]
            assert abs(got - expected) < TOL, (
                f"norm[{s}]: got {got}, expected {expected}"
            )


# ── Section 6: Confidence Intervals ────────────────────────────
class TestConfidenceIntervals:
    SITES = ["alpha", "beta", "gamma"]

    @staticmethod
    def _expected_ci(rows, site):
        vals = [
            float(r["measurement"])
            for r in rows
            if r["site"] == site and r["measurement"].strip() != ""
        ]
        n = len(vals)
        m = sum(vals) / n
        var = sum((x - m) ** 2 for x in vals) / (n - 1)
        sd = math.sqrt(var)
        se = sd / math.sqrt(n)
        return se, m - 1.96 * se, m + 1.96 * se

    def test_se(self, output, rows):
        for s in self.SITES:
            se, _, _ = self._expected_ci(rows, s)
            got = output["confidence_intervals"][s]["se"]
            assert abs(got - se) < TOL, f"se[{s}]: got {got}, expected {se}"

    def test_ci_lower(self, output, rows):
        for s in self.SITES:
            _, cl, _ = self._expected_ci(rows, s)
            got = output["confidence_intervals"][s]["ci_lower"]
            assert abs(got - cl) < TOL, (
                f"ci_lower[{s}]: got {got}, expected {cl}"
            )

    def test_ci_upper(self, output, rows):
        for s in self.SITES:
            _, _, cu = self._expected_ci(rows, s)
            got = output["confidence_intervals"][s]["ci_upper"]
            assert abs(got - cu) < TOL, (
                f"ci_upper[{s}]: got {got}, expected {cu}"
            )


# ── Section 7: Outlier Analysis ─────────────────────────────────
class TestOutlierAnalysis:
    SITES = ["alpha", "beta", "gamma"]

    @staticmethod
    def _expected_outlier(rows, site):
        vals = [
            float(r["measurement"])
            for r in rows
            if r["site"] == site and r["measurement"].strip() != ""
        ]
        n = len(vals)
        m = sum(vals) / n
        sd = math.sqrt(sum((x - m) ** 2 for x in vals) / (n - 1))
        cap = m + 2 * sd
        capped = [min(x, cap) for x in vals]
        capped_mean = sum(capped) / len(capped)
        n_capped = sum(1 for x in vals if x > cap)
        return capped_mean, n_capped

    def test_capped_mean(self, output, rows):
        for s in self.SITES:
            expected_mean, _ = self._expected_outlier(rows, s)
            got = output["outlier_analysis"][s]["capped_mean"]
            assert abs(got - expected_mean) < TOL, (
                f"capped_mean[{s}]: got {got}, expected {expected_mean}"
            )

    def test_n_capped(self, output, rows):
        for s in self.SITES:
            _, expected_n = self._expected_outlier(rows, s)
            got = output["outlier_analysis"][s]["n_capped"]
            assert got == expected_n, (
                f"n_capped[{s}]: got {got}, expected {expected_n}"
            )


# ── Section 8: Robust Location Estimates ────────────────────────
class TestRobustMeans:
    SITES = ["alpha", "beta", "gamma"]

    @staticmethod
    def _huber_m_estimate(values, k=1.345, tol=1e-6, max_iter=100):
        """Compute Huber M-estimate of location with MAD scaling."""
        mu = _median(values)
        abs_devs = [abs(v - mu) for v in values]
        mad_scale = _median(abs_devs) * 1.4826
        if mad_scale == 0:
            return mu, 0
        for iteration in range(1, max_iter + 1):
            residuals = [(v - mu) / mad_scale for v in values]
            weights = [
                1.0 if abs(r) <= k else k / abs(r) for r in residuals
            ]
            total_w = sum(weights)
            mu_new = sum(w * v for w, v in zip(weights, values)) / total_w
            if abs(mu_new - mu) < tol:
                return mu_new, iteration
            mu = mu_new
        return mu, max_iter

    def test_huber_means(self, output, rows):
        for s in self.SITES:
            vals = [
                float(r["measurement"])
                for r in rows
                if r["site"] == s and r["measurement"].strip() != ""
            ]
            expected_mu, _ = self._huber_m_estimate(vals)
            got = output["robust_means"][s]["huber_mean"]
            assert abs(got - expected_mu) < TOL, (
                f"huber_mean[{s}]: got {got}, expected {expected_mu}"
            )

    def test_iterations_positive(self, output):
        for s in self.SITES:
            got = output["robust_means"][s]["iterations"]
            n = int(round(got))
            assert n == got, (
                f"iterations[{s}] must be a whole number, got {got}"
            )
            assert 1 <= n <= 100, (
                f"iterations[{s}] = {n}, expected 1..100"
            )


# ── Section 9: Hodges-Lehmann Treatment Effects ─────────────────
class TestHodgesLehmann:
    SITES = ["alpha", "beta", "gamma"]

    @staticmethod
    def _expected_hl(rows, site):
        sr = [
            r for r in rows
            if r["site"] == site and r["measurement"].strip() != ""
        ]
        drug = [float(r["measurement"]) for r in sr if r["treatment"] == "drug"]
        plac = [float(r["measurement"]) for r in sr if r["treatment"] == "placebo"]
        diffs = sorted([d - p for d in drug for p in plac])
        return _median(diffs)

    def test_hl_effects(self, output, rows):
        for s in self.SITES:
            expected = self._expected_hl(rows, s)
            got = output["hodges_lehmann"][s]
            assert abs(got - expected) < TOL, (
                f"hl[{s}]: got {got}, expected {expected}"
            )


# ── Section 10: Summary ────────────────────────────────────────
class TestSummary:
    SITES = ["alpha", "beta", "gamma"]

    def test_mean_normalized(self, output, rows):
        norms = []
        for s in self.SITES:
            baselines = [float(r["baseline"]) for r in rows if r["site"] == s]
            mean_bl = sum(baselines) / len(baselines)
            meas = [
                float(r["measurement"])
                for r in rows
                if r["site"] == s and r["measurement"].strip() != ""
            ]
            mean_m = sum(meas) / len(meas)
            norms.append(mean_m / mean_bl)
        expected = sum(norms) / len(norms)
        got = output["summary"]["mean_normalized"]
        assert abs(got - expected) < TOL, (
            f"mean_normalized: got {got}, expected {expected}"
        )

    def test_weighted_treatment_effect(self, output, rows):
        effects = []
        for s in self.SITES:
            sr = [
                r
                for r in rows
                if r["site"] == s and r["measurement"].strip() != ""
            ]
            d = [
                float(r["measurement"]) for r in sr if r["treatment"] == "drug"
            ]
            p = [
                float(r["measurement"])
                for r in sr
                if r["treatment"] == "placebo"
            ]
            effects.append(sum(d) / len(d) - sum(p) / len(p))
        overall = sum(effects) / len(effects)
        expected = overall * 0.3
        got = output["summary"]["weighted_treatment_effect"]
        assert abs(got - expected) < TOL, (
            f"weighted_treatment_effect: got {got}, expected {expected}"
        )

    def test_quality_adjusted_n(self, output, rows):
        expected = sum(1 for r in rows if r["measurement"].strip() != "")
        got = output["summary"]["quality_adjusted_n"]
        assert got == expected

    def test_reference_baselines(self, output, rows):
        for s in self.SITES:
            baselines = [
                float(r["baseline"]) for r in rows if r["site"] == s
            ]
            closest = min(baselines, key=lambda b: abs(b - 20.0))
            got = output["summary"]["reference_baselines"][s]
            assert abs(got - closest) < TOL, (
                f"ref_baseline[{s}]: got {got}, expected {closest}"
            )

    def test_mean_huber_estimate(self, output, rows):
        huber_means = []
        for s in self.SITES:
            vals = [
                float(r["measurement"])
                for r in rows
                if r["site"] == s and r["measurement"].strip() != ""
            ]
            mu = _median(vals)
            abs_devs = [abs(v - mu) for v in vals]
            mad_scale = _median(abs_devs) * 1.4826
            if mad_scale > 0:
                for _ in range(100):
                    residuals = [(v - mu) / mad_scale for v in vals]
                    weights = [
                        1.0 if abs(r) <= 1.345 else 1.345 / abs(r)
                        for r in residuals
                    ]
                    total_w = sum(weights)
                    mu_new = (
                        sum(w * v for w, v in zip(weights, vals)) / total_w
                    )
                    if abs(mu_new - mu) < 1e-6:
                        mu = mu_new
                        break
                    mu = mu_new
            huber_means.append(mu)
        expected = sum(huber_means) / len(huber_means)
        got = output["summary"]["mean_huber_estimate"]
        assert abs(got - expected) < TOL, (
            f"mean_huber_estimate: got {got}, expected {expected}"
        )

    def test_median_hl_effect(self, output, rows):
        hl_effects = []
        for s in self.SITES:
            sr = [
                r for r in rows
                if r["site"] == s and r["measurement"].strip() != ""
            ]
            drug = [
                float(r["measurement"]) for r in sr
                if r["treatment"] == "drug"
            ]
            plac = [
                float(r["measurement"]) for r in sr
                if r["treatment"] == "placebo"
            ]
            diffs = sorted([d - p for d in drug for p in plac])
            hl_effects.append(_median(diffs))
        expected = _median(hl_effects)
        got = output["summary"]["median_hl_effect"]
        assert abs(got - expected) < TOL, (
            f"median_hl_effect: got {got}, expected {expected}"
        )
