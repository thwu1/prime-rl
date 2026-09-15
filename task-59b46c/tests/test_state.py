"""Verification tests for cross-subject EEG decoding pipeline."""

import sys
import json
import numpy as np
import pytest

sys.path.insert(0, "/app")

from eeg_data import generate_dataset
import pipeline


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def config():
    with open("/app/config.json") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def standard_results(config):
    return pipeline.decode(config["dataset"])


@pytest.fixture(scope="module")
def standard_dataset(config):
    return generate_dataset(**config["dataset"])


# ---------------------------------------------------------------------------
# 1. Result structure validation
# ---------------------------------------------------------------------------

class TestResultStructure:
    def test_has_accuracies_key(self, standard_results):
        assert "accuracies" in standard_results

    def test_has_mean_accuracy_key(self, standard_results):
        assert "mean_accuracy" in standard_results

    def test_has_predictions_key(self, standard_results):
        assert "predictions" in standard_results

    def test_accuracies_length_matches_subjects(self, standard_results, config):
        assert len(standard_results["accuracies"]) == config["dataset"]["n_subjects"]

    def test_predictions_length_matches_subjects(self, standard_results, config):
        assert len(standard_results["predictions"]) == config["dataset"]["n_subjects"]

    def test_mean_accuracy_equals_mean_of_accuracies(self, standard_results):
        expected = float(np.mean(standard_results["accuracies"]))
        assert np.isclose(standard_results["mean_accuracy"], expected, atol=1e-10), (
            f"mean_accuracy={standard_results['mean_accuracy']:.6f} != "
            f"mean(accuracies)={expected:.6f}"
        )

    def test_all_accuracies_in_valid_range(self, standard_results):
        for i, acc in enumerate(standard_results["accuracies"]):
            assert 0.0 <= acc <= 1.0, f"Subject {i} accuracy {acc} out of [0, 1]"

    def test_predictions_are_binary(self, standard_results):
        for i, preds in enumerate(standard_results["predictions"]):
            unique = set(int(v) for v in np.unique(preds))
            assert unique.issubset({0, 1}), (
                f"Subject {i} predictions contain non-binary values: {unique}"
            )

    def test_predictions_sizes_match_labels(self, standard_results, standard_dataset):
        for i, subj in enumerate(standard_dataset):
            preds = standard_results["predictions"][i]
            assert len(preds) == len(subj["labels"]), (
                f"Subject {i}: {len(preds)} predictions != {len(subj['labels'])} labels"
            )


# ---------------------------------------------------------------------------
# 2. Accuracy thresholds on standard dataset
# ---------------------------------------------------------------------------

class TestAccuracyThresholds:
    def test_mean_accuracy_meets_threshold(self, standard_results, config):
        thresh = config["requirements"]["min_mean_accuracy"]
        assert standard_results["mean_accuracy"] >= thresh, (
            f"Mean accuracy {standard_results['mean_accuracy']:.4f} < threshold {thresh}"
        )

    def test_per_subject_accuracy_meets_threshold(self, standard_results, config):
        thresh = config["requirements"]["min_per_subject_accuracy"]
        for i, acc in enumerate(standard_results["accuracies"]):
            assert acc >= thresh, (
                f"Subject {i} accuracy {acc:.4f} < threshold {thresh}"
            )


# ---------------------------------------------------------------------------
# 3. Generalization to unseen dataset configurations
# ---------------------------------------------------------------------------

class TestGeneralization:
    """Pipeline must work on dataset configs not seen during development."""

    def test_different_seed_fewer_subjects(self):
        """Different random seed and fewer subjects."""
        alt_params = {
            "n_subjects": 7,
            "n_channels": 22,
            "n_trials_per_class": 35,
            "n_samples": 1000,
            "fs": 250,
            "base_seed": 99,
        }
        results = pipeline.decode(alt_params)
        assert len(results["accuracies"]) == 7
        assert len(results["predictions"]) == 7
        assert results["mean_accuracy"] > 0.58, (
            f"Alt config (seed=99, 7 subj): mean accuracy "
            f"{results['mean_accuracy']:.4f} <= 0.58"
        )

    def test_fewer_channels_and_shorter_signals(self):
        """Reduced channel count and signal length."""
        alt_params = {
            "n_subjects": 5,
            "n_channels": 16,
            "n_trials_per_class": 30,
            "n_samples": 750,
            "fs": 250,
            "base_seed": 77,
        }
        results = pipeline.decode(alt_params)
        assert len(results["accuracies"]) == 5
        assert len(results["predictions"]) == 5
        assert results["mean_accuracy"] > 0.55, (
            f"Alt config (16ch, 5 subj): mean accuracy "
            f"{results['mean_accuracy']:.4f} <= 0.55"
        )

    def test_minimal_config_predictions_valid(self):
        """Small config: verify predictions match dataset dimensions."""
        alt_params = {
            "n_subjects": 4,
            "n_channels": 12,
            "n_trials_per_class": 25,
            "n_samples": 625,
            "fs": 250,
            "base_seed": 123,
        }
        results = pipeline.decode(alt_params)
        dataset = generate_dataset(**alt_params)
        assert len(results["accuracies"]) == 4
        for i, subj in enumerate(dataset):
            preds = results["predictions"][i]
            assert len(preds) == len(subj["labels"]), (
                f"Subject {i}: {len(preds)} preds != {len(subj['labels'])} labels"
            )
            assert set(int(v) for v in np.unique(preds)).issubset({0, 1})
        # Must beat chance significantly
        assert results["mean_accuracy"] > 0.53, (
            f"Alt config (12ch, 4 subj): mean accuracy "
            f"{results['mean_accuracy']:.4f} <= 0.53"
        )


# ---------------------------------------------------------------------------
# 4. Consistency and reproducibility
# ---------------------------------------------------------------------------

class TestConsistency:
    def test_deterministic_results(self, config):
        """Two calls with the same params must produce identical results."""
        r1 = pipeline.decode(config["dataset"])
        r2 = pipeline.decode(config["dataset"])
        assert np.allclose(r1["accuracies"], r2["accuracies"]), (
            "Pipeline is not deterministic across runs"
        )
        for p1, p2 in zip(r1["predictions"], r2["predictions"]):
            assert np.array_equal(p1, p2), "Predictions differ across runs"
