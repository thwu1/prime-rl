"""
Temperature Scaling calibration method.

"""
import numpy as np
from scipy.optimize import minimize_scalar


class TemperatureScaling:
    """Post-hoc temperature scaling for multi-class calibration."""

    def __init__(self):
        self.temperature = 1.0

    @staticmethod
    def _softmax(logits):
        shifted = logits - np.max(logits, axis=1, keepdims=True)
        exp_vals = np.exp(shifted)
        return exp_vals / np.sum(exp_vals, axis=1, keepdims=True)

    def fit(self, logits, labels, n_classes):
        """Find optimal temperature by minimizing NLL on training data."""

        def nll(T):
            scaled_probs = self._softmax(logits / T)
            scaled_probs = np.clip(scaled_probs, 1e-15, 1 - 1e-15)
            log_probs = np.log(scaled_probs[np.arange(len(labels)), labels])
            return float(-np.mean(log_probs))

        result = minimize_scalar(
            lambda T: -nll(T),
            bounds=(0.1, 10.0),
            method='bounded',
        )
        self.temperature = float(result.x)
        return self

    def transform(self, logits, n_classes):
        """Apply learned temperature to produce calibrated probabilities."""
        return self._softmax(logits / self.temperature)
