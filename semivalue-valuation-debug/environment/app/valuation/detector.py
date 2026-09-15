"""Noisy label detector using data valuation scores.

Supports both individual evaluator detection (bottom-k by value)
and rank-based ensemble detection (Borda count aggregation).
"""

import numpy as np


class NoisyLabelDetector:
    """Detects noisy (mislabeled) training points via data value ranking.

    Points with the lowest data values are flagged as likely corrupted,
    since mislabeled data tends to have negative or low marginal
    contribution to model performance.
    """

    def detect(self, data_values, noise_rate):
        """Flag the lowest-valued training points as noisy.

        Parameters
        ----------
        data_values : np.ndarray
            Per-point data value scores (higher = more valuable).
        noise_rate : float
            Expected proportion of noisy labels in the training set.

        Returns
        -------
        np.ndarray
            Sorted array of integer indices flagged as mislabeled.
        """
        n = len(data_values)
        k = int(n * noise_rate)
        return np.sort(np.argsort(data_values)[:k])

    def ensemble_detect(self, evaluator_results, noise_rate, n_points):
        """Combine evaluator rankings using Borda count aggregation.

        Ranks each evaluator's values (lower value receives lower rank).
        Sums ranks across evaluators and selects the points with the
        lowest total rank as detected noisy points.

        Parameters
        ----------
        evaluator_results : dict
            Mapping of evaluator name to data value arrays.
        noise_rate : float
            Expected noise fraction.
        n_points : int
            Total number of training points.

        Returns
        -------
        np.ndarray
            Sorted indices of detected noisy points.
        """
        rank_sum = np.zeros(n_points)
        for name, values in evaluator_results.items():
            values = np.array(values)
            ranks = np.argsort(np.argsort(values))
            rank_sum += ranks

        k = int(n_points * noise_rate)
        return np.sort(np.argsort(rank_sum)[-k:])
