"""Wavelet scale computation for SGWT filterbanks."""
import numpy as np


def compute_log_scales(lmin, lmax, Nscales, t1=1, t2=2):
    """Compute logarithmically-spaced wavelet scales.

    Scales cover the spectrum from low to high frequencies.  The
    output array has ``Nscales`` entries spaced evenly in the log
    domain between the bounds derived from ``lmin`` and ``lmax``.

    Parameters
    ----------
    lmin : float
        Effective minimum eigenvalue (smallest non-zero).
    lmax : float
        Maximum eigenvalue of the graph Laplacian.
    Nscales : int
        Number of scales to produce.
    t1, t2 : float
        Coverage parameters that control the scale range:
        ``scale_min = t1 / lmax``, ``scale_max = t2 / lmin``.

    Returns
    -------
    scales : ndarray, shape (Nscales,)
        Wavelet scales.
    """
    scale_min = t1 / lmax
    scale_max = t2 / lmin
    return np.exp(np.linspace(np.log(scale_min), np.log(scale_max), Nscales))
