"""Piecewise-Linear Encoder for tabular numerical features."""

import numpy as np

from .bins import compute_bins  # noqa: F401 -- re-exported for public API


class PiecewiseLinearEncoder:
    """Encode numerical features into piecewise-linear component vectors."""

    def __init__(self, bins):
        self._bins = [np.asarray(b, dtype=np.float64) for b in bins]
        self._k = [len(b) - 1 for b in self._bins]

    @property
    def n_features(self):
        return len(self._bins)

    @property
    def max_n_bins(self):
        return max(self._k)

    @property
    def total_n_bins(self):
        return sum(self._k)

    def encode_structured(self, X):
        """Return structured encoding of shape (batch, n_features, max_n_bins)."""
        if X.shape[1] != self.n_features:
            raise ValueError(
                f"Expected {self.n_features} features, got {X.shape[1]}")

        batch = X.shape[0]
        mb = self.max_n_bins
        out = np.zeros((batch, self.n_features, mb), dtype=np.float64)

        for f in range(self.n_features):
            edges = self._bins[f]
            k = self._k[f]

            for j in range(k):
                width = edges[j + 1] - edges[j]
                raw = (X[:, f] - edges[j]) / width

                if k == 1:
                    clamped = np.maximum(raw, 0.0)
                elif j == 0:
                    clamped = np.clip(raw, 0.0, 1.0)
                elif j == k - 1:
                    clamped = np.maximum(raw, 0.0)
                else:
                    clamped = np.clip(raw, 0.0, 1.0)

                out[:, f, j] = clamped

        return out

    def encode_flat(self, X):
        """Return flat encoding of shape (batch, total_n_bins)."""
        structured = self.encode_structured(X)
        parts = []
        for f in range(self.n_features):
            k = self._k[f]
            parts.append(structured[:, f, :k])
        return np.concatenate(parts, axis=1)
