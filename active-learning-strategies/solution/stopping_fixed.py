"""Corrected Active Learning Stopping Criteria.

"""

import numpy as np
from scipy.stats import entropy as scipy_entropy
from sklearn.metrics import cohen_kappa_score


def classification_change_stop(predictions_current, predictions_previous,
                               threshold=0.0):
    """Stop if fraction of changed predictions is at or below threshold."""
    unchanged = np.equal(predictions_current, predictions_previous)
    if unchanged.sum() >= predictions_current.shape[0] * (1 - threshold):
        return True
    return False


def kappa_average_stop(predictions_history, num_classes, window_size=3,
                       kappa_threshold=0.99):
    """Evaluate stop/continue using Cohen's kappa agreement."""
    decisions = []
    kappa_history = []
    last_predictions = None
    labels = np.arange(num_classes)

    for preds in predictions_history:
        if last_predictions is None:
            last_predictions = preds
            decisions.append(False)
            continue

        if np.array_equal(preds, last_predictions):
            kappa = 1.0
        else:
            kappa = cohen_kappa_score(preds, last_predictions, labels=labels)

        kappa_history.append(kappa)
        last_predictions = preds

        if len(kappa_history) < window_size:
            decisions.append(False)
        else:
            window = kappa_history[-window_size:]
            if np.mean(window) >= kappa_threshold:
                decisions.append(True)
            else:
                decisions.append(False)

    return decisions


def overall_uncertainty_stop(proba, indices, num_classes, threshold=0.05):
    """Stop if mean normalized prediction entropy falls below threshold."""
    prediction_entropy = np.apply_along_axis(scipy_entropy, 1, proba[indices])
    normalized = prediction_entropy / np.log(num_classes)
    return bool(np.mean(normalized) < threshold)
