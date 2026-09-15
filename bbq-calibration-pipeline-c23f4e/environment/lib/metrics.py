"""
Calibration metrics: ECE, MCE, ACE.

"""
import numpy as np


def _bin_data(confidences, correctness, n_bins):
    """Compute per-bin accuracy, confidence, and sample counts."""
    confidences = np.asarray(confidences, dtype=np.float64).ravel()
    correctness = np.asarray(correctness, dtype=np.float64).ravel()
    bin_edges = np.linspace(0.0, 1.0, n_bins + 1)

    bin_accs = []
    bin_confs = []
    bin_counts = []
    n_total = len(confidences)

    for b in range(n_bins):
        if b < n_bins - 1:
            mask = (confidences >= bin_edges[b]) & (confidences < bin_edges[b + 1])
        else:
            mask = (confidences >= bin_edges[b]) & (confidences <= bin_edges[b + 1])
        n_b = int(np.sum(mask))
        if n_b > 0:
            bin_accs.append(float(np.mean(correctness[mask])))
            bin_confs.append(float(np.mean(confidences[mask])))
            bin_counts.append(n_b)

    return bin_accs, bin_confs, bin_counts, n_total


def compute_ece(confidences, correctness, n_bins=10):
    """Expected Calibration Error."""
    bin_accs, bin_confs, bin_counts, n_total = _bin_data(
        confidences, correctness, n_bins
    )
    if not bin_accs:
        return 0.0
    gaps = [abs(a - c) for a, c in zip(bin_accs, bin_confs)]
    return float(np.mean(gaps))


def compute_mce(confidences, correctness, n_bins=10):
    """Maximum Calibration Error."""
    bin_accs, bin_confs, bin_counts, n_total = _bin_data(
        confidences, correctness, n_bins
    )
    if not bin_accs:
        return 0.0
    return float(max(abs(a - c) for a, c in zip(bin_accs, bin_confs)))


def compute_ace(confidences, correctness, n_bins=10):
    """Average Calibration Error."""
    bin_accs, bin_confs, bin_counts, n_total = _bin_data(
        confidences, correctness, n_bins
    )
    if not bin_accs:
        return 0.0
    gaps = [abs(a - c) for a, c in zip(bin_accs, bin_confs)]
    return float(np.mean(gaps))
