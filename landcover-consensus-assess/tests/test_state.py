
import sys
import os
import json
import csv
import subprocess
import math
import sqlite3

sys.path.insert(0, '/app')

import pytest
import numpy as np


# ─── Taxonomy ───────────────────────────────────────────────────────────────

class TestTaxonomy:
    def test_classes_l3_length(self):
        from lcnet.taxonomy import CLASSES_L3
        assert len(CLASSES_L3) == 7

    def test_classes_l3_names(self):
        from lcnet.taxonomy import CLASSES_L3
        expected = ["Snow/Ice", "Water", "Artificial", "Natural",
                     "Woody", "Cultivated", "Semi-Natural"]
        assert CLASSES_L3 == expected

    def test_classes_l2(self):
        from lcnet.taxonomy import CLASSES_L2
        assert CLASSES_L2 == ["Snow/Ice", "Water", "Bare Ground", "Woody", "Non-Woody"]

    def test_classes_l1(self):
        from lcnet.taxonomy import CLASSES_L1
        assert CLASSES_L1 == ["Bare", "Vegetation"]

    def test_l3_to_l2_mapping(self):
        from lcnet.taxonomy import L3_TO_L2
        assert L3_TO_L2 == {0: 0, 1: 1, 2: 2, 3: 2, 4: 3, 5: 4, 6: 4}

    def test_l3_to_l1_mapping(self):
        from lcnet.taxonomy import L3_TO_L1
        assert L3_TO_L1 == {0: 0, 1: 0, 2: 0, 3: 0, 4: 1, 5: 1, 6: 1}

    def test_bare_classes_map_to_l1_bare(self):
        from lcnet.taxonomy import L3_TO_L1
        for idx in [0, 1, 2, 3]:
            assert L3_TO_L1[idx] == 0, f"Class {idx} should map to Bare (0)"

    def test_vegetation_classes_map_to_l1_vegetation(self):
        from lcnet.taxonomy import L3_TO_L1
        for idx in [4, 5, 6]:
            assert L3_TO_L1[idx] == 1, f"Class {idx} should map to Vegetation (1)"


# ─── Consensus ──────────────────────────────────────────────────────────────

class TestConsensus:
    def test_unanimous_agreement(self):
        from lcnet.consensus import compute_consensus
        annotations = [np.array([0, 1, 2]),
                       np.array([0, 1, 2]),
                       np.array([0, 1, 2])]
        weights = [0.9, 0.85, 0.8]
        labels, scores = compute_consensus(annotations, weights)
        np.testing.assert_array_equal(labels, [0, 1, 2])
        assert all(s > 0.8 for s in scores)

    def test_high_weight_annotator_wins(self):
        """When a high-accuracy annotator disagrees with two low-accuracy ones."""
        from lcnet.consensus import compute_consensus
        annotations = [np.array([0]), np.array([1]), np.array([1])]
        weights = [0.95, 0.5, 0.5]
        labels, scores = compute_consensus(annotations, weights)
        assert labels[0] == 0

    def test_single_annotator(self):
        from lcnet.consensus import compute_consensus
        annotations = [np.array([3, 5, 6])]
        weights = [0.9]
        labels, scores = compute_consensus(annotations, weights)
        np.testing.assert_array_equal(labels, [3, 5, 6])

    def test_exact_consensus_values(self):
        """Verify exact probability computation.

        3 annotators, weights [0.9, 0.8, 0.7], 7 classes.
        Pixel 0 labels: [0, 0, 1]
        Normalized weights: [0.375, 1/3, 7/24]

        P(class 0) = 0.375*0.9 + (1/3)*0.8 + (7/24)*(0.3/6)
                   = 0.3375 + 0.26667 + 0.01458 = 0.61875
        """
        from lcnet.consensus import compute_consensus
        annotations = [np.array([0, 1, 2]),
                       np.array([0, 2, 2]),
                       np.array([1, 1, 3])]
        weights = [0.9, 0.8, 0.7]
        labels, scores = compute_consensus(annotations, weights, num_classes=7)

        np.testing.assert_array_equal(labels, [0, 1, 2])
        assert scores[0] == pytest.approx(0.61875, rel=1e-6)
        # Pixel 1 labels: [1, 2, 1]
        # P(1) = 0.375*0.9 + (1/3)*(0.2/6) + (7/24)*0.7
        assert scores[1] == pytest.approx(0.375 * 0.9 + (1/3) * (0.2/6) + (7/24) * 0.7, rel=1e-6)
        # Pixel 2 labels: [2, 2, 3] — same structure as pixel 0
        assert scores[2] == pytest.approx(0.61875, rel=1e-6)

    def test_two_class_consensus(self):
        """Consensus with num_classes=2."""
        from lcnet.consensus import compute_consensus
        annotations = [np.array([0, 1, 0]),
                       np.array([0, 0, 1])]
        weights = [0.8, 0.6]
        labels, scores = compute_consensus(annotations, weights, num_classes=2)
        assert labels[0] == 0  # Both say 0
        assert labels[1] == 1  # Higher-weight says 1
        # w_norm = [0.8/1.4, 0.6/1.4] = [4/7, 3/7]
        # P(1) = (4/7)*0.8 + (3/7)*0.4 = 3.2/7 + 1.2/7 = 4.4/7
        assert labels[1] == 1
        assert scores[1] == pytest.approx(4.4 / 7, rel=1e-6)

    def test_probabilities_sum_to_one(self):
        """Verify internal probability distributions sum to 1."""
        from lcnet.consensus import compute_consensus
        annotations = [np.array([0, 3, 6]),
                       np.array([2, 3, 4]),
                       np.array([5, 1, 6])]
        weights = [0.85, 0.75, 0.65]
        labels, scores = compute_consensus(annotations, weights, num_classes=7)
        assert len(labels) == 3
        assert all(0 < s <= 1 for s in scores)


# ─── Metrics ────────────────────────────────────────────────────────────────

class TestMetrics:
    def test_perfect_accuracy(self):
        from lcnet.metrics import assess
        predictions = [0, 1, 2, 3, 4, 5, 6]
        ground_truth = [0, 1, 2, 3, 4, 5, 6]
        result = assess(predictions, ground_truth)
        assert result["overall_accuracy"] == pytest.approx(1.0)
        assert result["cohens_kappa"] == pytest.approx(1.0)
        for name, m in result["per_class"].items():
            assert m["f1"] == pytest.approx(1.0), f"{name} F1 should be 1.0"
            assert m["precision"] == pytest.approx(1.0)
            assert m["recall"] == pytest.approx(1.0)

    def test_all_same_prediction(self):
        """All predicted as class 0 vs diverse truth."""
        from lcnet.metrics import assess
        predictions = [0] * 7
        ground_truth = list(range(7))
        result = assess(predictions, ground_truth)
        assert result["overall_accuracy"] == pytest.approx(1.0 / 7.0)
        assert result["cohens_kappa"] == pytest.approx(0.0)

    def test_kappa_zero(self):
        """50% accuracy with 50% chance agreement -> kappa = 0."""
        from lcnet.metrics import assess
        predictions = [0, 1, 0, 1]
        ground_truth = [0, 0, 1, 1]
        result = assess(predictions, ground_truth)
        assert result["overall_accuracy"] == pytest.approx(0.5)
        assert result["cohens_kappa"] == pytest.approx(0.0)

    def test_kappa_half(self):
        """Known case where kappa = 0.5."""
        from lcnet.metrics import assess
        predictions = [0, 0, 1, 2, 2, 2]
        ground_truth = [0, 1, 1, 2, 2, 0]
        result = assess(predictions, ground_truth)
        assert result["overall_accuracy"] == pytest.approx(2.0 / 3.0)
        assert result["cohens_kappa"] == pytest.approx(0.5)

    def test_kappa_negative_one(self):
        """Completely opposite predictions -> kappa = -1."""
        from lcnet.metrics import assess
        predictions = [0, 0, 1, 1]
        ground_truth = [1, 1, 0, 0]
        result = assess(predictions, ground_truth)
        assert result["overall_accuracy"] == pytest.approx(0.0)
        assert result["cohens_kappa"] == pytest.approx(-1.0)

    def test_kappa_degenerate_all_same(self):
        """All same class -> p_e = 1.0, OA = 1.0 -> kappa = 1.0."""
        from lcnet.metrics import assess
        predictions = [0, 0, 0, 0]
        ground_truth = [0, 0, 0, 0]
        result = assess(predictions, ground_truth)
        assert result["overall_accuracy"] == pytest.approx(1.0)
        assert result["cohens_kappa"] == pytest.approx(1.0)

    def test_per_class_metrics_detail(self):
        """Verify exact precision/recall/F1 for each class."""
        from lcnet.metrics import assess
        predictions = [0, 0, 1, 2, 2, 2]
        ground_truth = [0, 1, 1, 2, 2, 0]
        result = assess(predictions, ground_truth)
        pc = result["per_class"]

        # Class Snow/Ice(0): TP=1, FP=1, FN=1 -> P=0.5, R=0.5, F1=0.5
        assert pc["Snow/Ice"]["precision"] == pytest.approx(0.5)
        assert pc["Snow/Ice"]["recall"] == pytest.approx(0.5)
        assert pc["Snow/Ice"]["f1"] == pytest.approx(0.5)

        # Class Water(1): TP=1, FP=0, FN=1 -> P=1.0, R=0.5, F1=2/3
        assert pc["Water"]["precision"] == pytest.approx(1.0)
        assert pc["Water"]["recall"] == pytest.approx(0.5)
        assert pc["Water"]["f1"] == pytest.approx(2.0 / 3.0)

        # Class Artificial(2): TP=2, FP=1, FN=0 -> P=2/3, R=1.0, F1=0.8
        assert pc["Artificial"]["precision"] == pytest.approx(2.0 / 3.0)
        assert pc["Artificial"]["recall"] == pytest.approx(1.0)
        assert pc["Artificial"]["f1"] == pytest.approx(0.8)

    def test_confusion_matrix_structure(self):
        from lcnet.metrics import assess
        predictions = [0, 1, 2, 3, 4, 5, 6]
        ground_truth = [0, 1, 2, 3, 4, 5, 6]
        result = assess(predictions, ground_truth)
        cm = result["confusion_matrix"]
        assert len(cm) == 7
        assert all(len(row) == 7 for row in cm)
        # Identity matrix
        for i in range(7):
            for j in range(7):
                assert cm[i][j] == (1 if i == j else 0)

    def test_confusion_matrix_orientation(self):
        """Rows must be true classes, columns must be predicted classes."""
        from lcnet.metrics import assess
        # Predict all as class 0 against varied truth
        predictions = [0, 0, 0]
        ground_truth = [0, 1, 2]
        result = assess(predictions, ground_truth)
        cm = result["confusion_matrix"]
        # Row 0 (truth=0): one correct prediction in col 0
        assert cm[0][0] == 1
        # Row 1 (truth=1): mispredicted as 0 -> col 0
        assert cm[1][0] == 1
        # Row 2 (truth=2): mispredicted as 0 -> col 0
        assert cm[2][0] == 1
        # Column 0 should sum to 3 (all predictions are class 0)
        assert sum(cm[r][0] for r in range(7)) == 3

    def test_hierarchical_level2(self):
        """Artificial(2) and Natural(3) both map to Bare Ground at level 2."""
        from lcnet.metrics import assess
        predictions = [2, 3]
        ground_truth = [3, 2]
        result_l3 = assess(predictions, ground_truth, level=3)
        assert result_l3["overall_accuracy"] == pytest.approx(0.0)

        result_l2 = assess(predictions, ground_truth, level=2)
        assert result_l2["overall_accuracy"] == pytest.approx(1.0)

    def test_hierarchical_level1(self):
        """Mixed bare/vegetation classes mapped to binary."""
        from lcnet.metrics import assess
        # pred=[0(Bare), 4(Veg)], truth=[1(Bare), 5(Veg)] -> at L1 both correct
        predictions = [0, 4]
        ground_truth = [1, 5]
        result_l1 = assess(predictions, ground_truth, level=1)
        assert result_l1["overall_accuracy"] == pytest.approx(1.0)
        cm = result_l1["confusion_matrix"]
        assert len(cm) == 2
        assert len(cm[0]) == 2

    def test_hierarchical_partial_improvement(self):
        """Level 2 improves accuracy but not to 100%."""
        from lcnet.metrics import assess
        # pred=[2,5,0], truth=[3,6,4]
        # L3: all wrong, OA=0
        # L2: pred=[2,4,0], truth=[2,4,3] -> 2 of 3 correct
        # L1: pred=[0,1,0], truth=[0,1,1] -> 2 of 3 correct
        predictions = [2, 5, 0]
        ground_truth = [3, 6, 4]
        r3 = assess(predictions, ground_truth, level=3)
        assert r3["overall_accuracy"] == pytest.approx(0.0)
        r2 = assess(predictions, ground_truth, level=2)
        assert r2["overall_accuracy"] == pytest.approx(2.0 / 3.0)
        r1 = assess(predictions, ground_truth, level=1)
        assert r1["overall_accuracy"] == pytest.approx(2.0 / 3.0)

    def test_zero_support_class(self):
        """Classes that don't appear get 0.0 for all metrics."""
        from lcnet.metrics import assess
        predictions = [0, 0]
        ground_truth = [0, 0]
        result = assess(predictions, ground_truth)
        # Only Snow/Ice appears; all others have zero support
        assert result["per_class"]["Water"]["f1"] == 0.0
        assert result["per_class"]["Water"]["precision"] == 0.0
        assert result["per_class"]["Water"]["recall"] == 0.0


# ─── Sampling ───────────────────────────────────────────────────────────────

class TestSampling:
    def test_correct_count(self):
        from lcnet.sampling import stratified_sample
        features = np.random.RandomState(42).rand(100, 5)
        indices = stratified_sample(features, 10, seed=42)
        assert len(indices) == 10

    def test_all_unique(self):
        from lcnet.sampling import stratified_sample
        features = np.random.RandomState(42).rand(100, 5)
        indices = stratified_sample(features, 10, seed=42)
        assert len(set(indices)) == 10

    def test_valid_range(self):
        from lcnet.sampling import stratified_sample
        features = np.random.RandomState(42).rand(50, 3)
        indices = stratified_sample(features, 8, seed=0)
        assert all(0 <= i < 50 for i in indices)

    def test_deterministic(self):
        from lcnet.sampling import stratified_sample
        features = np.random.RandomState(0).rand(50, 3)
        idx1 = stratified_sample(features, 5, seed=123)
        idx2 = stratified_sample(features, 5, seed=123)
        np.testing.assert_array_equal(idx1, idx2)

    def test_full_sample_returns_all(self):
        from lcnet.sampling import stratified_sample
        features = np.random.RandomState(0).rand(10, 2)
        indices = stratified_sample(features, 10, seed=42)
        assert len(indices) == 10
        assert set(indices.tolist()) == set(range(10))

    def test_oversample_returns_all(self):
        from lcnet.sampling import stratified_sample
        features = np.random.RandomState(0).rand(5, 2)
        indices = stratified_sample(features, 20, seed=42)
        assert len(indices) == 5

    def test_bimodal_coverage(self):
        """CDF-based sampling should cover both clusters in bimodal data."""
        from lcnet.sampling import stratified_sample
        rng = np.random.RandomState(42)
        cluster1 = rng.randn(80, 2) * 0.1
        cluster2 = rng.randn(20, 2) * 0.1 + 5
        features = np.vstack([cluster1, cluster2])
        indices = stratified_sample(features, 10, seed=42)
        selected = features[indices]
        near_c1 = sum(1 for s in selected if np.linalg.norm(s) < 2)
        near_c2 = sum(1 for s in selected if np.linalg.norm(s - 5) < 2)
        assert near_c1 > 0, "Should sample from cluster 1"
        assert near_c2 > 0, "Should sample from cluster 2"

    def test_not_just_first_n(self):
        """Sampling must not simply return the first n indices."""
        from lcnet.sampling import stratified_sample
        rng = np.random.RandomState(7)
        features = rng.rand(50, 4)
        indices = stratified_sample(features, 8, seed=7)
        assert list(indices) != list(range(8)), \
            "Sampling returned first n indices; implement proper farthest-point selection"


# ─── Scoring ────────────────────────────────────────────────────────────────

class TestScoring:
    def test_perfect_cross_entropy(self):
        from lcnet.scoring import cross_entropy_score
        submission = np.array([[1.0, 0.0, 0.0],
                               [0.0, 1.0, 0.0],
                               [0.0, 0.0, 1.0]])
        ground_truth = np.array([0, 1, 2])
        score = cross_entropy_score(submission, ground_truth)
        assert score < 1e-10

    def test_terrible_cross_entropy(self):
        from lcnet.scoring import cross_entropy_score
        submission = np.array([[0.0, 1.0, 0.0],
                               [1.0, 0.0, 0.0],
                               [0.0, 1.0, 0.0]])
        ground_truth = np.array([0, 1, 2])
        score = cross_entropy_score(submission, ground_truth)
        assert np.isfinite(score), "Score must be finite; clip probabilities for numerical stability"
        assert score > 30

    def test_known_cross_entropy(self):
        from lcnet.scoring import cross_entropy_score
        submission = np.array([[0.7, 0.2, 0.1],
                               [0.1, 0.8, 0.1],
                               [0.2, 0.3, 0.5]])
        ground_truth = np.array([0, 1, 2])
        expected = -(math.log(0.7) + math.log(0.8) + math.log(0.5)) / 3
        score = cross_entropy_score(submission, ground_truth)
        assert score == pytest.approx(expected, rel=1e-6)

    def test_validate_good_submission(self):
        from lcnet.scoring import validate_submission
        submission = {0: [0.5, 0.3, 0.2], 1: [0.1, 0.8, 0.1]}
        valid, errors = validate_submission(submission, [0, 1], 3)
        assert valid is True
        assert len(errors) == 0

    def test_validate_missing_id(self):
        from lcnet.scoring import validate_submission
        submission = {0: [0.5, 0.5]}
        valid, errors = validate_submission(submission, [0, 1], 2)
        assert valid is False
        assert any("1" in e for e in errors)

    def test_validate_bad_sum(self):
        from lcnet.scoring import validate_submission
        submission = {0: [0.5, 0.3, 0.3]}
        valid, errors = validate_submission(submission, [0], 3)
        assert valid is False

    def test_validate_negative_probability(self):
        from lcnet.scoring import validate_submission
        submission = {0: [-0.1, 1.1]}
        valid, errors = validate_submission(submission, [0], 2)
        assert valid is False

    def test_validate_tolerance(self):
        """Row sum within 1e-6 of 1.0 should be accepted as valid."""
        from lcnet.scoring import validate_submission
        # Sum = 1.0 + 5e-7, well within 1e-6 tolerance
        submission = {0: [0.3, 0.3, 0.4 + 5e-7]}
        valid, errors = validate_submission(submission, [0], 3)
        assert valid is True


# ─── Storage ────────────────────────────────────────────────────────────────

class TestStorage:
    def test_init_creates_tables(self, tmp_path):
        from lcnet.storage import init_db
        db = str(tmp_path / "test.db")
        init_db(db)
        conn = sqlite3.connect(db)
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()]
        conn.close()
        assert "assessments" in tables
        assert "scores" in tables

    def test_store_assessment_correct_values(self, tmp_path):
        """Verify that overall_accuracy and cohens_kappa are stored in their
        respective columns and not swapped."""
        from lcnet.storage import init_db, store_assessment
        db = str(tmp_path / "test.db")
        init_db(db)
        result = {
            "overall_accuracy": 0.85,
            "cohens_kappa": 0.42,
            "per_class": {"A": {"f1": 0.9}},
            "confusion_matrix": [[5, 1], [1, 5]]
        }
        store_assessment(result, 3, db)
        conn = sqlite3.connect(db)
        row = conn.execute(
            "SELECT overall_accuracy, cohens_kappa FROM assessments"
        ).fetchone()
        conn.close()
        assert row[0] == pytest.approx(0.85), \
            "overall_accuracy column has wrong value (may be swapped with kappa)"
        assert row[1] == pytest.approx(0.42), \
            "cohens_kappa column has wrong value (may be swapped with accuracy)"

    def test_store_score(self, tmp_path):
        from lcnet.storage import init_db, store_score
        db = str(tmp_path / "test.db")
        init_db(db)
        result = {"valid": True, "score": 0.345, "errors": []}
        store_score(result, db)
        conn = sqlite3.connect(db)
        row = conn.execute("SELECT valid, score FROM scores").fetchone()
        conn.close()
        assert row[0] == 1
        assert row[1] == pytest.approx(0.345)

    def test_summary_groups_by_level(self, tmp_path):
        """Multiple assessments at different levels must be grouped correctly."""
        from lcnet.storage import init_db, store_assessment, get_summary
        db = str(tmp_path / "test.db")
        init_db(db)

        for _ in range(3):
            store_assessment({
                "overall_accuracy": 0.9, "cohens_kappa": 0.8,
                "per_class": {}, "confusion_matrix": []
            }, 3, db)
        for _ in range(2):
            store_assessment({
                "overall_accuracy": 0.95, "cohens_kappa": 0.85,
                "per_class": {}, "confusion_matrix": []
            }, 2, db)

        summary = get_summary(db)
        assert summary["assessment_runs"] == 5
        assert "3" in summary["by_level"]
        assert "2" in summary["by_level"]
        assert summary["by_level"]["3"]["count"] == 3
        assert summary["by_level"]["2"]["count"] == 2
        assert summary["by_level"]["3"]["mean_accuracy"] == pytest.approx(0.9)
        assert summary["by_level"]["2"]["mean_accuracy"] == pytest.approx(0.95)


# ─── CLI ────────────────────────────────────────────────────────────────────

class TestCLI:
    @pytest.fixture
    def env(self):
        e = os.environ.copy()
        e["PYTHONPATH"] = "/app"
        return e

    def test_consensus_cli(self, tmp_path, env):
        input_data = {
            "annotations": [[0, 1, 2], [0, 2, 2], [1, 1, 3]],
            "weights": [0.9, 0.8, 0.7],
            "num_classes": 7
        }
        input_file = str(tmp_path / "in.json")
        output_file = str(tmp_path / "out.json")
        with open(input_file, 'w') as f:
            json.dump(input_data, f)

        result = subprocess.run(
            ["python3", "-m", "lcnet", "consensus", input_file, output_file],
            capture_output=True, text=True, env=env
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"

        with open(output_file) as f:
            output = json.load(f)
        assert output["labels"] == [0, 1, 2]
        assert len(output["scores"]) == 3
        assert all(isinstance(s, float) for s in output["scores"])

    def test_assess_cli(self, tmp_path, env):
        pred_file = str(tmp_path / "pred.csv")
        truth_file = str(tmp_path / "truth.csv")

        with open(pred_file, 'w', newline='') as f:
            w = csv.writer(f)
            w.writerow(["id", "label"])
            for i, v in enumerate([0, 0, 1, 2, 2, 2]):
                w.writerow([str(i), v])

        with open(truth_file, 'w', newline='') as f:
            w = csv.writer(f)
            w.writerow(["id", "label"])
            for i, v in enumerate([0, 1, 1, 2, 2, 0]):
                w.writerow([str(i), v])

        result = subprocess.run(
            ["python3", "-m", "lcnet", "assess", pred_file, truth_file, "--level", "3"],
            capture_output=True, text=True, env=env
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        output = json.loads(result.stdout)
        assert output["overall_accuracy"] == pytest.approx(2.0 / 3.0)
        assert output["cohens_kappa"] == pytest.approx(0.5)

    def test_assess_cli_hierarchical(self, tmp_path, env):
        """CLI must correctly pass --level to the assessment function."""
        pred_file = str(tmp_path / "pred2.csv")
        truth_file = str(tmp_path / "truth2.csv")

        with open(pred_file, 'w', newline='') as f:
            w = csv.writer(f)
            w.writerow(["id", "label"])
            w.writerow(["0", "2"])  # Artificial
            w.writerow(["1", "3"])  # Natural

        with open(truth_file, 'w', newline='') as f:
            w = csv.writer(f)
            w.writerow(["id", "label"])
            w.writerow(["0", "3"])  # Natural
            w.writerow(["1", "2"])  # Artificial

        result = subprocess.run(
            ["python3", "-m", "lcnet", "assess", pred_file, truth_file, "--level", "2"],
            capture_output=True, text=True, env=env
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        output = json.loads(result.stdout)
        # At L2: both 2 and 3 map to Bare Ground, so all predictions are correct
        assert output["overall_accuracy"] == pytest.approx(1.0)

    def test_sample_cli(self, tmp_path, env):
        feat_file = str(tmp_path / "features.csv")
        with open(feat_file, 'w', newline='') as f:
            w = csv.writer(f)
            w.writerow(["f1", "f2"])
            rng = np.random.RandomState(99)
            for row in rng.rand(30, 2):
                w.writerow([str(v) for v in row])

        result = subprocess.run(
            ["python3", "-m", "lcnet", "sample", feat_file, "5", "--seed", "42"],
            capture_output=True, text=True, env=env
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        indices = json.loads(result.stdout)
        assert len(indices) == 5
        assert len(set(indices)) == 5
        assert all(0 <= i < 30 for i in indices)

    def test_score_cli(self, tmp_path, env):
        sub_file = str(tmp_path / "submission.csv")
        truth_file = str(tmp_path / "truth.csv")

        with open(sub_file, 'w', newline='') as f:
            w = csv.writer(f)
            w.writerow(["id", "class0", "class1", "class2"])
            w.writerow(["a", "0.7", "0.2", "0.1"])
            w.writerow(["b", "0.1", "0.8", "0.1"])

        with open(truth_file, 'w', newline='') as f:
            w = csv.writer(f)
            w.writerow(["id", "label"])
            w.writerow(["a", "0"])
            w.writerow(["b", "1"])

        result = subprocess.run(
            ["python3", "-m", "lcnet", "score", sub_file, truth_file],
            capture_output=True, text=True, env=env
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        output = json.loads(result.stdout)
        assert output["valid"] is True
        expected_ce = -(math.log(0.7) + math.log(0.8)) / 2
        assert output["score"] == pytest.approx(expected_ce, rel=1e-6)

    def test_assess_cli_with_db(self, tmp_path, env):
        """Verify --db flag stores assessment results in SQLite."""
        from lcnet.storage import init_db
        db = str(tmp_path / "assess_db_test.db")
        init_db(db)

        pred_file = str(tmp_path / "pred.csv")
        truth_file = str(tmp_path / "truth.csv")

        with open(pred_file, 'w', newline='') as f:
            w = csv.writer(f)
            w.writerow(["id", "label"])
            w.writerow(["0", "0"])
            w.writerow(["1", "1"])

        with open(truth_file, 'w', newline='') as f:
            w = csv.writer(f)
            w.writerow(["id", "label"])
            w.writerow(["0", "0"])
            w.writerow(["1", "1"])

        result = subprocess.run(
            ["python3", "-m", "lcnet", "assess", pred_file, truth_file,
             "--level", "3", "--db", db],
            capture_output=True, text=True, env=env
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"

        conn = sqlite3.connect(db)
        row = conn.execute(
            "SELECT overall_accuracy, cohens_kappa, level FROM assessments"
        ).fetchone()
        conn.close()
        assert row is not None, "Assessment result should be stored in the database"
        assert row[0] == pytest.approx(1.0), "Stored overall_accuracy should match"
        assert row[2] == 3, "Stored level should match --level argument"

    def test_score_cli_with_db(self, tmp_path, env):
        """Verify --db flag stores scoring results in SQLite."""
        from lcnet.storage import init_db
        db = str(tmp_path / "score_db_test.db")
        init_db(db)

        sub_file = str(tmp_path / "submission.csv")
        truth_file = str(tmp_path / "truth.csv")

        with open(sub_file, 'w', newline='') as f:
            w = csv.writer(f)
            w.writerow(["id", "class0", "class1"])
            w.writerow(["a", "0.7", "0.3"])

        with open(truth_file, 'w', newline='') as f:
            w = csv.writer(f)
            w.writerow(["id", "label"])
            w.writerow(["a", "0"])

        result = subprocess.run(
            ["python3", "-m", "lcnet", "score", sub_file, truth_file, "--db", db],
            capture_output=True, text=True, env=env
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"

        conn = sqlite3.connect(db)
        count = conn.execute("SELECT COUNT(*) FROM scores").fetchone()[0]
        conn.close()
        assert count == 1, "Score result should be stored in the database when --db is provided"

    def test_report_cli(self, tmp_path, env):
        """Verify report subcommand outputs correct summary JSON."""
        from lcnet.storage import init_db, store_assessment
        db = str(tmp_path / "report_test.db")
        init_db(db)
        store_assessment({
            "overall_accuracy": 0.8, "cohens_kappa": 0.6,
            "per_class": {}, "confusion_matrix": []
        }, 3, db)

        result = subprocess.run(
            ["python3", "-m", "lcnet", "report", "--db", db],
            capture_output=True, text=True, env=env
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        output = json.loads(result.stdout)
        assert output["assessment_runs"] == 1
        assert "3" in output["by_level"]
        assert output["by_level"]["3"]["mean_accuracy"] == pytest.approx(0.8)


# ─── Makefile ───────────────────────────────────────────────────────────────

class TestMakefile:
    @pytest.fixture
    def env(self):
        e = os.environ.copy()
        e["PYTHONPATH"] = "/app"
        return e

    def test_makefile_exists(self):
        assert os.path.isfile("/app/Makefile")

    def test_make_init_db(self, tmp_path, env):
        db = str(tmp_path / "test_make.db")
        result = subprocess.run(
            ["make", "-C", "/app", "init-db", f"RESULTS_DB={db}"],
            capture_output=True, text=True, env=env
        )
        assert result.returncode == 0, f"make init-db failed: {result.stderr}"
        assert os.path.isfile(db)

    def test_make_pipeline(self, tmp_path, env):
        """Full pipeline target must chain init-db, assess, score, report."""
        db = str(tmp_path / "pipeline.db")
        result = subprocess.run(
            ["make", "-C", "/app", "pipeline", f"RESULTS_DB={db}"],
            capture_output=True, text=True, env=env
        )
        assert result.returncode == 0, \
            f"make pipeline failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        assert os.path.isfile(db)
        # Verify data was actually stored
        conn = sqlite3.connect(db)
        assess_count = conn.execute("SELECT COUNT(*) FROM assessments").fetchone()[0]
        score_count = conn.execute("SELECT COUNT(*) FROM scores").fetchone()[0]
        conn.close()
        assert assess_count >= 1, "Pipeline should store at least one assessment"
        assert score_count >= 1, "Pipeline should store at least one score"

    def test_make_clean(self, tmp_path, env):
        db = str(tmp_path / "clean_test.db")
        # Create DB first
        subprocess.run(
            ["make", "-C", "/app", "init-db", f"RESULTS_DB={db}"],
            capture_output=True, text=True, env=env
        )
        assert os.path.isfile(db), "DB should exist after init-db"
        # Clean it
        result = subprocess.run(
            ["make", "-C", "/app", "clean", f"RESULTS_DB={db}"],
            capture_output=True, text=True, env=env
        )
        assert result.returncode == 0, f"make clean failed: {result.stderr}"
        assert not os.path.isfile(db), "DB should be removed by make clean"
