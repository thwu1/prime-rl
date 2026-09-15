
import json
import os
import pytest

OUTPUT_DIR = "/app/output"


@pytest.fixture(scope="module")
def validation_report():
    path = os.path.join(OUTPUT_DIR, "validation_report.json")
    assert os.path.exists(path), "validation_report.json not found"
    with open(path) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def metrics():
    path = os.path.join(OUTPUT_DIR, "metrics.json")
    assert os.path.exists(path), "metrics.json not found"
    with open(path) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def rankings():
    path = os.path.join(OUTPUT_DIR, "rankings.json")
    assert os.path.exists(path), "rankings.json not found"
    with open(path) as f:
        return json.load(f)


# -- Validation tests --


class TestValidation:
    def test_malformed_file_is_invalid(self, validation_report):
        """disc_malformed_set1 has out-of-range scores and missing fields."""
        key = "disc_malformed_set1"
        assert key in validation_report, f"{key} not in validation report"
        entry = validation_report[key]
        assert entry["valid"] is False, "Malformed file should be invalid"
        assert len(entry["errors"]) >= 3, (
            f"Expected at least 3 errors (out-of-range ai_likelihood, missing ai_likelihood, "
            f"negative believability, missing believability), got {len(entry['errors'])}"
        )

    def test_valid_files_pass(self, validation_report):
        """All non-malformed files should pass validation."""
        valid_files = [
            "disc_reliable_set1",
            "disc_reliable_set2",
            "disc_biased_set1",
            "disc_uncalibrated_set1",
            "disc_degenerate_set3",
        ]
        for key in valid_files:
            assert key in validation_report, f"{key} not in validation report"
            assert validation_report[key]["valid"] is True, (
                f"{key} should be valid but got errors: {validation_report[key].get('errors')}"
            )

    def test_all_prediction_files_covered(self, validation_report):
        """Validation report should cover all 6 prediction files."""
        assert len(validation_report) == 6, (
            f"Expected 6 entries in validation report, got {len(validation_report)}"
        )


# -- Metric tests: disc_reliable on set_alpha --


class TestDiscReliableSet1:
    """disc_reliable on set_alpha: good discriminator, imperfect separation."""

    def test_auc_roc(self, metrics):
        m = metrics["disc_reliable_set1"]
        assert m["auc_roc"] == pytest.approx(0.95, abs=0.001)

    def test_brier_score(self, metrics):
        m = metrics["disc_reliable_set1"]
        assert m["brier_score"] == pytest.approx(0.107565, abs=0.002)

    def test_ece(self, metrics):
        m = metrics["disc_reliable_set1"]
        assert m["ece"] == pytest.approx(0.1565, abs=0.005)

    def test_no_over_deception(self, metrics):
        m = metrics["disc_reliable_set1"]
        assert m["over_deception"] is False

    def test_composite_score(self, metrics):
        m = metrics["disc_reliable_set1"]
        expected = 0.4 * 0.95 + 0.3 * (1 - 0.107565) + 0.3 * (1 - 0.1565)
        assert m["composite_score"] == pytest.approx(expected, abs=0.005)

    def test_n_predictions(self, metrics):
        m = metrics["disc_reliable_set1"]
        assert m["n_predictions"] == 20

    def test_eval_set(self, metrics):
        m = metrics["disc_reliable_set1"]
        assert m["eval_set"] == "set_alpha"

    def test_believability_stats(self, metrics):
        m = metrics["disc_reliable_set1"]
        assert m["mean_believability"] is not None
        assert m["max_believability"] is not None
        assert 0 <= m["mean_believability"] <= 1
        assert 0 <= m["max_believability"] <= 1
        assert m["max_believability"] >= m["mean_believability"]


# -- Metric tests: disc_biased on set_alpha (over-deception) --


class TestDiscBiasedSet1:
    """disc_biased: systematically assigns high AI-likelihood to human text."""

    def test_auc_roc_near_zero(self, metrics):
        m = metrics["disc_biased_set1"]
        assert m["auc_roc"] == pytest.approx(0.0, abs=0.001)

    def test_over_deception_flag(self, metrics):
        m = metrics["disc_biased_set1"]
        assert m["over_deception"] is True

    def test_high_brier_score(self, metrics):
        m = metrics["disc_biased_set1"]
        assert m["brier_score"] > 0.5

    def test_composite_score_low(self, metrics):
        m = metrics["disc_biased_set1"]
        assert m["composite_score"] is not None
        assert m["composite_score"] < 0.3


# -- Metric tests: disc_uncalibrated on set_alpha --


class TestDiscUncalibratedSet1:
    """disc_uncalibrated: perfect ranking but poorly calibrated scores."""

    def test_perfect_auc(self, metrics):
        m = metrics["disc_uncalibrated_set1"]
        assert m["auc_roc"] == pytest.approx(1.0, abs=0.001)

    def test_high_ece(self, metrics):
        m = metrics["disc_uncalibrated_set1"]
        assert m["ece"] > 0.25

    def test_moderate_brier(self, metrics):
        m = metrics["disc_uncalibrated_set1"]
        assert m["brier_score"] == pytest.approx(0.167, abs=0.005)

    def test_no_over_deception(self, metrics):
        m = metrics["disc_uncalibrated_set1"]
        assert m["over_deception"] is False


# -- Metric tests: disc_degenerate on set_gamma (single class) --


class TestDiscDegenerateSet3:
    """disc_degenerate: all-AI eval set, discrimination metric undefined."""

    def test_auc_null(self, metrics):
        m = metrics["disc_degenerate_set3"]
        assert m["auc_roc"] is None

    def test_composite_null(self, metrics):
        m = metrics["disc_degenerate_set3"]
        assert m["composite_score"] is None

    def test_brier_computed(self, metrics):
        m = metrics["disc_degenerate_set3"]
        assert m["brier_score"] is not None
        assert m["brier_score"] == pytest.approx(0.09385, abs=0.005)

    def test_no_human_believability(self, metrics):
        m = metrics["disc_degenerate_set3"]
        assert m["mean_human_believability"] is None


# -- Metric tests: disc_reliable on set_beta --


class TestDiscReliableSet2:
    """disc_reliable on set_beta: easier to detect generator."""

    def test_perfect_auc(self, metrics):
        m = metrics["disc_reliable_set2"]
        assert m["auc_roc"] == pytest.approx(1.0, abs=0.001)

    def test_lower_brier_than_set1(self, metrics):
        m1 = metrics["disc_reliable_set1"]
        m2 = metrics["disc_reliable_set2"]
        assert m2["brier_score"] < m1["brier_score"]

    def test_brier_value(self, metrics):
        m = metrics["disc_reliable_set2"]
        assert m["brier_score"] == pytest.approx(0.06257, abs=0.003)


# -- Malformed file exclusion --


class TestMalformedExclusion:
    def test_not_in_metrics(self, metrics):
        assert "disc_malformed_set1" not in metrics

    def test_not_in_rankings(self, rankings):
        names = [r["name"] for r in rankings]
        assert "disc_malformed_set1" not in names


# -- Rankings tests --


class TestRankings:
    def test_rankings_is_list(self, rankings):
        assert isinstance(rankings, list)

    def test_rankings_exclude_degenerate(self, rankings):
        """Entries with null composite (degenerate) should not appear."""
        names = [r["name"] for r in rankings]
        assert "disc_degenerate_set3" not in names

    def test_rankings_exclude_malformed(self, rankings):
        names = [r["name"] for r in rankings]
        assert "disc_malformed_set1" not in names

    def test_rankings_count(self, rankings):
        """4 valid prediction files with computable composite should be ranked."""
        assert len(rankings) == 4

    def test_rankings_descending_composite(self, rankings):
        """Rankings should be in descending composite score order."""
        scores = [r["composite_score"] for r in rankings]
        for i in range(len(scores) - 1):
            assert scores[i] >= scores[i + 1], (
                f"Ranking not descending at position {i}: {scores[i]} < {scores[i+1]}"
            )

    def test_biased_ranked_last(self, rankings):
        """disc_biased should be ranked last (worst composite)."""
        assert rankings[-1]["name"] == "disc_biased_set1"

    def test_reliable_set2_ranked_first(self, rankings):
        """disc_reliable_set2 should rank first (best overall)."""
        assert rankings[0]["name"] == "disc_reliable_set2"

    def test_rank_numbers_sequential(self, rankings):
        for i, r in enumerate(rankings):
            assert r["rank"] == i + 1

    def test_ranking_entries_have_required_fields(self, rankings):
        required = ["rank", "name", "team", "eval_set", "composite_score",
                     "auc_roc", "brier_score", "ece"]
        for r in rankings:
            for field in required:
                assert field in r, f"Missing field '{field}' in ranking entry"


# -- Output format tests --


class TestOutputFormat:
    def test_output_dir_exists(self):
        assert os.path.isdir(OUTPUT_DIR)

    def test_all_output_files_exist(self):
        for fname in ["validation_report.json", "metrics.json", "rankings.json"]:
            path = os.path.join(OUTPUT_DIR, fname)
            assert os.path.exists(path), f"{fname} not found in output"

    def test_metrics_values_rounded(self, metrics):
        """Numeric values should be rounded to 6 decimal places."""
        for key, m in metrics.items():
            if m.get("auc_roc") is not None:
                s = str(m["auc_roc"])
                if "." in s:
                    decimals = len(s.split(".")[1])
                    assert decimals <= 6, f"{key} auc_roc has {decimals} decimals"
