"""
JONSWAP spectral density and directional spreading functions.
"""

import numpy as np


def jonswap_spectrum(f, Hm0, Tp, gamma=3.3):
    """Compute JONSWAP energy density spectrum.

    Parameters
    ----------
    f : array_like
        Frequency array in Hz (must be > 0 for meaningful output).
    Hm0 : float
        Significant wave height in metres.
    Tp : float
        Peak wave period in seconds.
    gamma : float
        Peak enhancement factor (default 3.3).

    Returns
    -------
    numpy.ndarray
        Spectral density S(f) in m^2/Hz, alpha-scaled so that
        4 * sqrt(integral S df) = Hm0.
    """
    f = np.asarray(f, dtype=float)
    fp = 1.0 / Tp
    g = 9.81

    # Avoid division by zero for f == 0
    f_safe = np.where(f > 0, f, 1.0)

    # Pierson-Moskowitz base spectrum
    S_pm = (g ** 2 / (16.0 * np.pi ** 4)) * f_safe ** (-5) * np.exp(
        -1.25 * (fp / f_safe) ** 4
    )

    # Peak enhancement (JONSWAP gamma factor)
    sigma = np.where(f_safe <= fp, 0.07, 0.09)
    r = np.exp(-0.5 * ((f_safe - fp) / (sigma * fp)) ** 2)
    S_unit = S_pm * gamma ** r

    # Zero out f <= 0 entries
    S_unit = np.where(f > 0, S_unit, 0.0)

    # Alpha-scale to match desired Hm0
    # Hm0 = 4 * sqrt(m0)  =>  m0_target = (Hm0/4)^2
    m0_target = (Hm0 / 4.0) ** 2

    # Numerical integration (trapezoidal)
    df = np.diff(f)
    m0_unit = np.sum(0.5 * (S_unit[:-1] + S_unit[1:]) * df)

    if m0_unit > 0:
        alpha = m0_target / m0_unit
    else:
        alpha = 0.0

    return alpha * S_unit


def directional_spreading(theta, theta_mean, s):
    """Cosine-power directional spreading function.

    Parameters
    ----------
    theta : array_like
        Direction angles in radians.
    theta_mean : float
        Mean wave direction in radians.
    s : float
        Spreading parameter (higher = narrower distribution).

    Returns
    -------
    numpy.ndarray
        D(theta), numerically normalized so integral D dtheta = 1.
    """
    theta = np.asarray(theta, dtype=float)
    half_diff = (theta - theta_mean) / 2.0

    # cos^(2s) of the half-angle difference; clamp negative cosines to zero
    cos_val = np.cos(half_diff)
    cos_val = np.maximum(cos_val, 0.0)
    D = cos_val ** (2.0 * s)

    # Numerical normalization via trapezoidal rule
    if len(theta) > 1:
        dtheta = np.diff(theta)
        integral = np.sum(0.5 * (D[:-1] + D[1:]) * dtheta)
        if integral > 0:
            D = D / integral

    return D
