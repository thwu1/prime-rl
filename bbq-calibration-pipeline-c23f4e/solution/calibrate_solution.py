#!/usr/bin/env python3
"""
Reference implementation: BBQ calibration pipeline.

Implements Histogram Binning, BBQ (Bayesian Binning into Quantiles),
and calibration metrics (ECE, MCE, ACE).

"""
import numpy as np
import json
import sys


class HistogramBinning:
    """
    Histogram Binning calibration with equal-width bins on [0, 1].
    Empty bins are filled with their center value.
    """

    def __init__(self, bins=10):
        self.bins = bins
        self._bin_map = None
        self._bin_bounds = None

    def fit(self, X, y):
        X = np.asarray(X, dtype=np.float64).ravel()
        y = np.asarray(y, dtype=np.float64).ravel()

        eps = np.finfo(np.float64).eps
        X = np.clip(X, eps, 1.0 - eps)

        self._bin_bounds = np.linspace(0.0, 1.0, self.bins + 1)

        # Assign each sample to a bin using digitize (right=True: bins[i-1] < x <= bins[i])
        indices = np.digitize(X, self._bin_bounds, right=True) - 1
        indices = np.clip(indices, 0, self.bins - 1)

        # Compute mean accuracy per bin
        bin_map = np.full(self.bins, np.nan)
        for b in range(self.bins):
            mask = indices == b
            count = np.sum(mask)
            if count > 0:
                bin_map[b] = np.mean(y[mask])

        # Fill empty bins with bin center
        for b in range(self.bins):
            if np.isnan(bin_map[b]):
                bin_map[b] = 0.5 * (self._bin_bounds[b] + self._bin_bounds[b + 1])

        self._bin_map = bin_map
        return self

    def transform(self, X):
        X = np.asarray(X, dtype=np.float64).ravel()
        eps = np.finfo(np.float64).eps
        X = np.clip(X, eps, 1.0 - eps)

        indices = np.digitize(X, self._bin_bounds, right=True) - 1
        indices = np.clip(indices, 0, self.bins - 1)

        calibrated = self._bin_map[indices]
        return np.clip(calibrated, 0.0, 1.0)

    def get_degrees_of_freedom(self):
        return self.bins


class BBQ:
    """
    Bayesian Binning into Quantiles (BBQ).

    Creates histogram binning models across a range of bin counts,
    scores them with BIC, computes relative model posteriors, applies
    elbow filtering, and normalizes weights for ensemble prediction.
    """

    def __init__(self, score_function='bic'):
        sf = score_function.lower()
        if sf not in ('bic', 'aic'):
            raise ValueError(f"Unknown score function: {score_function}")
        self.score_function = sf
        self._models = []
        self._weights = []

    def fit(self, X, y):
        X = np.asarray(X, dtype=np.float64).ravel()
        y = np.asarray(y, dtype=np.float64).ravel()
        n = len(X)

        # Determine bin range (Naeini et al., AAAI 2015)
        # For 1D (binary classification): num_features = 1
        constant = 10.0
        n_root = n ** (1.0 / 3.0)  # N^(1/(num_features+2)) with num_features=1
        min_bins = int(max(1, np.floor(n_root / constant)))
        max_bins = int(min(np.ceil(n / 5.0), np.ceil(n_root * constant)))

        # Ensure at least one model
        if max_bins < min_bins:
            max_bins = min_bins

        # Create and fit histogram binning models
        models = []
        for b in range(min_bins, max_bins + 1):
            hb = HistogramBinning(bins=b)
            hb.fit(X, y)
            models.append(hb)

        # Compute information criterion scores
        ic_scores = self._compute_ic_scores(X, y, models)

        # Convert to relative model posteriors
        model_posteriors = np.exp((np.min(ic_scores) - ic_scores) / 2.0)

        # Apply elbow method to filter models
        self._weights, self._models = self._elbow(models, model_posteriors)

        return self

    def _compute_ic_scores(self, X, y, models):
        """Compute BIC or AIC scores for each model."""
        n = len(X)
        scores = np.zeros(len(models))

        for i, model in enumerate(models):
            preds = model.transform(X)

            # Clip for numerical stability in log computation
            eps = np.finfo(np.float64).eps
            preds = np.clip(preds, eps, 1.0 - eps)

            # Binary cross-entropy log-likelihood
            ll = np.sum(y * np.log(preds) + (1.0 - y) * np.log(1.0 - preds))
            k = model.get_degrees_of_freedom()

            if self.score_function == 'bic':
                scores[i] = -2.0 * ll + k * np.log(n)
            else:  # aic
                scores[i] = -2.0 * ll + 2.0 * k

        return scores

    def _elbow(self, models, posteriors, alpha=0.001):
        """
        Select models by elbow method: keep models while consecutive
        score differences scaled by variance exceed threshold.
        """
        n = len(posteriors)
        variance = np.var(posteriors)

        # Sort by posterior score (descending = best first)
        sorted_idx = np.argsort(posteriors)[::-1]
        sorted_scores = posteriors[sorted_idx]

        k = 0

        # Phase 1: include all models with equal top score
        while k < n - 1 and sorted_scores[k] == sorted_scores[k + 1]:
            k += 1

        # Phase 2: elbow criterion — keep adding while score drop is significant
        if variance > 0:
            while k < n - 1 and \
                    (sorted_scores[k] - sorted_scores[k + 1]) / variance > alpha:
                k += 1

        k += 1  # k is now a count

        kept_models = [models[sorted_idx[i]] for i in range(k)]
        kept_weights = np.array([posteriors[sorted_idx[i]] for i in range(k)])
        kept_weights = kept_weights / np.sum(kept_weights)

        return kept_weights.tolist(), kept_models

    def transform(self, X):
        X = np.asarray(X, dtype=np.float64).ravel()
        calibrated = np.zeros_like(X)

        for weight, model in zip(self._weights, self._models):
            calibrated += weight * model.transform(X)

        return np.clip(calibrated, 0.0, 1.0)

    @property
    def num_models_selected(self):
        return len(self._models)

    @property
    def model_weights(self):
        return list(self._weights)


# ---------------------------------------------------------------------------
# Calibration metrics
# ---------------------------------------------------------------------------

def _bin_data(X, y, bins):
    """Shared binning logic for metrics."""
    X = np.asarray(X, dtype=np.float64).ravel()
    y = np.asarray(y, dtype=np.float64).ravel()
    eps = np.finfo(np.float64).eps
    X = np.clip(X, eps, 1.0 - eps)

    bin_bounds = np.linspace(0.0, 1.0, bins + 1)
    n = len(X)

    bin_accs = []
    bin_confs = []
    bin_counts = []

    for b in range(bins):
        if b < bins - 1:
            mask = (X >= bin_bounds[b]) & (X < bin_bounds[b + 1])
        else:
            # Last bin includes right endpoint
            mask = (X >= bin_bounds[b]) & (X <= bin_bounds[b + 1])

        n_b = int(np.sum(mask))
        if n_b > 0:
            bin_accs.append(float(np.mean(y[mask])))
            bin_confs.append(float(np.mean(X[mask])))
            bin_counts.append(n_b)

    return bin_accs, bin_confs, bin_counts, n


def compute_ece(X, y, bins=10):
    """Expected Calibration Error."""
    bin_accs, bin_confs, bin_counts, n = _bin_data(X, y, bins)
    if n == 0:
        return 0.0
    ece = sum(
        (count / n) * abs(acc - conf)
        for acc, conf, count in zip(bin_accs, bin_confs, bin_counts)
    )
    return float(ece)


def compute_mce(X, y, bins=10):
    """Maximum Calibration Error."""
    bin_accs, bin_confs, bin_counts, n = _bin_data(X, y, bins)
    if not bin_accs:
        return 0.0
    mce = max(abs(acc - conf) for acc, conf in zip(bin_accs, bin_confs))
    return float(mce)


def compute_ace(X, y, bins=10):
    """Average Calibration Error."""
    bin_accs, bin_confs, bin_counts, n = _bin_data(X, y, bins)
    if not bin_accs:
        return 0.0
    gaps = [abs(acc - conf) for acc, conf in zip(bin_accs, bin_confs)]
    return float(np.mean(gaps))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) != 3:
        print("Usage: python3 calibrate.py <data_npz_path> <output_json_path>")
        sys.exit(1)

    data_path = sys.argv[1]
    output_path = sys.argv[2]

    data = np.load(data_path)
    X_train = data['confidences_train']
    y_train = data['labels_train']
    X_test = data['confidences_test']
    y_test = data['labels_test']

    # Uncalibrated metrics
    uncalibrated = {
        'ece': compute_ece(X_test, y_test),
        'mce': compute_mce(X_test, y_test),
        'ace': compute_ace(X_test, y_test),
    }

    # Histogram Binning
    hb = HistogramBinning(bins=10)
    hb.fit(X_train, y_train)
    hb_preds = hb.transform(X_test)
    histogram_binning = {
        'ece': compute_ece(hb_preds, y_test),
        'mce': compute_mce(hb_preds, y_test),
        'ace': compute_ace(hb_preds, y_test),
        'calibrated_predictions': hb_preds.tolist(),
    }

    # BBQ
    bbq = BBQ(score_function='bic')
    bbq.fit(X_train, y_train)
    bbq_preds = bbq.transform(X_test)
    bbq_result = {
        'ece': compute_ece(bbq_preds, y_test),
        'mce': compute_mce(bbq_preds, y_test),
        'ace': compute_ace(bbq_preds, y_test),
        'calibrated_predictions': bbq_preds.tolist(),
        'num_models_selected': bbq.num_models_selected,
        'model_weights': bbq.model_weights,
    }

    results = {
        'uncalibrated': uncalibrated,
        'histogram_binning': histogram_binning,
        'bbq': bbq_result,
    }

    with open(output_path, 'w') as f:
        json.dump(results, f, indent=2)

    print(f"Results written to {output_path}")
    print(f"  Uncalibrated ECE: {uncalibrated['ece']:.6f}")
    print(f"  Histogram Binning ECE: {histogram_binning['ece']:.6f}")
    print(f"  BBQ ECE: {bbq_result['ece']:.6f}")
    print(f"  BBQ models selected: {bbq.num_models_selected}")


if __name__ == '__main__':
    main()
