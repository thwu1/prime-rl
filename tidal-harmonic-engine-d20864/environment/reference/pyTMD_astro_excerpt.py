"""
Excerpts from pyTMD (Python Tide Model Driver) astronomical routines.
Reference only -- not directly importable. Requires pyTMD.math and other
dependencies not present in this environment.

Source: https://github.com/tsutterley/pyTMD
License: MIT

The key function is mean_longitudes() which computes the five basic
astronomical mean longitudes using one of four methods.
"""

import numpy as np

# number of days between MJD and the J2000 epoch
_mjd_j2000 = 51544.5
# Julian century
_century = 36525.0


def normalize_angle(angle):
    """Normalize angle to range [0, 360)"""
    return angle % 360.0


def polynomial_sum(coefficients, t):
    """Evaluate polynomial with given coefficients at t.
    coefficients[0] + coefficients[1]*t + coefficients[2]*t^2 + ...
    """
    result = np.zeros_like(t, dtype=float)
    for i, c in enumerate(coefficients):
        result = result + c * np.power(t, i)
    return result


# PURPOSE: compute the basic astronomical mean longitudes
def mean_longitudes(MJD, method='Cartwright'):
    r"""
    Computes the basic astronomical mean longitudes: S, H, P, N and Ps

    Note N is not N', i.e. N is decreasing with time.

    Parameters
    ----------
    MJD: np.ndarray
        Modified Julian Day (MJD) of input date
    method: str, default 'Cartwright'
        Method for calculating mean longitudes

            - 'Cartwright': use coefficients from David Cartwright
            - 'Meeus': use coefficients from Meeus Astronomical Algorithms
            - 'ASTRO5': use Meeus Astronomical coefficients from ASTRO5
            - 'IERS': convert from IERS Delaunay arguments

    Returns
    -------
    S: Mean longitude of Moon (degrees)
    H: Mean longitude of Sun (degrees)
    P: Mean longitude of lunar perigee (degrees)
    N: Mean longitude of ascending lunar node (degrees)
    Ps: Longitude of solar perigee (degrees)
    """
    if method.title() == 'Meeus':
        # convert from MJD to days relative to 2000-01-01T12:00:00
        T = MJD - _mjd_j2000
        # mean longitude of Moon
        lunar_longitude = np.array([
            218.3164591, 13.17639647754579,
            -9.9454632e-13, 3.8086292e-20, -8.6184958e-27,
        ])
        S = polynomial_sum(lunar_longitude, T)
        # mean longitude of Sun
        solar_longitude = np.array([280.46645, 0.985647360164271, 2.2727347e-13])
        H = polynomial_sum(solar_longitude, T)
        # mean longitude of lunar perigee
        lunar_perigee = np.array([
            83.3532430, 0.11140352391786447,
            -7.7385418e-12, -2.5636086e-19, 2.95738836e-26,
        ])
        P = polynomial_sum(lunar_perigee, T)
        # mean longitude of ascending lunar node
        lunar_node = np.array([
            125.0445550, -0.052953762762491446,
            1.55628359e-12, 4.390675353e-20, -9.26940435e-27,
        ])
        N = polynomial_sum(lunar_node, T)
        # mean longitude of solar perigee (Simon et al., 1994)
        Ps = 282.94 + (1.7192 * T) / _century
    elif method.upper() == 'ASTRO5':
        # convert from MJD to centuries relative to 2000-01-01T12:00:00
        T = (MJD - _mjd_j2000) / _century
        # mean longitude of Moon (p. 338)
        lunar_longitude = np.array([
            218.3164477, 481267.88123421,
            -1.5786e-3, 1.855835e-6, -1.53388e-8
        ])
        S = polynomial_sum(lunar_longitude, T)
        # mean longitude of Sun (p. 338)
        lunar_elongation = np.array([
            297.8501921, 445267.1114034,
            -1.8819e-3, 1.83195e-6, -8.8445e-9
        ])
        H = polynomial_sum(lunar_longitude - lunar_elongation, T)
        # mean longitude of lunar perigee (p. 343)
        lunar_perigee = np.array([83.3532465, 4069.0137287, -1.032e-2, -1.249172e-5])
        P = polynomial_sum(lunar_perigee, T)
        # mean longitude of ascending lunar node (p. 144)
        lunar_node = np.array([125.04452, -1934.136261, 2.0708e-3, 2.22222e-6])
        N = polynomial_sum(lunar_node, T)
        # mean longitude of solar perigee (Simon et al., 1994)
        Ps = 282.94 + 1.7192 * T
    else:
        # Formulae for the period 1990--2010 derived by David Cartwright
        # convert from MJD to days relative to 2000-01-01T12:00:00
        # convert from Universal Time to Dynamic Time at 2000-01-01
        T = MJD - 51544.4993
        # mean longitude of Moon
        S = 218.3164 + 13.17639648 * T
        # mean longitude of Sun
        H = 280.4661 + 0.98564736 * T
        # mean longitude of lunar perigee
        P = 83.3535 + 0.11140353 * T
        # mean longitude of ascending lunar node
        N = 125.0445 - 0.05295377 * T
        # solar perigee at epoch 2000
        Ps = np.full_like(T, 282.8)
    # take the modulus of each
    S = normalize_angle(S)
    H = normalize_angle(H)
    P = normalize_angle(P)
    N = normalize_angle(N)
    Ps = normalize_angle(Ps)
    # return as tuple
    return (S, H, P, N, Ps)
