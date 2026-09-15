"""Baseflow separation using the Lyne-Hollick recursive digital filter.

References
----------
Lyne, V. and Hollick, M., 1979. Stochastic time-variable rainfall-runoff
modelling. Inst. Eng. Aust. Natl. Conf. Publ., 79/10, pp.89-93.

Ladson, A.R., Brown, R., Neal, B. and Nathan, R., 2013.
A standard approach to baseflow separation using the Lyne and Hollick filter.
Australasian Journal of Water Resources, 17(1), pp.25-34.

Su, C.H., Costelloe, J.F., Peterson, T.J. and Western, A.W., 2016.
On the structural limitations of recursive digital filters for base flow
estimation. Water Resources Research, 52(6), pp.4745-4764.
"""
import numpy as np


def _forward_pass(q, alpha):
    """Forward pass of the Lyne-Hollick filter.

    Computes quickflow using the recursive digital filter, then
    derives baseflow as the residual.
    """
    qf = np.zeros_like(q, dtype=np.float64)
    qf[0] = q[0] - np.min(q)

    for i in range(1, len(q)):
        qf[i] = alpha * qf[i - 1] + 0.5 * (1 - alpha) * (q[i] - q[i - 1])

    qb = np.where(qf > 0, q - qf, q)
    return qb


def _backward_pass(q, alpha):
    """Backward pass of the Lyne-Hollick filter."""
    qf = np.zeros_like(q, dtype=np.float64)
    qf[-1] = q[-1] - np.min(q)

    for i in range(len(q) - 2, -1, -1):
        qf[i] = alpha * qf[i + 1] + 0.5 * (1 + alpha) * (q[i] - q[i + 1])

    qb = np.where(qf > 0, q - qf, q)
    return qb


def baseflow(discharge, alpha=0.925, n_passes=3, pad_width=10):
    """Extract baseflow using the Lyne-Hollick filter.

    Parameters
    ----------
    discharge : array-like
        Discharge time series (1D). Must not contain NaN values.
    alpha : float
        Filter parameter, must be between 0 and 1. Default is 0.925.
    n_passes : int
        Number of filter passes. Must be an odd number >= 1. Default is 3.
    pad_width : int
        Padding width for boundary effects. Default is 10.

    Returns
    -------
    numpy.ndarray
        Baseflow time series.
    """
    if n_passes < 1 or n_passes % 2 == 0:
        raise ValueError("n_passes must be an odd number >= 1")
    if not (0 < alpha < 1):
        raise ValueError("alpha must be between 0 and 1")

    q = np.asarray(discharge, dtype=np.float64).copy()
    q = np.pad(q, pad_width, mode="edge")

    qb = _forward_pass(q, alpha)

    passes = round(0.5 * (n_passes - 1))
    for _ in range(passes):
        qb = _forward_pass(_backward_pass(qb, alpha), alpha)

    qb = qb[pad_width:-pad_width]
    return qb


def baseflow_index(discharge, alpha=0.925, n_passes=3, pad_width=10):
    """Compute the baseflow index (BFI).

    BFI = sum(baseflow) / sum(total_flow)

    Parameters
    ----------
    discharge : array-like
        Discharge time series.
    alpha : float
        Filter parameter. Default is 0.925.
    n_passes : int
        Number of passes. Default is 3.
    pad_width : int
        Padding width. Default is 10.

    Returns
    -------
    float
        Baseflow index, between 0 and 1.
    """
    q = np.asarray(discharge, dtype=np.float64)
    q_sum = np.sum(q)
    if q_sum < 1e-6:
        return 0.0
    qb = baseflow(q, alpha, n_passes, pad_width)
    return float(np.sum(qb) / q_sum)
