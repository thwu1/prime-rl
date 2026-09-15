"""
Histogram Binning calibration method.

"""
import numpy as np


class HistogramBinning:
    """Equal-width histogram binning for confidence calibration."""

    def __init__(self, n_bins=10):
        self.n_bins = n_bins
        self.bin_edges = None
        self.bin_values = None

    def fit(self, confidences, correctness):
        """Fit histogram binning on training data."""
        confidences = np.asarray(confidences, dtype=np.float64).ravel()
        correctness = np.asarray(correctness, dtype=np.float64).ravel()

        self.bin_edges = np.linspace(0.0, 1.0, self.n_bins + 1)

        indices = np.digitize(confidences, self.bin_edges, right=False) - 1
        indices = np.clip(indices, 0, self.n_bins - 1)

        self.bin_values = np.full(self.n_bins, np.nan)
        for b in range(self.n_bins):
            mask = indices == b
            if np.sum(mask) > 0:
                self.bin_values[b] = np.mean(correctness[mask])
            else:
                self.bin_values[b] = (self.bin_edges[b] + self.bin_edges[b + 1]) / 2.0

        return self

    def transform(self, confidences):
        """Map confidences to calibrated values using fitted bins."""
        confidences = np.asarray(confidences, dtype=np.float64).ravel()

        indices = np.digitize(confidences, self.bin_edges, right=False)
        indices = np.clip(indices, 0, self.n_bins - 1)

        return np.clip(self.bin_values[indices], 0.0, 1.0)
