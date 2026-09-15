"""Active Learning Stopping Criteria

Functions that determine when to stop the active learning loop based on
prediction stability, uncertainty, or agreement measures.

"""

import numpy as np
from scipy.stats import entropy as scipy_entropy


def classification_change_stop(predictions_current, predictions_previous, threshold=0.0):
    """Stop if the fraction of changed predictions is at or below threshold.

    Parameters
    ----------
    predictions_current : np.ndarray, shape (num_samples,)
        Current predictions (integer class labels).
    predictions_previous : np.ndarray, shape (num_samples,)
        Previous predictions (integer class labels).
    threshold : float
        Maximum fraction of samples allowed to change. 0.0 means stop only
        when zero samples changed.

    Returns
    -------
    stop : bool
        True if criterion indicates stopping.
    """
    unchanged = np.equal(predictions_current, predictions_previous)
    if unchanged.sum() >= predictions_current.shape[0] * (1 - threshold):
        return True
    return False


def kappa_average_stop(predictions_history, num_classes, window_size=3,
                       kappa_threshold=0.99):
    """Evaluate stop/continue for a sequence of prediction arrays using
    Cohen's kappa agreement.

    Computes Cohen's kappa between each consecutive pair of prediction arrays.
    Returns True (stop) when the mean kappa over the most recent `window_size`
    kappa values meets or exceeds `kappa_threshold`.

    Special case: when two prediction arrays are element-wise identical,
    kappa is defined as 1.0 (the standard formula produces a division by zero
    for perfect agreement).

    The first entry always yields False (no predecessor to compare against).

    Parameters
    ----------
    predictions_history : list of np.ndarray
        Sequence of prediction arrays, each shape (num_samples,).
    num_classes : int
        Number of distinct class labels.
    window_size : int
        Number of recent kappa values to average.
    kappa_threshold : float
        Mean kappa must reach this value to trigger stopping.

    Returns
    -------
    decisions : list of bool
        One decision per entry in predictions_history.
    """
    raise NotImplementedError("kappa_average_stop not implemented")


def overall_uncertainty_stop(proba, indices, num_classes, threshold=0.05):
    """Stop if mean normalized prediction entropy falls below threshold.

    Normalized entropy = entropy(p) / log(num_classes), using natural
    logarithm. Values range from 0 (fully certain) to 1 (maximum uncertainty).

    Parameters
    ----------
    proba : np.ndarray, shape (num_total_samples, num_classes)
        Predicted class probabilities for all samples.
    indices : np.ndarray
        Indices selecting the subset of samples to evaluate.
    num_classes : int
        Number of classes.
    threshold : float
        Stop when mean normalized entropy is below this value.

    Returns
    -------
    stop : bool
        True if criterion indicates stopping.
    """
    raise NotImplementedError("overall_uncertainty_stop not implemented")
