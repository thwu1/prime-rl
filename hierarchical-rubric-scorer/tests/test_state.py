
import json
import math

import numpy as np
import pytest


@pytest.fixture(scope="module")
def output():
    with open("/app/output/scores.json") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Expected values (analytically derived)
# ---------------------------------------------------------------------------
EXPECTED_SAMPLE_SCORES = {
    "paper_001": 0.824,
    "paper_002": 0.0,
    "paper_003": 0.8755,
    "paper_004": 0.374,
    "paper_005": 0.856,
}

EXPECTED_MEAN = 0.5859

EXPECTED_CRITERION_MEANS = {
    "data_pipeline": 0.8,
    "model_arch": 0.53,
    "accuracy": 0.47,
    "ablation": 0.6,
    "env_setup": 0.8,
    "run_script": 0.6,
    "methodology": 0.638,
    "results": 0.509,
    "reproducibility": 0.7,
    "root": 0.5859,
}

EXPECTED_FLEISS_KAPPA = 13.0 / 273.0  # approx 0.047619


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _compute_bootstrap_ci(scores, seed=42, n_resamples=10000):
    """Reference bootstrap CI computation."""
    rng = np.random.default_rng(seed)
    arr = np.array(scores)
    means = np.array(
        [np.mean(rng.choice(arr, size=len(arr), replace=True)) for _ in range(n_resamples)]
    )
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


# ---------------------------------------------------------------------------
# Test: output structure
# ---------------------------------------------------------------------------
class TestOutputStructure:
    def test_has_sample_scores(self, output):
        assert "sample_scores" in output

    def test_has_mean_score(self, output):
        assert "mean_score" in output

    def test_has_criterion_means(self, output):
        assert "criterion_means" in output

    def test_has_fleiss_kappa(self, output):
        assert "fleiss_kappa" in output

    def test_has_bootstrap_ci_lower(self, output):
        assert "bootstrap_ci_lower" in output

    def test_has_bootstrap_ci_upper(self, output):
        assert "bootstrap_ci_upper" in output

    def test_all_samples_present(self, output):
        for sid in EXPECTED_SAMPLE_SCORES:
            assert sid in output["sample_scores"], f"Missing sample {sid}"

    def test_all_criteria_present(self, output):
        for cid in EXPECTED_CRITERION_MEANS:
            assert cid in output["criterion_means"], f"Missing criterion {cid}"


# ---------------------------------------------------------------------------
# Test: per-sample scores
# ---------------------------------------------------------------------------
class TestSampleScores:
    @pytest.mark.parametrize(
        "sample_id,expected",
        list(EXPECTED_SAMPLE_SCORES.items()),
    )
    def test_sample_score(self, output, sample_id, expected):
        actual = output["sample_scores"][sample_id]
        assert math.isclose(actual, expected, abs_tol=1e-6), (
            f"{sample_id}: expected {expected}, got {actual}"
        )


# ---------------------------------------------------------------------------
# Test: dependency cascade verification
# ---------------------------------------------------------------------------
class TestDependencyCascade:
    def test_paper_002_all_zero(self, output):
        assert math.isclose(output["sample_scores"]["paper_002"], 0.0, abs_tol=1e-9)

    def test_paper_004_partial_cascade(self, output):
        assert math.isclose(output["sample_scores"]["paper_004"], 0.374, abs_tol=1e-6)


# ---------------------------------------------------------------------------
# Test: criterion means
# ---------------------------------------------------------------------------
class TestCriterionMeans:
    @pytest.mark.parametrize(
        "criterion_id,expected",
        list(EXPECTED_CRITERION_MEANS.items()),
    )
    def test_criterion_mean(self, output, criterion_id, expected):
        actual = output["criterion_means"][criterion_id]
        assert math.isclose(actual, expected, abs_tol=1e-4), (
            f"{criterion_id}: expected {expected}, got {actual}"
        )


# ---------------------------------------------------------------------------
# Test: aggregate statistics
# ---------------------------------------------------------------------------
class TestStatistics:
    def test_mean_score(self, output):
        assert math.isclose(output["mean_score"], EXPECTED_MEAN, abs_tol=1e-4)

    def test_fleiss_kappa(self, output):
        assert math.isclose(output["fleiss_kappa"], EXPECTED_FLEISS_KAPPA, abs_tol=1e-4), (
            f"Expected Fleiss' kappa ~ {EXPECTED_FLEISS_KAPPA:.6f}, "
            f"got {output['fleiss_kappa']:.6f}"
        )

    def test_bootstrap_ci_bounds_ordered(self, output):
        assert output["bootstrap_ci_lower"] < output["mean_score"] < output["bootstrap_ci_upper"]

    def test_bootstrap_ci_within_range(self, output):
        assert 0.0 <= output["bootstrap_ci_lower"]
        assert output["bootstrap_ci_upper"] <= 1.0

    def test_bootstrap_ci_values(self, output):
        """Verify bootstrap CI matches an independent computation with the same seed."""
        scores = [EXPECTED_SAMPLE_SCORES[s] for s in sorted(EXPECTED_SAMPLE_SCORES)]
        ref_lower, ref_upper = _compute_bootstrap_ci(scores, seed=42, n_resamples=10000)
        assert math.isclose(output["bootstrap_ci_lower"], ref_lower, abs_tol=1e-2), (
            f"CI lower: expected ~ {ref_lower:.4f}, got {output['bootstrap_ci_lower']:.4f}"
        )
        assert math.isclose(output["bootstrap_ci_upper"], ref_upper, abs_tol=1e-2), (
            f"CI upper: expected ~ {ref_upper:.4f}, got {output['bootstrap_ci_upper']:.4f}"
        )


# ---------------------------------------------------------------------------
# Test: data quality handling
# ---------------------------------------------------------------------------
class TestDataQuality:
    def test_duplicate_handling(self, output):
        """Judgments file has duplicate for (paper_003, judge_B, model_arch).
        Correct handling should use the later entry, producing correct score."""
        assert math.isclose(output["sample_scores"]["paper_003"], 0.8755, abs_tol=1e-6)

    def test_unknown_criterion_ignored(self, output):
        """An entry for 'nonexistent_criterion' should not appear in output."""
        assert "nonexistent_criterion" not in output.get("criterion_means", {})
