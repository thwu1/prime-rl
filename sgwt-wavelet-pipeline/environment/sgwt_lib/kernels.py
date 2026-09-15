"""Wavelet kernel definitions for SGWT filterbanks."""
import numpy as np


def _meyer_v(x):
    """Auxiliary smoothing polynomial for Meyer wavelet transitions.

    Provides C^3 smooth transitions between the pass-band and stop-band
    of the Meyer scaling function and wavelet.
    """
    return x ** 4 * (35.0 - 84.0 * x + 70.0 * x ** 2 - 21.0 * x ** 3)


def meyer_kernel(x, kernel_type):
    """Evaluate the Meyer wavelet or scaling-function kernel.

    Parameters
    ----------
    x : array_like
        Scaled eigenvalues (typically ``scale * eigenvalues``).
    kernel_type : {'scaling_function', 'wavelet'}
        Which part of the Meyer decomposition to evaluate.
    """
    x = np.asarray(x, dtype=float)
    l1 = 2.0 / 3.0
    l2 = 4.0 / 3.0
    l3 = 8.0 / 3.0

    r = np.zeros_like(x)

    if kernel_type == "scaling_function":
        r1 = x < l1
        r2 = (x >= l1) & (x < l2)
        r[r1] = 1.0
        r[r2] = np.cos(np.pi / 2.0 * _meyer_v(np.abs(x[r2]) / l1 - 1.0))
    elif kernel_type == "wavelet":
        r2 = (x >= l1) & (x < l2)
        r3 = (x >= l2) & (x < l3)
        r[r2] = np.sin(np.pi / 2.0 * _meyer_v(np.abs(x[r2]) / l1 - 1.0))
        r[r3] = np.cos(np.pi / 2.0 * _meyer_v(np.abs(x[r3]) / l2 - 1.0))
    else:
        raise ValueError(f"Unknown kernel type: {kernel_type}")
    return r


def mexicanhat_lowpass(x, lmin):
    """Low-pass scaling function for the MexicanHat filterbank.

    Provides spectral coverage at the lowest frequencies below the
    first wavelet scale.
    """
    return 1.2 * np.exp(-1.0) * np.exp(-((x / (0.4 * lmin)) ** 2))


def mexicanhat_bandpass(x, scale):
    """Band-pass wavelet for the MexicanHat filterbank at a given scale."""
    return scale * x * np.exp(-scale * x)
