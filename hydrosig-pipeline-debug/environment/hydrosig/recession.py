"""Recession analysis module.

Identifies recession segments in streamflow hydrographs and fits
master recession curves to determine the baseflow recession constant K.
"""
import numpy as np
from scipy import stats


def find_segments(streamflow, min_length=15):
    """Find consecutive decreasing flow periods.

    Parameters
    ----------
    streamflow : array-like
        Daily streamflow time series.
    min_length : int
        Minimum segment length in days.

    Returns
    -------
    numpy.ndarray
        (N, 2) array of (start, end) indices for each recession segment.
    """
    q = np.asarray(streamflow, dtype=np.float64)
    n = len(q)
    segments = []
    start = None

    for i in range(1, n):
        if q[i] <= q[i - 1]:
            if start is None:
                start = i - 1
        else:
            if start is not None:
                end = i - 1
                if (end - start) >= min_length:
                    segments.append((start, end))
                start = None

    if segments:
        return np.array(segments, dtype=np.int64)
    return np.empty((0, 2), dtype=np.int64)


def exponential_mrc(streamflow, flow_section):
    """Build master recession curve using matching strip method.

    Sorts recession segments by starting flow and sequentially
    shifts them to build a composite decay curve.
    """
    q = np.asarray(streamflow, dtype=np.float64)

    start_values = q[flow_section[:, 0]]
    sort_indices = np.argsort(start_values)

    first_idx = sort_indices[0]
    s0, e0 = flow_section[first_idx]
    mrc = np.column_stack((
        np.arange(1, e0 - s0 + 2, dtype=np.float64),
        q[s0:e0 + 1]
    ))

    for i in range(1, len(flow_section)):
        seg_idx = sort_indices[i]
        s, e = flow_section[seg_idx]

        log_q = np.log(np.maximum(mrc[:, 1], 1e-10))
        coeffs = np.polyfit(mrc[:, 0], log_q, 1)

        start_val = max(start_values[seg_idx], 1e-10)
        timeshift = (np.log(start_val) - coeffs[1]) / coeffs[0]

        new_seg = np.column_stack((
            timeshift + np.arange(1, e - s + 2, dtype=np.float64),
            q[s:e + 1]
        ))
        mrc = np.vstack((mrc, new_seg))

    return mrc


def recession_constant(streamflow, min_recession_length=15):
    """Compute recession constant K from master recession curve.

    K = -slope of log(Q) vs time regression on the composite MRC.
    """
    q = np.asarray(streamflow, dtype=np.float64)
    segments = find_segments(q, min_recession_length)

    if len(segments) < 2:
        return float('nan')

    mrc = exponential_mrc(q, segments)

    log_q = np.log(np.maximum(mrc[:, 1], 1e-10))
    slope_val, _, _, _, _ = stats.linregress(mrc[:, 0], log_q)

    return float(-slope_val)
