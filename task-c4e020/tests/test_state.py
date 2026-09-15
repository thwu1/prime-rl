
import json
import os

import numpy as np
import pytest


GROUND_TRUTH_DIR = "/tmp/ground_truth"
DATA_DIR = "/app/data"
TEST_SUBJECTS = ["subject_08", "subject_09", "subject_10"]


def balanced_accuracy(y_true, y_pred):
    """Compute balanced accuracy (mean per-class recall)."""
    y_true = np.asarray(y_true)
    y_pred = np.asarray(y_pred)
    classes = np.unique(y_true)
    recalls = []
    for c in classes:
        mask = y_true == c
        if np.sum(mask) > 0:
            recalls.append(float(np.mean(y_pred[mask] == c)))
    return float(np.mean(recalls))


def load_ground_truth(subject_id):
    path = os.path.join(GROUND_TRUTH_DIR, "{}_labels.npy".format(subject_id))
    assert os.path.isfile(path), (
        "Ground truth not found at {}. "
        "Ensure generate_ground_truth.py ran successfully.".format(path)
    )
    return np.load(path)


def load_predictions():
    with open("/app/predictions.json") as f:
        return json.load(f)


class TestPredictionsExist:
    def test_predictions_file_exists(self):
        assert os.path.isfile("/app/predictions.json"), (
            "/app/predictions.json not found"
        )

    def test_pipeline_config_exists(self):
        assert os.path.isfile("/app/pipeline_config.json"), (
            "/app/pipeline_config.json not found"
        )


class TestPredictionsFormat:
    def test_all_test_subjects_present(self):
        preds = load_predictions()
        for subj in TEST_SUBJECTS:
            assert subj in preds, "Missing predictions for {}".format(subj)

    def test_predictions_are_lists_of_binary_ints(self):
        preds = load_predictions()
        for subj in TEST_SUBJECTS:
            assert isinstance(preds[subj], list), (
                "Predictions for {} must be a list".format(subj)
            )
            for val in preds[subj]:
                assert val in (0, 1), (
                    "Predictions for {} must contain only 0 or 1, got {}".format(subj, val)
                )

    def test_predictions_length_matches_data(self):
        preds = load_predictions()
        for subj in TEST_SUBJECTS:
            gt = load_ground_truth(subj)
            assert len(preds[subj]) == len(gt), (
                "Prediction length {} != expected length {} for {}".format(
                    len(preds[subj]), len(gt), subj)
            )


class TestAccuracy:
    def test_per_subject_balanced_accuracy(self):
        preds = load_predictions()
        for subj in TEST_SUBJECTS:
            gt = load_ground_truth(subj)
            pred_arr = np.array(preds[subj])
            ba = balanced_accuracy(gt, pred_arr)
            assert ba >= 0.60, (
                "{} balanced accuracy {:.4f} < 0.60 minimum threshold".format(subj, ba)
            )

    def test_mean_balanced_accuracy(self):
        preds = load_predictions()
        accuracies = []
        for subj in TEST_SUBJECTS:
            gt = load_ground_truth(subj)
            pred_arr = np.array(preds[subj])
            ba = balanced_accuracy(gt, pred_arr)
            accuracies.append(ba)
        mean_ba = float(np.mean(accuracies))
        assert mean_ba >= 0.70, (
            "Mean balanced accuracy {:.4f} < 0.70 required threshold".format(mean_ba)
        )


class TestPipelineConfig:
    def test_required_fields(self):
        with open("/app/pipeline_config.json") as f:
            config = json.load(f)
        required = ["preprocessing", "feature_extraction", "domain_adaptation", "classifier"]
        for field in required:
            assert field in config, "pipeline_config.json missing field: {}".format(field)
            assert isinstance(config[field], str), (
                "Field '{}' must be a string, got {}".format(field, type(config[field]).__name__)
            )
            assert len(config[field].strip()) > 0, (
                "Field '{}' must be a non-empty string".format(field)
            )
