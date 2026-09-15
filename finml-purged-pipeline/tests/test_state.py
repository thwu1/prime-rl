"""
Tests for Financial Feature Classification Pipeline.

Verifies that /app/results/results.json and /app/results/analysis.db contain
correct, self-consistent outputs from a properly implemented pipeline that
handles temporal overlap bias in sampling, evaluation, and feature importance.
"""
import json
import os
import sqlite3

import pytest


RESULTS_PATH = "/app/results/results.json"
ANALYSIS_DB_PATH = "/app/results/analysis.db"
N_SAMPLES = 5000
N_FEATURES = 20

# Reconstruct ground truth from data generation column permutation
_PERM = [14, 3, 8, 18, 1, 12, 7, 16, 0, 10, 5, 19, 9, 15, 2, 6, 17, 4, 11, 13]
_GT = {}
for _i, _p in enumerate(_PERM):
    _name = f"F_{_i:02d}"
    _GT[_name] = "informative" if _p < 5 else ("redundant" if _p < 10 else "noise")
_INFORMATIVE = frozenset(f for f, t in _GT.items() if t == "informative")
_REDUNDANT = frozenset(f for f, t in _GT.items() if t == "redundant")
_NOISE = frozenset(f for f, t in _GT.items() if t == "noise")
_SIGNAL = _INFORMATIVE | _REDUNDANT


@pytest.fixture
def results():
    assert os.path.exists(RESULTS_PATH), f"Results file not found at {RESULTS_PATH}"
    with open(RESULTS_PATH) as f:
        return json.load(f)


@pytest.fixture
def analysis_db():
    assert os.path.exists(ANALYSIS_DB_PATH), f"Analysis DB not found at {ANALYSIS_DB_PATH}"
    con = sqlite3.connect(ANALYSIS_DB_PATH)
    yield con
    con.close()


# ─────────────────────────────────────────────────────────────
# 1. Results structure
# ─────────────────────────────────────────────────────────────


class TestResultsStructure:
    def test_results_file_exists(self):
        assert os.path.exists(RESULTS_PATH)

    def test_analysis_db_exists(self):
        assert os.path.exists(ANALYSIS_DB_PATH)

    def test_has_sampling_analysis(self, results):
        sa = results.get("sampling_analysis", {})
        assert "avg_uniqueness_corrected" in sa
        assert "avg_uniqueness_random" in sa

    def test_has_sample_weights(self, results):
        sw = results.get("sample_weights", {})
        for key in ("mean_uniqueness", "mean_weight", "std_weight", "n_samples"):
            assert key in sw, f"Missing key {key} in sample_weights"

    def test_has_evaluation(self, results):
        ev = results.get("evaluation", {})
        for key in ("mean_score", "std_score", "scores", "n_splits",
                     "n_excluded_per_fold"):
            assert key in ev, f"Missing key {key} in evaluation"

    def test_has_feature_importance_rankings(self, results):
        fi = results.get("feature_importance", {})
        rankings = fi.get("rankings", {})
        assert len(rankings) >= 2, "Need at least 2 importance methods"

    def test_has_feature_classification(self, results):
        fc = results.get("feature_classification", {})
        assert len(fc) == N_FEATURES


# ─────────────────────────────────────────────────────────────
# 2. Sampling analysis
# ─────────────────────────────────────────────────────────────


class TestSamplingAnalysis:
    def test_corrected_beats_random(self, results):
        sa = results["sampling_analysis"]
        assert sa["avg_uniqueness_corrected"] > sa["avg_uniqueness_random"], (
            f"Corrected ({sa['avg_uniqueness_corrected']:.4f}) must exceed "
            f"random ({sa['avg_uniqueness_random']:.4f})"
        )

    def test_meaningfully_better(self, results):
        sa = results["sampling_analysis"]
        ratio = sa["avg_uniqueness_corrected"] / sa["avg_uniqueness_random"]
        assert ratio > 1.005, f"Ratio {ratio:.4f} too small"

    def test_values_in_range(self, results):
        sa = results["sampling_analysis"]
        assert 0 < sa["avg_uniqueness_corrected"] <= 1
        assert 0 < sa["avg_uniqueness_random"] <= 1


# ─────────────────────────────────────────────────────────────
# 3. Sample weights
# ─────────────────────────────────────────────────────────────


class TestSampleWeights:
    def test_mean_weight_normalized(self, results):
        sw = results["sample_weights"]
        assert 0.8 < sw["mean_weight"] < 1.2, (
            f"Mean weight {sw['mean_weight']:.4f} should be ~1.0"
        )

    def test_weight_variance(self, results):
        assert results["sample_weights"]["std_weight"] > 0

    def test_uniqueness_range(self, results):
        assert 0 < results["sample_weights"]["mean_uniqueness"] <= 1

    def test_n_samples(self, results):
        assert results["sample_weights"]["n_samples"] == N_SAMPLES


# ─────────────────────────────────────────────────────────────
# 4. Evaluation
# ─────────────────────────────────────────────────────────────


class TestEvaluation:
    def test_exclusions_occurred(self, results):
        n_excl = results["evaluation"]["n_excluded_per_fold"]
        assert any(n > 0 for n in n_excl), "No observations excluded — leakage likely"

    def test_score_not_inflated(self, results):
        assert results["evaluation"]["mean_score"] < 0.95, (
            "Score suspiciously high — possible leakage"
        )

    def test_score_above_random(self, results):
        assert results["evaluation"]["mean_score"] > 0.45, (
            "Score below chance — implementation may be broken"
        )

    def test_multiple_folds(self, results):
        ev = results["evaluation"]
        assert ev["n_splits"] >= 3
        assert len(ev["scores"]) == ev["n_splits"]

    def test_scores_vary(self, results):
        scores = results["evaluation"]["scores"]
        assert max(scores) - min(scores) > 0.001

    def test_exclusion_fraction_reasonable(self, results):
        for n in results["evaluation"]["n_excluded_per_fold"]:
            assert n / N_SAMPLES < 0.5


# ─────────────────────────────────────────────────────────────
# 5. Feature importance
# ─────────────────────────────────────────────────────────────


class TestFeatureImportance:
    def test_rankings_complete(self, results):
        for method, ranking in results["feature_importance"]["rankings"].items():
            assert len(ranking) == N_FEATURES, (
                f"{method} has {len(ranking)} features, expected {N_FEATURES}"
            )

    def test_signal_in_top10(self, results):
        """At least one method must rank >=5 signal features in its top 10."""
        for method, ranking in results["feature_importance"]["rankings"].items():
            top10 = set(ranking[:10])
            if len(top10 & _SIGNAL) >= 5:
                return
        pytest.fail("No method ranked >=5 signal features in its top 10")

    def test_noise_not_dominant_top5(self, results):
        for method, ranking in results["feature_importance"]["rankings"].items():
            top5 = set(ranking[:5])
            assert len(top5 & _NOISE) <= 3, f"{method}: noise dominates top 5"


# ─────────────────────────────────────────────────────────────
# 6. Feature classification
# ─────────────────────────────────────────────────────────────


class TestFeatureClassification:
    def test_valid_labels(self, results):
        valid = {"informative", "redundant", "noise"}
        for feat, cls in results["feature_classification"].items():
            assert cls in valid, f"Invalid label '{cls}' for {feat}"

    def test_informative_not_noise(self, results):
        fc = results["feature_classification"]
        non_noise = sum(1 for f in _INFORMATIVE if fc.get(f) != "noise")
        assert non_noise >= 3, (
            f"At least 3/5 informative features must not be noise, got {non_noise}"
        )

    def test_noise_identified(self, results):
        fc = results["feature_classification"]
        correct = sum(1 for f in _NOISE if fc.get(f) == "noise")
        assert correct >= 6, (
            f"At least 6/10 noise features must be noise, got {correct}"
        )

    def test_consistency_with_rankings(self, results):
        fi = results["feature_importance"]
        fc = results["feature_classification"]
        all_top15 = set()
        for ranking in fi["rankings"].values():
            all_top15 |= set(ranking[:15])
        for feat, cls in fc.items():
            if cls == "informative":
                assert feat in all_top15, (
                    f"{feat} classified informative but absent from all top-15"
                )


# ─────────────────────────────────────────────────────────────
# 7. SQLite analysis database
# ─────────────────────────────────────────────────────────────


class TestAnalysisDB:
    def test_sample_weights_count(self, analysis_db):
        cur = analysis_db.execute("SELECT COUNT(*) FROM sample_weights")
        assert cur.fetchone()[0] == N_SAMPLES

    def test_sample_weights_columns(self, analysis_db):
        cur = analysis_db.execute("PRAGMA table_info(sample_weights)")
        cols = {row[1] for row in cur.fetchall()}
        assert {"date", "weight", "uniqueness"}.issubset(cols)

    def test_cv_folds_exist(self, analysis_db):
        cur = analysis_db.execute(
            "SELECT COUNT(DISTINCT fold) FROM cv_assignments"
        )
        assert cur.fetchone()[0] >= 3

    def test_cv_roles_exist(self, analysis_db):
        cur = analysis_db.execute("SELECT DISTINCT role FROM cv_assignments")
        roles = {row[0] for row in cur.fetchall()}
        assert {"train", "test", "excluded"}.issubset(roles)

    def test_cv_exclusions_in_db(self, analysis_db):
        cur = analysis_db.execute(
            "SELECT COUNT(*) FROM cv_assignments WHERE role='excluded'"
        )
        assert cur.fetchone()[0] > 0

    def test_feature_scores_methods(self, analysis_db):
        cur = analysis_db.execute(
            "SELECT COUNT(DISTINCT method) FROM feature_scores"
        )
        assert cur.fetchone()[0] >= 2

    def test_feature_scores_completeness(self, analysis_db):
        cur = analysis_db.execute(
            "SELECT COUNT(DISTINCT feature) FROM feature_scores"
        )
        assert cur.fetchone()[0] == N_FEATURES

    def test_cv_exclusion_count_matches_json(self, results, analysis_db):
        """Exclusion counts in SQLite must match JSON — prevents faking."""
        json_excl = results["evaluation"]["n_excluded_per_fold"]
        for fold_idx, expected_n in enumerate(json_excl):
            cur = analysis_db.execute(
                "SELECT COUNT(*) FROM cv_assignments "
                "WHERE fold=? AND role='excluded'",
                (fold_idx,)
            )
            db_n = cur.fetchone()[0]
            assert db_n == expected_n, (
                f"Fold {fold_idx}: JSON={expected_n}, DB={db_n}"
            )

    def test_sample_weights_match_json(self, results, analysis_db):
        """Weight statistics in SQLite must match JSON — prevents faking."""
        cur = analysis_db.execute(
            "SELECT AVG(weight), AVG(uniqueness) FROM sample_weights"
        )
        db_mean_w, db_mean_u = cur.fetchone()
        json_mean_w = results["sample_weights"]["mean_weight"]
        json_mean_u = results["sample_weights"]["mean_uniqueness"]
        assert abs(db_mean_w - json_mean_w) < 0.01, (
            f"Weight mismatch: JSON={json_mean_w:.4f}, DB={db_mean_w:.4f}"
        )
        assert abs(db_mean_u - json_mean_u) < 0.01, (
            f"Uniqueness mismatch: JSON={json_mean_u:.4f}, DB={db_mean_u:.4f}"
        )

    def test_feature_scores_signal_above_noise(self, analysis_db):
        """Signal features must have higher average scores than noise."""
        cur = analysis_db.execute(
            "SELECT feature, AVG(score) as avg_score "
            "FROM feature_scores GROUP BY feature"
        )
        scores = {row[0]: row[1] for row in cur.fetchall()}
        signal_scores = [scores[f] for f in _SIGNAL if f in scores]
        noise_scores = [scores[f] for f in _NOISE if f in scores]
        signal_avg = (sum(signal_scores) / len(signal_scores)
                      if signal_scores else 0)
        noise_avg = (sum(noise_scores) / len(noise_scores)
                     if noise_scores else 0)
        assert signal_avg > noise_avg, (
            f"Signal avg ({signal_avg:.4f}) must exceed noise ({noise_avg:.4f})"
        )
