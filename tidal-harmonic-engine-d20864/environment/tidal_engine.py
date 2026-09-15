#!/usr/bin/env python3
"""
Tidal harmonic analysis and prediction engine.
Mean longitudes computed via native C library (libastro).
"""

import json
import ctypes
import os
import numpy as np

# ── Constants ───────────────────────────────────────────────────────────

_MJD_J2000 = 51544.5
_MJD_TIDE = 48622.0  # 1992-01-01T00:00:00

# Load Doodson coefficients
with open("/app/doodson_coefficients.json") as _f:
    _DOODSON_COEFS = json.load(_f)

# ── C library for mean longitudes ────────────────────────────────────

_LIB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "libastro")
_LIB_PATH = os.path.join(_LIB_DIR, "libastro.so")
_libastro = ctypes.CDLL(_LIB_PATH)

_DPTR = ctypes.POINTER(ctypes.c_double)
_libastro.compute_mean_longitudes.argtypes = [
    _DPTR, ctypes.c_int, _DPTR, _DPTR, _DPTR, _DPTR, _DPTR
]
_libastro.compute_mean_longitudes.restype = None


# ── Mean longitudes (via C library) ─────────────────────────────────────

def mean_longitudes(mjd):
    """
    Compute astronomical mean longitudes via libastro.

    Parameters
    ----------
    mjd : float or np.ndarray
        Modified Julian Day

    Returns
    -------
    tuple of (s, h, p, n, pp) in degrees, each in [0, 360)
    """
    mjd_arr = np.atleast_1d(np.asarray(mjd, dtype=np.float64)).copy()
    nt = len(mjd_arr)
    s  = np.empty(nt, dtype=np.float64)
    h  = np.empty(nt, dtype=np.float64)
    p  = np.empty(nt, dtype=np.float64)
    n  = np.empty(nt, dtype=np.float64)
    pp = np.empty(nt, dtype=np.float64)

    _libastro.compute_mean_longitudes(
        mjd_arr.ctypes.data_as(_DPTR), ctypes.c_int(nt),
        s.ctypes.data_as(_DPTR), h.ctypes.data_as(_DPTR),
        p.ctypes.data_as(_DPTR), n.ctypes.data_as(_DPTR),
        pp.ctypes.data_as(_DPTR),
    )
    return (s, h, p, n, pp)


# ── Doodson number ─────────────────────────────────────────────────────

def doodson_number(constituent):
    """Compute classic Doodson number for a tidal constituent."""
    coef = np.array(_DOODSON_COEFS[constituent.lower()][:6], dtype=int)
    coef[1:] += 5
    DO = sum(v * 10 ** (2 - i) for i, v in enumerate(coef))
    return round(DO, 3)


# ── Angular frequency ──────────────────────────────────────────────────

def angular_frequency(constituents):
    """Compute angular frequencies for tidal constituents (rad/s)."""
    MJD = np.array([_MJD_J2000, _MJD_J2000 + 0.05])
    deltat = 86400.0 * (MJD[1] - MJD[0])

    s, h, p, n, pp = mean_longitudes(MJD)
    nt = len(MJD)
    hour = 24.0 * np.mod(MJD, 1)
    tau = 15.0 * hour - s + h
    k = 90.0 + np.zeros(nt)

    fargs = np.column_stack([tau, s, h, p, n, pp, k])

    nc = len(constituents)
    coef = np.zeros((7, nc))
    for i, c in enumerate(constituents):
        coef[:, i] = _DOODSON_COEFS[c.lower()]

    rates = (fargs[1, :] - fargs[0, :]) / deltat
    fd = np.dot(rates, coef)
    omega = fd / 360.0
    return np.abs(omega)


# ── Constituent parameters ─────────────────────────────────────────────

_SPECIES = {
    "m2": 2, "s2": 2, "k1": 1, "o1": 1, "n2": 2, "p1": 1, "k2": 2,
    "q1": 1, "2n2": 2, "mu2": 2, "nu2": 2, "l2": 2, "t2": 2, "j1": 1,
    "m1": 1, "oo1": 1, "rho1": 1, "mf": 0, "mm": 0, "ssa": 0,
    "m4": 4, "ms4": 4, "mn4": 4, "m6": 6, "m8": 8, "mk3": 3,
    "s6": 6, "2sm2": 2, "2mk3": 3, "msf": 0, "sa": 0, "mt": 0, "2q1": 1,
}

_ALPHA = {
    "m2": 0.693, "s2": 0.693, "k1": 0.736, "o1": 0.695, "n2": 0.693,
    "p1": 0.706, "k2": 0.693, "q1": 0.695, "2n2": 0.693, "mu2": 0.693,
    "nu2": 0.693, "l2": 0.693, "t2": 0.693, "j1": 0.695, "m1": 0.695,
    "oo1": 0.695, "rho1": 0.695, "mf": 0.693, "mm": 0.693, "ssa": 0.693,
    "m4": 0.693, "ms4": 0.693, "mn4": 0.693, "m6": 0.693, "m8": 0.693,
    "mk3": 0.693, "s6": 0.693, "2sm2": 0.693, "2mk3": 0.693,
    "msf": 0.693, "sa": 0.693, "mt": 0.693, "2q1": 0.693,
}

_OMEGA = {
    "m2": 1.405189e-04, "s2": 1.454441e-04, "k1": 7.292117e-05,
    "o1": 6.759774e-05, "n2": 1.378797e-04, "p1": 7.252295e-05,
    "k2": 1.458423e-04, "q1": 6.495854e-05, "2n2": 1.352405e-04,
    "mu2": 1.355937e-04, "nu2": 1.382329e-04, "l2": 1.431581e-04,
    "t2": 1.452450e-04, "j1": 7.556036e-05, "m1": 7.025945e-05,
    "oo1": 7.824458e-05, "rho1": 6.531174e-05, "mf": 0.053234e-04,
    "mm": 0.026392e-04, "ssa": 0.003982e-04, "m4": 2.810377e-04,
    "ms4": 2.859630e-04, "mn4": 2.783984e-04, "m6": 4.215566e-04,
    "m8": 5.620755e-04, "mk3": 2.134402e-04, "s6": 4.363323e-04,
    "2sm2": 1.503693e-04, "2mk3": 2.081166e-04, "msf": 4.925200e-06,
    "sa": 1.990970e-07, "mt": 7.962619e-06, "2q1": 6.231934e-05,
}

_PHASE = {
    "m2": 1.731557546, "s2": 0.0, "k1": 0.173003674, "o1": 1.558553872,
    "n2": 6.050721243, "p1": 6.110181633, "k2": 3.487600001,
    "q1": 5.877717569, "2n2": 4.086699633, "mu2": 3.463115091,
    "nu2": 5.427136701, "l2": 0.553986502, "t2": 0.050398470,
    "j1": 2.137025284, "m1": 2.436575000, "oo1": 1.92904613,
    "rho1": 5.254133027, "mf": 1.756042456, "mm": 1.964021610,
    "ssa": 3.487600001, "m4": 3.463115091, "ms4": 1.731557546,
    "mn4": 1.499093481, "m6": 5.194672637, "m8": 6.926230184,
    "mk3": 1.90456122, "s6": 0.0, "2sm2": 4.551627762,
    "2mk3": 3.290111417, "msf": 4.551627762, "sa": 6.232786837,
    "mt": 3.720064066, "2q1": 3.91369596,
}

_AMPLITUDE = {
    "m2": 0.2441, "s2": 0.112743, "k1": 0.141565, "o1": 0.100661,
    "n2": 0.046397, "p1": 0.046848, "k2": 0.030684, "q1": 0.019273,
    "2n2": 0.006141, "mu2": 0.007408, "nu2": 0.008811, "l2": 0.006931,
    "t2": 0.006608, "j1": 0.007915, "m1": 0.007915, "oo1": 0.004338,
    "rho1": 0.003661, "mf": 0.042041, "mm": 0.022191, "ssa": 0.019567,
    "m4": 0.0, "ms4": 0.0, "mn4": 0.0, "m6": 0.0, "m8": 0.0,
    "mk3": 0.0, "s6": 0.0, "2sm2": 0.0, "2mk3": 0.0,
    "msf": 0.003681, "sa": 0.003104, "mt": 0.008044, "2q1": 0.002565,
}


def _constituent_parameters(name):
    """Return (amplitude, phase, omega, alpha, species) for constituent."""
    c = name.lower()
    return (
        _AMPLITUDE.get(c, 0.0),
        _PHASE.get(c, 0.0),
        _OMEGA.get(c, 0.0),
        _ALPHA.get(c, 0.0),
        _SPECIES.get(c, 0),
    )


# ── Nodal corrections (OTIS type) ──────────────────────────────────────

def nodal_corrections(mjd, constituents):
    """
    Compute OTIS-type nodal corrections.

    Parameters
    ----------
    mjd : float or np.ndarray
        Modified Julian Day
    constituents : list of str
        Tidal constituent names

    Returns
    -------
    u : np.ndarray, shape (nt, nc)
        Nodal phase correction (radians)
    f : np.ndarray, shape (nt, nc)
        Nodal amplitude factor
    """
    mjd = np.atleast_1d(np.asarray(mjd, dtype=float))
    nt = len(mjd)
    nc = len(constituents)

    s, h, p, n, pp = mean_longitudes(mjd)

    N = np.radians(n)
    P = np.radians(p)
    sinn = np.sin(N)
    cosn = np.cos(N)
    sin2n = np.sin(2.0 * N)
    cos2n = np.cos(2.0 * N)
    sin3n = np.sin(3.0 * N)
    sin2p = np.sin(2.0 * P)
    cos2p = np.cos(2.0 * P)

    f = np.ones((nt, nc))
    u = np.zeros((nt, nc))

    for i, c in enumerate(constituents):
        c = c.lower()

        if c in ("msf", "tau1", "p1", "theta1", "lambda2", "s2"):
            f[:, i] = 1.0
            u[:, i] = 0.0

        elif c in ("mm", "msm"):
            f[:, i] = 1.0 - 0.130 * cosn
            u[:, i] = 0.0

        elif c in ("mf", "msqm", "msp", "mq", "mtm"):
            f[:, i] = 1.043 + 0.414 * cosn
            u[:, i] = np.radians(-23.7 * sinn + 2.7 * sin2n - 0.4 * sin3n)

        elif c in ("o1", "so3", "op2"):
            term1 = 0.189 * sinn - 0.0058 * sin2n
            term2 = 1.0 + 0.189 * cosn - 0.0058 * cos2n
            f[:, i] = np.hypot(term1, term2)
            u[:, i] = np.radians(10.8 * sinn - 1.3 * sin2n + 0.2 * sin3n)

        elif c in ("2q1", "q1", "rho1", "sigma1"):
            f[:, i] = np.hypot(1.0 + 0.188 * cosn, 0.188 * sinn)
            u[:, i] = np.arctan2(0.189 * sinn, 1.0 + 0.189 * cosn)

        elif c in ("k1", "sk3", "2sk5"):
            term1 = -0.1554 * sinn + 0.0029 * sin2n
            term2 = 1.0 + 0.1158 * cosn - 0.0029 * cos2n
            f[:, i] = np.hypot(term1, term2)
            u[:, i] = np.arctan2(term1, term2)

        elif c in ("j1", "theta1"):
            term1 = -0.227 * sinn
            term2 = 1.0 + 0.169 * cosn
            f[:, i] = np.hypot(term1, term2)
            u[:, i] = np.arctan2(term1, term2)

        elif c in ("oo1", "ups1"):
            term1 = -0.640 * sinn - 0.134 * sin2n
            term2 = 1.0 + 0.640 * cosn + 0.134 * cos2n
            f[:, i] = np.hypot(term1, term2)
            u[:, i] = np.arctan2(term1, term2)

        elif c in ("m2", "2n2", "mu2", "n2", "nu2", "lambda2", "ms4",
                    "eps2", "2sm6", "2sn6", "mp1", "mp3", "sn4"):
            term1 = -0.03731 * sinn + 0.00052 * sin2n
            term2 = 1.0 - 0.03731 * cosn + 0.00052 * cos2n
            f[:, i] = np.hypot(term1, term2)
            u[:, i] = np.arctan2(term1, term2)

        elif c in ("l2", "sl4"):
            term1 = (-0.25 * sin2p
                      - 0.11 * np.sin(2.0 * P - N)
                      - 0.04 * sinn)
            term2 = (1.0
                      - 0.25 * cos2p
                      - 0.11 * np.cos(2.0 * P - N)
                      - 0.04 * cosn)
            f[:, i] = np.hypot(term1, term2)
            u[:, i] = np.arctan2(term1, term2)

        elif c in ("k2", "sk4", "2sk6", "kp1"):
            term1 = -0.3108 * sinn - 0.0324 * sin2n
            term2 = 1.0 + 0.2852 * cosn + 0.0324 * cos2n
            f[:, i] = np.hypot(term1, term2)
            u[:, i] = np.arctan2(term1, term2)

        elif c in ("eta2", "zeta2"):
            term1 = -0.436 * sinn
            term2 = 1.0 + 0.436 * cosn
            f[:, i] = np.hypot(term1, term2)
            u[:, i] = np.arctan2(term1, term2)

        elif c in ("m1",):
            term1 = (-0.2294 * sinn
                      - 0.3594 * sin2p
                      - 0.0664 * np.sin(2.0 * P - N))
            term2 = (1.0
                      + 0.1722 * cosn
                      + 0.3594 * cos2p
                      + 0.0664 * np.cos(2.0 * P - N))
            f[:, i] = np.hypot(term1, term2)
            u[:, i] = np.arctan2(term1, term2)

        elif c in ("chi1",):
            term1 = -0.221 * sinn
            term2 = 1.0 + 0.221 * cosn
            f[:, i] = np.hypot(term1, term2)
            u[:, i] = np.arctan2(term1, term2)

        elif c in ("mt",):
            term1 = -0.203 * sinn - 0.040 * sin2n
            term2 = 1.0 + 0.203 * cosn + 0.040 * cos2n
            f[:, i] = np.hypot(term1, term2)
            u[:, i] = np.arctan2(term1, term2)

        elif c in ("m4", "mn4"):
            t1 = -0.03731 * sinn + 0.00052 * sin2n
            t2 = 1.0 - 0.03731 * cosn + 0.00052 * cos2n
            f_m2 = np.hypot(t1, t2)
            u_m2 = np.arctan2(t1, t2)
            f[:, i] = f_m2 ** 2
            u[:, i] = 2.0 * u_m2

        elif c in ("m6",):
            t1 = -0.03731 * sinn + 0.00052 * sin2n
            t2 = 1.0 - 0.03731 * cosn + 0.00052 * cos2n
            f_m2 = np.hypot(t1, t2)
            u_m2 = np.arctan2(t1, t2)
            f[:, i] = f_m2 ** 3
            u[:, i] = 3.0 * u_m2

        elif c in ("m8",):
            t1 = -0.03731 * sinn + 0.00052 * sin2n
            t2 = 1.0 - 0.03731 * cosn + 0.00052 * cos2n
            f_m2 = np.hypot(t1, t2)
            u_m2 = np.arctan2(t1, t2)
            f[:, i] = f_m2 ** 4
            u[:, i] = 4.0 * u_m2

        elif c in ("ssa", "sa"):
            f[:, i] = 1.0
            u[:, i] = 0.0

        else:
            f[:, i] = 1.0
            u[:, i] = 0.0

    return (u, f)


# ── Harmonic analysis ──────────────────────────────────────────────────

def harmonic_analysis(t_days, heights, constituents):
    """
    Solve for harmonic constants via least-squares.

    Parameters
    ----------
    t_days : np.ndarray
        Time in days since 1992-01-01T00:00:00
    heights : np.ndarray
        Observed tidal heights
    constituents : list of str
        Constituent names

    Returns
    -------
    hc : dict
        Mapping constituent name -> complex amplitude (real=cos, imag=sin)
    """
    t_days = np.ravel(t_days)
    heights = np.ravel(heights)
    nc = len(constituents)
    nt = len(t_days)

    mjd = t_days + _MJD_TIDE
    u, pf = nodal_corrections(mjd, constituents)

    M = []
    for k, c in enumerate(constituents):
        amp, ph, omega, alpha, species = _constituent_parameters(c)
        th = omega * t_days * 86400.0 + ph + u[:, k]
        M.append(pf[:, k] * np.cos(th))
        M.append(pf[:, k] * np.sin(th))
    M = np.transpose(M)

    p, _, _, _ = np.linalg.lstsq(M, heights, rcond=-1)

    hc = {}
    for k, c in enumerate(constituents):
        hc[c] = complex(p[2 * k], p[2 * k + 1])
    return hc


# ── Tidal prediction ──────────────────────────────────────────────────

def predict_tide(t_days, hc, constituents):
    """
    Predict tidal heights from harmonic constants.

    Parameters
    ----------
    t_days : np.ndarray
        Time in days since 1992-01-01T00:00:00
    hc : dict
        Complex harmonic constants {constituent: complex}
    constituents : list of str
        Constituent names

    Returns
    -------
    heights : np.ndarray
        Predicted tidal heights
    """
    t_days = np.ravel(t_days)
    nt = len(t_days)
    mjd = t_days + _MJD_TIDE

    u, pf = nodal_corrections(mjd, constituents)

    heights = np.zeros(nt)
    for k, c in enumerate(constituents):
        amp, ph, omega, alpha, species = _constituent_parameters(c)
        th = omega * t_days * 86400.0 + ph + u[:, k]
        z = hc[c]
        heights += z.real * np.cos(th) - z.imag * np.sin(th)
    return heights
