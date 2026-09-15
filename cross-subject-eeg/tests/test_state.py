
import pytest
import json
import numpy as np
import os

GROUND_TRUTH_DIR = '/tmp/eeg_ground_truth'
RESULTS_PATH = '/app/results.json'
METADATA_PATH = '/app/data/metadata.json'


@pytest.fixture
def metadata():
    with open(METADATA_PATH) as f:
        return json.load(f)


@pytest.fixture
def results():
    with open(RESULTS_PATH) as f:
        return json.load(f)


def test_results_file_exists():
    assert os.path.exists(RESULTS_PATH), "results.json not found at /app/results.json"


def test_results_has_required_keys(results):
    assert 'overall_accuracy' in results, "Missing 'overall_accuracy' key"
    assert 'subject_accuracies' in results, "Missing 'subject_accuracies' key"
    assert 'predictions' in results, "Missing 'predictions' key"


def test_all_test_subjects_present(results, metadata):
    for s in metadata['test_subjects']:
        key = str(s)
        assert key in results['subject_accuracies'], \
            "Missing subject {} in subject_accuracies".format(s)
        assert key in results['predictions'], \
            "Missing subject {} in predictions".format(s)


def test_predictions_valid_classes(results, metadata):
    n_classes = metadata['n_classes']
    for s in metadata['test_subjects']:
        preds = results['predictions'][str(s)]
        for p in preds:
            assert isinstance(p, int), \
                "Prediction for subject {} is not int: {}".format(s, type(p))
            assert 0 <= p < n_classes, \
                "Invalid class {} for subject {} (must be 0-{})".format(p, s, n_classes - 1)


def test_prediction_counts(results, metadata):
    n_expected = metadata['n_trials_per_class'] * metadata['n_classes']
    for s in metadata['test_subjects']:
        preds = results['predictions'][str(s)]
        assert len(preds) == n_expected, \
            "Subject {} has {} predictions, expected {}".format(s, len(preds), n_expected)


def test_ground_truth_regenerated():
    """Verify ground truth was successfully regenerated at test time."""
    assert os.path.isdir(GROUND_TRUTH_DIR), \
        "Ground truth directory not found -- regeneration failed"
    for s in range(6, 10):
        gt_path = os.path.join(GROUND_TRUTH_DIR, 'subject_{:02d}_labels.npy'.format(s))
        assert os.path.exists(gt_path), \
            "Ground truth for subject {} not regenerated".format(s)


def test_overall_accuracy(results, metadata):
    all_correct = 0
    all_total = 0
    for s in metadata['test_subjects']:
        gt_path = os.path.join(GROUND_TRUTH_DIR, 'subject_{:02d}_labels.npy'.format(s))
        labels = np.load(gt_path)
        preds = np.array(results['predictions'][str(s)])
        assert len(preds) == len(labels), \
            "Subject {} prediction count mismatch: {} vs {}".format(s, len(preds), len(labels))
        all_correct += int(np.sum(preds == labels))
        all_total += len(labels)

    accuracy = all_correct / all_total
    assert accuracy >= 0.50, \
        "Overall accuracy {:.4f} < 0.50 required minimum".format(accuracy)


def test_per_subject_accuracy(results, metadata):
    for s in metadata['test_subjects']:
        gt_path = os.path.join(GROUND_TRUTH_DIR, 'subject_{:02d}_labels.npy'.format(s))
        labels = np.load(gt_path)
        preds = np.array(results['predictions'][str(s)])
        acc = float(np.mean(preds == labels))
        assert acc >= 0.30, \
            "Subject {} accuracy {:.4f} < 0.30 required minimum".format(s, acc)
