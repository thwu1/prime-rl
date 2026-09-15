"""Baseflow separation using recursive digital filtering.

Implements the Lyne-Hollick (1979) recursive digital filter with
multi-pass support following Nathan & McMahon (1990).

Standard parameters: alpha=0.925, n_passes=3, pad_width=10.
"""
import numpy as np


def forward_pass(q, alpha):
    """Forward pass: recursive high-pass filter for quickflow extraction."""
    n = len(q)
    qf = np.zeros(n, dtype=np.float64)
    qf[0] = q[0] - np.min(q)
    for i in range(1, n):
        qf[i] = alpha * qf[i - 1] + 0.5 * (1 - alpha) * (q[i] - q[i - 1])
    return np.where(qf > 0, q - qf, q)


def backward_pass(q, alpha):
    """Backward pass: same filter applied in reverse direction."""
    n = len(q)
    qf = np.zeros(n, dtype=np.float64)
    qf[-1] = q[-1] - np.min(q)
    for i in range(n - 2, -1, -1):
        qf[i] = alpha * qf[i + 1] + 0.5 * (1 - alpha) * (q[i] - q[i + 1])
    return np.where(qf > 0, q - qf, q)


def separate(discharge, alpha=0.925, n_passes=3, pad_width=10):
    """Extract baseflow using multi-pass filtering.

    Parameters
    ----------
    discharge : array-like
        Daily streamflow time series.
    alpha : float
        Filter parameter (default 0.925).
    n_passes : int
        Number of passes (odd, >= 1).
    pad_width : int
        Edge padding width for boundary effects.

    Returns
    -------
    numpy.ndarray
        Baseflow time series.
    """
    q = np.asarray(discharge, dtype=np.float64).copy()
    q = np.pad(q, pad_width, mode='edge')

    qb = forward_pass(q, alpha)
    extra = round(0.5 * (n_passes - 1))
    for _ in range(extra):
        qb = forward_pass(backward_pass(qb, alpha), alpha)

    qb = qb[pad_width:-pad_width]
    return qb


def bfi(discharge, alpha=0.925, n_passes=3, pad_width=10):
    """Compute Baseflow Index (BFI = sum(Qb) / sum(Q))."""
    q = np.asarray(discharge, dtype=np.float64)
    total = np.sum(q)
    if total < 1e-6:
        return 0.0
    qb = separate(q, alpha, n_passes, pad_width)
    return float(np.sum(qb) / total)
