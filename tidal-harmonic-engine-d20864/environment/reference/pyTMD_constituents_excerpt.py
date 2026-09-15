"""
Excerpts from pyTMD (Python Tide Model Driver) constituent routines
and harmonic analysis solver.

Reference only -- not directly importable.

Source: https://github.com/tsutterley/pyTMD
License: MIT
"""

import numpy as np


# ================================================================
# From pyTMD/constituents.py: _to_doodson_number
# ================================================================

def _to_doodson_number(coef, **kwargs):
    """
    Converts Doodson coefficients (Cartwright numbers) to
    classic Doodson number.

    The convention is that indices 1-5 are each offset by +5
    (the Doodson offset), while index 0 (tau) is not offset.

    Parameters
    ----------
    coef: np.ndarray
        7-element Doodson coefficient array [tau, s, h, p, n, pp, k]

    Returns
    -------
    number: float
        Classic Doodson number
    """
    c = np.array(coef[:6], dtype=int)
    c[1:] += 5
    number = (c[0] * 100 + c[1] * 10 + c[2]
              + c[3] * 0.1 + c[4] * 0.01 + c[5] * 0.001)
    return number


# ================================================================
# From pyTMD/constituents.py: _frequency
# ================================================================

def _frequency(coef, method='Cartwright'):
    """
    Calculates the angular frequency for Doodson coefficients
    (Cartwright numbers).

    Returns omega in radians per second.

    Parameters
    ----------
    coef: np.ndarray
        Doodson coefficients for constituent(s)
    method: str
        Method for computing mean longitudes
    """
    # Two closely-spaced MJDs near J2000
    MJD = np.array([51544.5, 51544.55])
    deltat = 86400.0 * (MJD[1] - MJD[0])
    # calculate the mean longitudes
    s, h, p, n, pp = mean_longitudes(MJD, method=method)

    nt = len(MJD)
    hour = 24.0 * np.mod(MJD, 1)
    tau = 15.0 * hour - s + h
    k = 90.0 + np.zeros(nt)

    fargs = np.c_[tau, s, h, p, n, pp, k]
    # calculate the rates of change of the fundamental arguments
    rates = (fargs[1, :] - fargs[0, :]) / deltat
    fd = np.dot(rates, coef)
    # convert to radians per second
    omega = 2.0 * np.pi * fd / 360.0
    return np.abs(omega)


# ================================================================
# From pyTMD/constituents.py: nodal_modulation (OTIS corrections)
# ================================================================

def nodal_modulation(n, p, constituents, corrections='OTIS'):
    """
    Calculates the nodal corrections for tidal constituents.

    Parameters
    ----------
    n: np.ndarray
        Mean longitude of ascending lunar node (degrees)
    p: np.ndarray
        Mean longitude of lunar perigee (degrees)
    constituents: list
        Tidal constituent IDs
    corrections: str
        Use nodal corrections from OTIS, FES or GOT models

    Returns
    -------
    u: np.ndarray
        Nodal correction angle (radians)
    f: np.ndarray
        Nodal modulation factor
    """
    OTIS_TYPE = corrections in ('OTIS', 'ATLAS', 'TMD3', 'netcdf')

    # convert longitudes to radians
    N = np.radians(n)
    P = np.radians(p)
    # trigonometric factors for nodal corrections
    sinn = np.sin(N)
    cosn = np.cos(N)
    sin2n = np.sin(2.0 * N)
    cos2n = np.cos(2.0 * N)
    sin3n = np.sin(3.0 * N)
    sinp = np.sin(P)
    cosp = np.cos(P)
    sin2p = np.sin(2.0 * P)
    cos2p = np.cos(2.0 * P)

    nt = len(np.atleast_1d(n))
    nc = len(constituents)
    f = np.zeros((nt, nc))
    u = np.zeros((nt, nc))

    for i, c in enumerate(constituents):
        if c in ('msf', 'tau1', 'p1', 'theta1', 'lambda2', 's2') and OTIS_TYPE:
            term1 = 0.0
            term2 = 1.0

        elif c in ('mm', 'msm') and OTIS_TYPE:
            term1 = 0.0
            term2 = 1.0 - 0.130 * cosn

        elif c in ('mf', 'msqm', 'msp', 'mq', 'mtm') and OTIS_TYPE:
            f[:, i] = 1.043 + 0.414 * cosn
            u[:, i] = np.radians(-23.7 * sinn + 2.7 * sin2n - 0.4 * sin3n)
            continue

        elif c in ('o1', 'so3', 'op2') and OTIS_TYPE:
            term1 = 0.189 * sinn - 0.0058 * sin2n
            term2 = 1.0 + 0.189 * cosn - 0.0058 * cos2n
            f[:, i] = np.hypot(term1, term2)  # O1
            u[:, i] = np.radians(10.8 * sinn - 1.3 * sin2n + 0.2 * sin3n)
            continue

        elif c in ('2q1', 'q1', 'rho1', 'sigma1') and OTIS_TYPE:
            f[:, i] = np.hypot(1.0 + 0.188 * cosn, 0.188 * sinn)
            u[:, i] = np.arctan(0.189 * sinn / (1.0 + 0.189 * cosn))
            continue

        elif c in ('k1', 'sk3', '2sk5') and OTIS_TYPE:
            term1 = -0.1554 * sinn + 0.0029 * sin2n
            term2 = 1.0 + 0.1158 * cosn - 0.0029 * cos2n

        elif c in ('m2', '2n2', 'mu2', 'n2', 'nu2', 'lambda2', 'ms4',
                    'eps2', '2sm6', '2sn6', 'mp1', 'mp3', 'sn4'):
            term1 = -0.03731 * sinn + 0.00052 * sin2n
            term2 = 1.0 - 0.03731 * cosn + 0.00052 * cos2n

        elif c in ('l2', 'sl4') and OTIS_TYPE:
            term1 = -0.25 * sin2p - 0.11 * np.sin(2.0 * P - N) - 0.04 * sinn
            term2 = (1.0 - 0.25 * cos2p
                     - 0.11 * np.cos(2.0 * P - N) - 0.04 * cosn)

        elif c in ('k2', 'sk4', '2sk6', 'kp1') and OTIS_TYPE:
            term1 = -0.3108 * sinn - 0.0324 * sin2n
            term2 = 1.0 + 0.2852 * cosn + 0.0324 * cos2n

        elif c in ('oo1', 'ups1') and OTIS_TYPE:
            term1 = -0.640 * sinn - 0.134 * sin2n
            term2 = 1.0 + 0.640 * cosn + 0.134 * cos2n

        elif c in ('j1', 'theta1'):
            term1 = -0.227 * sinn
            term2 = 1.0 + 0.169 * cosn

        elif c in ('eta2', 'zeta2'):
            term1 = -0.436 * sinn
            term2 = 1.0 + 0.436 * cosn

        elif c in ('m1', 'm1a', 'm1b'):
            # perth5 coefficients (assuming argument includes p)
            term1 = (-0.2294 * sinn - 0.3594 * sin2p
                     - 0.0664 * np.sin(2.0 * P - N))
            term2 = (1.0 + 0.1722 * cosn + 0.3594 * cos2p
                     + 0.0664 * np.cos(2.0 * P - N))

        elif c in ('ssa', 'sa'):
            term1 = 0.0
            term2 = 1.0

        else:
            f[:, i] = 1.0
            u[:, i] = 0.0
            continue

        # default: compute f and u from term1 and term2
        f[:, i] = np.hypot(term1, term2)
        u[:, i] = np.arctan2(term1, term2)

    return u, f


# ================================================================
# From pyTMD/constituents.py: _constituent_parameters
# ================================================================

def _constituent_parameters(c):
    """
    Loads parameters for a given tidal constituent.

    Returns
    -------
    amplitude: Amplitude of equilibrium tide (meters)
    phase: Phase at t0 = 1 Jan 0:00 1992 (radians)
    omega: Angular frequency (radians/s)
    alpha: Load Love number
    species: Spherical harmonic dependence
    """
    _omega = {
        "m2": 1.405189e-04, "s2": 1.454441e-04, "k1": 7.292117e-05,
        "o1": 6.759774e-05, "n2": 1.378797e-04, "p1": 7.252295e-05,
        "k2": 1.458423e-04, "q1": 6.495854e-05, "2n2": 1.352405e-04,
        "mu2": 1.355937e-04, "nu2": 1.382329e-04, "l2": 1.431581e-04,
        "t2": 1.452450e-04, "j1": 7.556036e-05, "m1": 7.025945e-05,
        "oo1": 7.824458e-05, "rho1": 6.531174e-05, "mf": 0.053234e-04,
        "mm": 0.026392e-04, "ssa": 0.003982e-04,
    }
    _phase = {
        "m2": 1.731557546, "s2": 0.0, "k1": 0.173003674, "o1": 1.558553872,
        "n2": 6.050721243, "p1": 6.110181633, "k2": 3.487600001,
        "q1": 5.877717569, "2n2": 4.086699633, "mu2": 3.463115091,
        "nu2": 5.427136701, "l2": 0.553986502, "t2": 0.050398470,
        "j1": 2.137025284, "m1": 2.436575000, "oo1": 1.92904613,
        "rho1": 5.254133027, "mf": 1.756042456, "mm": 1.964021610,
        "ssa": 3.487600001,
    }
    _amplitude = {
        "m2": 0.2441, "s2": 0.112743, "k1": 0.141565, "o1": 0.100661,
        "n2": 0.046397, "p1": 0.046848, "k2": 0.030684, "q1": 0.019273,
        "2n2": 0.006141, "mu2": 0.007408, "nu2": 0.008811, "l2": 0.006931,
        "t2": 0.006608, "j1": 0.007915, "m1": 0.007915, "oo1": 0.004338,
        "rho1": 0.003661, "mf": 0.042041, "mm": 0.022191, "ssa": 0.019567,
    }
    _alpha = {
        "m2": 0.693, "s2": 0.693, "k1": 0.736, "o1": 0.695, "n2": 0.693,
        "p1": 0.706, "k2": 0.693, "q1": 0.695,
    }
    _species = {
        "m2": 2, "s2": 2, "k1": 1, "o1": 1, "n2": 2, "p1": 1, "k2": 2,
        "q1": 1, "2n2": 2, "mu2": 2, "nu2": 2, "l2": 2, "t2": 2, "j1": 1,
        "m1": 1, "oo1": 1, "rho1": 1, "mf": 0, "mm": 0, "ssa": 0,
    }
    name = c.lower()
    return (
        _amplitude.get(name, 0.0),
        _phase.get(name, 0.0),
        _omega.get(name, 0.0),
        _alpha.get(name, 0.0),
        _species.get(name, 0),
    )


# ================================================================
# From pyTMD/solve/constants.py: harmonic analysis design matrix
# ================================================================

# number of days between MJD and the tide epoch (1992-01-01T00:00:00)
_mjd_tide = 48622.0


def constants(t, ht, constituents, corrections='OTIS'):
    """
    Estimate the harmonic constants for a time series.

    Parameters
    ----------
    t: float or np.ndarray
        Days relative to 1992-01-01T00:00:00
    ht: np.ndarray
        Input time series (elevation or currents)
    constituents: list
        Tidal constituent IDs
    corrections: str
        Use nodal corrections from OTIS or FES models

    Design matrix construction (for OTIS corrections):
        For each constituent k:
            theta_k = omega_k * t * 86400 + phase_k + pu[:, k]
            column 2k:   pf[:, k] * cos(theta_k)
            column 2k+1: -pf[:, k] * sin(theta_k)

    The complex harmonic constant is then:
        hc = p[2k] - 1j * p[2k+1]
    """
    t = np.ravel(t)
    ht = np.ravel(ht)
    nc = len(constituents)

    # load the nodal corrections
    # pu = nodal phase angle, pf = nodal factor
    # G = equilibrium phase (degrees)
    pu, pf, G = arguments(t + _mjd_tide, constituents, corrections=corrections)

    # create design matrix
    M = []
    for k, c in enumerate(constituents):
        if corrections in ('OTIS', 'ATLAS', 'TMD3', 'netcdf'):
            amp, ph, omega, alpha, species = _constituent_parameters(c)
            th = omega * t * 86400.0 + ph + pu[:, k]
        else:
            th = np.radians(G[:, k]) + pu[:, k]
        # add constituent to design matrix
        M.append(pf[:, k] * np.cos(th))
        M.append(-pf[:, k] * np.sin(th))
    # take the transpose of the design matrix
    M = np.transpose(M)

    # solve via least squares
    p, res, rnk, s = np.linalg.lstsq(M, ht, rcond=-1)

    # indices for the cosine and sine terms
    nc = len(constituents)
    icos = 2 * np.arange(nc)
    isin = 2 * np.arange(nc) + 1
    hc = p[icos] - 1j * p[isin]
    return hc


# ================================================================
# From pyTMD/predict/_tides.py: tide prediction
# ================================================================

def predict_tide(t, hc, constituents, corrections='OTIS'):
    """
    Predict tidal elevations using harmonic constants.

    For OTIS models, each constituent contribution is:
        pf[:, k] * (hc[k].real * cos(theta) - hc[k].imag * sin(theta))

    where theta = omega * t * 86400 + phase + pu
    and pf is the nodal amplitude factor.
    """
    t = np.ravel(t)
    pu, pf, G = arguments(t + _mjd_tide, constituents, corrections=corrections)

    ht = np.zeros_like(t, dtype=float)
    for k, c in enumerate(constituents):
        if corrections in ('OTIS', 'ATLAS', 'TMD3', 'netcdf'):
            amp, ph, omega, alpha, species = _constituent_parameters(c)
            th = omega * t * 86400.0 + ph + pu[:, k]
        else:
            th = np.radians(G[:, k]) + pu[:, k]
        # reconstruct with nodal amplitude factor
        ht += pf[:, k] * (hc[k].real * np.cos(th) - hc[k].imag * np.sin(th))

    return ht
