#!/usr/bin/env python3
"""
Tidal harmonic prediction engine.
Implements the Doodson/Schureman formalism for computing
equilibrium arguments, nodal corrections, and tidal predictions.
"""

import numpy as np

# Standard list of 60 tidal constituents
_STANDARD_60 = [
    "sa", "ssa", "mm", "msf", "mf", "mt", "alpha1", "2q1", "sigma1",
    "q1", "rho1", "o1", "tau1", "m1", "chi1", "pi1", "p1", "s1", "k1",
    "psi1", "phi1", "theta1", "j1", "oo1", "2n2", "mu2", "n2", "nu2",
    "m2a", "m2", "m2b", "lambda2", "l2", "t2", "s2", "r2", "k2", "eta2",
    "mns2", "2sm2", "m3", "mk3", "s3", "mn4", "m4", "ms4", "mk4", "s4",
    "s5", "m6", "s6", "s7", "s8", "m8", "mks2", "msqm", "mtm", "n4",
    "eps2", "z0",
]


def _normalize_angle(angle):
    """Normalize angle to [0, 360)."""
    return np.mod(angle, 360.0)


def mean_longitudes(mjd):
    """
    Compute astronomical mean longitudes using Cartwright's method.

    Parameters
    ----------
    mjd : float or array_like
        Modified Julian Date(s)

    Returns
    -------
    s, h, p, n, ps : ndarray
        Mean longitudes in degrees, normalized to [0, 360)
    """
    mjd = np.atleast_1d(np.asarray(mjd, dtype=float))
    T = mjd - 51544.4993
    s = _normalize_angle(218.3164 + 13.17639648 * T)
    h = _normalize_angle(280.4661 + 0.98564736 * T)
    p = _normalize_angle(83.3535 + 0.11140353 * T)
    n = _normalize_angle(125.0445 - 0.05295377 * T)
    ps = _normalize_angle(np.full_like(T, 282.8))
    return s, h, p, n, ps


def _build_coefficients():
    """Build full Doodson coefficient dictionary.

    Each entry maps constituent name -> [tau, s, h, p, n, pp, k] coefficients.
    """
    C = {}
    # Long-period species
    C['sa'] = [0.0, 0.0, 1.0, 0.0, 0.0, -1.0, 0.0]
    C['ssa'] = [0.0, 0.0, 2.0, 0.0, 0.0, 0.0, 0.0]
    C['mm'] = [0.0, 1.0, 0.0, -1.0, 0.0, 0.0, 0.0]
    C['msf'] = [0.0, 2.0, -2.0, 0.0, 0.0, 0.0, 0.0]
    C['mf'] = [0.0, 2.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    C['mt'] = [0.0, 3.0, 0.0, -1.0, 0.0, 0.0, 0.0]
    # Diurnal species
    C['alpha1'] = [1.0, -4.0, 2.0, 1.0, 0.0, 0.0, -1.0]
    C['2q1'] = [1.0, -3.0, 0.0, 2.0, 0.0, 0.0, -1.0]
    C['sigma1'] = [1.0, -3.0, 2.0, 0.0, 0.0, 0.0, -1.0]
    C['q1'] = [1.0, -2.0, 0.0, 1.0, 0.0, 0.0, -1.0]
    C['rho1'] = [1.0, -2.0, 2.0, -1.0, 0.0, 0.0, -1.0]
    C['o1'] = [1.0, -1.0, 0.0, 0.0, 0.0, 0.0, -1.0]
    C['tau1'] = [1.0, -1.0, 2.0, 0.0, 0.0, 0.0, 1.0]
    C['m1'] = [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0]
    C['chi1'] = [1.0, 0.0, 2.0, -1.0, 0.0, 0.0, 1.0]
    C['pi1'] = [1.0, 1.0, -3.0, 0.0, 0.0, 1.0, -1.0]
    C['p1'] = [1.0, 1.0, -2.0, 0.0, 0.0, 0.0, -1.0]
    C['s1'] = [1.0, 1.0, -1.0, 0.0, 0.0, 0.0, 1.0]  # OTIS convention
    C['k1'] = [1.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0]
    C['psi1'] = [1.0, 1.0, 1.0, 0.0, 0.0, -1.0, 1.0]
    C['phi1'] = [1.0, 1.0, 2.0, 0.0, 0.0, 0.0, 1.0]
    C['theta1'] = [1.0, 2.0, -2.0, 1.0, 0.0, 0.0, 1.0]
    C['j1'] = [1.0, 2.0, 0.0, -1.0, 0.0, 0.0, 1.0]
    C['oo1'] = [1.0, 3.0, 0.0, 0.0, 0.0, 0.0, 1.0]
    # Semi-diurnal species
    C['2n2'] = [2.0, -2.0, 0.0, 2.0, 0.0, 0.0, 0.0]
    C['mu2'] = [2.0, -2.0, 2.0, 0.0, 0.0, 0.0, 0.0]
    C['n2'] = [2.0, -1.0, 0.0, 1.0, 0.0, 0.0, 0.0]
    C['nu2'] = [2.0, -1.0, 2.0, -1.0, 0.0, 0.0, 0.0]
    C['m2a'] = [2.0, 0.0, -1.0, 0.0, 0.0, 1.0, 0.0]
    C['m2'] = [2.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    C['m2b'] = [2.0, 0.0, 1.0, 0.0, 0.0, -1.0, 0.0]
    C['lambda2'] = [2.0, 1.0, -2.0, 1.0, 0.0, 0.0, 2.0]
    C['l2'] = [2.0, 1.0, 0.0, -1.0, 0.0, 0.0, 2.0]
    C['t2'] = [2.0, 2.0, -3.0, 0.0, 0.0, 1.0, 0.0]
    C['s2'] = [2.0, 2.0, -2.0, 0.0, 0.0, 0.0, 0.0]
    C['r2'] = [2.0, 2.0, -1.0, 0.0, 0.0, -1.0, 2.0]
    C['k2'] = [2.0, 2.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    C['eta2'] = [2.0, 3.0, 0.0, -1.0, 0.0, 0.0, 0.0]
    C['mns2'] = [2.0, -3.0, 2.0, 1.0, 0.0, 0.0, 0.0]
    C['2sm2'] = [2.0, 4.0, -4.0, 0.0, 0.0, 0.0, 0.0]
    # Higher harmonics
    C['m3'] = [3.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    # mk3 = k1 + m2
    C['mk3'] = [a + b for a, b in zip(C['k1'], C['m2'])]
    C['s3'] = [3.0, 3.0, -3.0, 0.0, 0.0, 0.0, 0.0]
    # mn4 = n2 + m2
    C['mn4'] = [a + b for a, b in zip(C['n2'], C['m2'])]
    C['m4'] = [4.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    # ms4 = m2 + s2
    C['ms4'] = [a + b for a, b in zip(C['m2'], C['s2'])]
    # mk4 = m2 + k2
    C['mk4'] = [a + b for a, b in zip(C['m2'], C['k2'])]
    C['s4'] = [4.0, 4.0, -4.0, 0.0, 0.0, 0.0, 0.0]
    C['s5'] = [5.0, 5.0, -5.0, 0.0, 0.0, 0.0, 0.0]
    C['m6'] = [6.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    C['s6'] = [6.0, 6.0, -6.0, 0.0, 0.0, 0.0, 0.0]
    C['s7'] = [7.0, 7.0, -7.0, 0.0, 0.0, 0.0, 0.0]
    C['s8'] = [8.0, 8.0, -8.0, 0.0, 0.0, 0.0, 0.0]
    # Shallow water constituents
    C['m8'] = [8.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    # mks2 = m2 + k2 - s2
    C['mks2'] = [a + b - c for a, b, c in zip(C['m2'], C['k2'], C['s2'])]
    C['msqm'] = [0.0, 4.0, -2.0, 0.0, 0.0, 0.0, 0.0]
    C['mtm'] = [0.0, 3.0, 0.0, -1.0, 0.0, 0.0, 0.0]
    C['n4'] = [4.0, -2.0, 0.0, 2.0, 0.0, 0.0, 0.0]
    C['eps2'] = [2.0, -3.0, 2.0, 1.0, 0.0, 0.0, 0.0]
    C['z0'] = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    # Minor constituent variants
    # m1b: tau - p + k (M1 variant with -p)
    C['m1b'] = [1.0, 0.0, 0.0, -1.0, 0.0, 0.0, 1.0]
    # l2b: 2*tau + s + p
    C['l2b'] = [2.0, 1.0, 0.0, 1.0, 0.0, 0.0, 0.0]
    return C


# Global coefficient dictionary
_COEF = _build_coefficients()


def equilibrium_arguments(mjd, constituents, corrections='OTIS'):
    """
    Compute Doodson equilibrium arguments for given constituents.

    Parameters
    ----------
    mjd : float or array_like
        Modified Julian Date(s)
    constituents : list of str
        Constituent names
    corrections : str
        Correction type (default 'OTIS')

    Returns
    -------
    args : ndarray, shape (nt, nc)
        Equilibrium arguments in degrees
    """
    mjd = np.atleast_1d(np.asarray(mjd, dtype=float))
    nt = len(mjd)
    nc = len(constituents)

    s, h, p, n, ps = mean_longitudes(mjd)
    hour = 24.0 * np.mod(mjd, 1)
    tau = 15.0 * hour - s + h
    k = 90.0 + np.zeros(nt)

    fargs = np.column_stack([tau, s, h, p, n, ps, k])

    coef = np.zeros((7, nc))
    for i, c in enumerate(constituents):
        cname = c.lower()
        if cname in _COEF:
            coef[:, i] = _COEF[cname]
        else:
            raise ValueError(f"Unknown constituent: {c}")

    return np.dot(fargs, coef)


def _compute_otis_nodal(nt, n, p, M1='Ray'):
    """
    Compute OTIS nodal corrections for all 60 standard constituents.

    Returns f (amplitude factors) and u (phase angles in degrees).
    """
    dtr = np.pi / 180.0
    sinn = np.sin(n * dtr)
    cosn = np.cos(n * dtr)
    sin2n = np.sin(2.0 * n * dtr)
    cos2n = np.cos(2.0 * n * dtr)
    sin3n = np.sin(3.0 * n * dtr)

    f = np.ones((nt, 60))
    u = np.zeros((nt, 60))

    # ---- Nodal amplitude factors f ----
    # 0: Sa
    f[:, 0] = 1.0
    # 1: Ssa
    f[:, 1] = 1.0
    # 2: Mm
    f[:, 2] = 1.0 - 0.130 * cosn
    # 3: MSf
    f[:, 3] = 1.0
    # 4: Mf
    f[:, 4] = 1.043 + 0.414 * cosn
    # 5: Mt
    temp1 = (1.0 + 0.203 * cosn + 0.040 * cos2n)**2
    temp2 = (0.203 * sinn + 0.040 * sin2n)**2
    f[:, 5] = np.sqrt(temp1 + temp2)
    # 6: alpha1
    f[:, 6] = 1.0
    # 7: 2Q1
    f[:, 7] = np.sqrt((1.0 + 0.189 * cosn)**2 + (0.189 * sinn)**2)
    # 8: sigma1
    f[:, 8] = f[:, 7]
    # 9: q1
    f[:, 9] = f[:, 7]
    # 10: rho1
    f[:, 10] = f[:, 7]
    # 11: O1
    temp1 = (1.0 + 0.189 * cosn - 0.0058 * cos2n)**2
    temp2 = (0.189 * sinn - 0.0058 * sin2n)**2
    f[:, 11] = np.sqrt(temp1 + temp2)
    # 12: tau1
    f[:, 12] = 1.0
    # 13: M1 (Ray or Doodson coefficients)
    if M1 == 'Doodson':
        Mtmp1 = 2.0 * np.cos(p * dtr) + 0.4 * np.cos((p - n) * dtr)
        Mtmp2 = np.sin(p * dtr) + 0.2 * np.sin((p - n) * dtr)
    else:  # Ray
        Mtmp1 = 1.36 * np.cos(p * dtr) + 0.267 * np.cos((p - n) * dtr)
        Mtmp2 = 0.64 * np.sin(p * dtr) + 0.135 * np.sin((p - n) * dtr)
    f[:, 13] = np.sqrt(Mtmp1**2 + Mtmp2**2)
    # 14: chi1
    f[:, 14] = np.sqrt((1.0 + 0.221 * cosn)**2 + (0.221 * sinn)**2)
    # 15: pi1
    f[:, 15] = 1.0
    # 16: P1
    f[:, 16] = 1.0
    # 17: S1
    f[:, 17] = 1.0
    # 18: K1
    temp1 = (1.0 + 0.1158 * cosn - 0.0029 * cos2n)**2
    temp2 = (0.1554 * sinn - 0.0029 * sin2n)**2
    f[:, 18] = np.sqrt(temp1 + temp2)
    # 19: psi1
    f[:, 19] = 1.0
    # 20: phi1
    f[:, 20] = 1.0
    # 21: theta1
    f[:, 21] = 1.0
    # 22: J1
    f[:, 22] = np.sqrt((1.0 + 0.169 * cosn)**2 + (0.227 * sinn)**2)
    # 23: OO1
    temp1 = (1.0 + 0.640 * cosn + 0.134 * cos2n)**2
    temp2 = (0.640 * sinn + 0.134 * sin2n)**2
    f[:, 23] = np.sqrt(temp1 + temp2)
    # 24: 2N2
    temp1 = (1.0 - 0.03731 * cosn + 0.00052 * cos2n)**2
    temp2 = (0.03731 * sinn - 0.00052 * sin2n)**2
    f[:, 24] = np.sqrt(temp1 + temp2)
    # 25-27: mu2, N2, nu2 (same as 2N2)
    f[:, 25] = f[:, 24]
    f[:, 26] = f[:, 24]
    f[:, 27] = f[:, 24]
    # 28: M2a
    f[:, 28] = 1.0
    # 29: M2
    f[:, 29] = f[:, 24]
    # 30: M2b
    f[:, 30] = 1.0
    # 31: lambda2
    f[:, 31] = 1.0
    # 32: L2
    Ltmp1 = 1.0 - 0.25 * np.cos(2 * p * dtr) - \
        0.11 * np.cos((2.0 * p - n) * dtr) - 0.04 * cosn
    Ltmp2 = 0.25 * np.sin(2 * p * dtr) + \
        0.11 * np.sin((2.0 * p - n) * dtr) + 0.04 * sinn
    f[:, 32] = np.sqrt(Ltmp1**2 + Ltmp2**2)
    # 33: T2
    f[:, 33] = 1.0
    # 34: S2
    f[:, 34] = 1.0
    # 35: R2
    f[:, 35] = 1.0
    # 36: K2
    temp1 = (1.0 + 0.2852 * cosn + 0.0324 * cos2n)**2
    temp2 = (0.3108 * sinn + 0.0324 * sin2n)**2
    f[:, 36] = np.sqrt(temp1 + temp2)
    # 37: eta2
    f[:, 37] = np.sqrt((1.0 + 0.436 * cosn)**2 + (0.436 * sinn)**2)
    # 38: MNS2
    f[:, 38] = f[:, 29]**2
    # 39: 2SM2
    f[:, 39] = f[:, 29]
    # 40: M3 (OTIS uses 1.0)
    f[:, 40] = 1.0
    # 41: MK3
    f[:, 41] = f[:, 18] * f[:, 29]
    # 42: S3
    f[:, 42] = 1.0
    # 43: MN4
    f[:, 43] = f[:, 29]**2
    # 44: M4
    f[:, 44] = f[:, 43]
    # 45: MS4
    f[:, 45] = f[:, 29]
    # 46: MK4
    f[:, 46] = f[:, 29] * f[:, 36]
    # 47: S4
    f[:, 47] = 1.0
    # 48: S5
    f[:, 48] = 1.0
    # 49: M6
    f[:, 49] = f[:, 29]**3
    # 50: S6
    f[:, 50] = 1.0
    # 51: S7
    f[:, 51] = 1.0
    # 52: S8
    f[:, 52] = 1.0
    # 53: m8
    f[:, 53] = f[:, 29]**4
    # 54: mks2
    f[:, 54] = f[:, 29] * f[:, 36]
    # 55: msqm
    f[:, 55] = f[:, 4]
    # 56: mtm
    f[:, 56] = f[:, 4]
    # 57: n4
    f[:, 57] = f[:, 29]**2
    # 58: eps2
    f[:, 58] = f[:, 29]
    # 59: Z0
    f[:, 59] = 1.0

    # ---- Nodal phase angles u (degrees) ----
    # 0: Sa
    u[:, 0] = 0.0
    # 1: Ssa
    u[:, 1] = 0.0
    # 2: Mm
    u[:, 2] = 0.0
    # 3: MSf
    u[:, 3] = 0.0
    # 4: Mf
    u[:, 4] = -23.7 * sinn + 2.7 * sin2n - 0.4 * sin3n
    # 5: Mt
    temp1 = -(0.203 * sinn + 0.040 * sin2n)
    temp2 = (1.0 + 0.203 * cosn + 0.040 * cos2n)
    u[:, 5] = np.arctan(temp1 / temp2) / dtr
    # 6: alpha1
    u[:, 6] = 0.0
    # 7: 2Q1
    u[:, 7] = np.arctan(0.189 * sinn / (1.0 + 0.189 * cosn)) / dtr
    # 8: sigma1
    u[:, 8] = u[:, 7]
    # 9: q1
    u[:, 9] = u[:, 7]
    # 10: rho1
    u[:, 10] = u[:, 7]
    # 11: O1
    u[:, 11] = 10.8 * sinn - 1.3 * sin2n + 0.2 * sin3n
    # 12: tau1
    u[:, 12] = 0.0
    # 13: M1
    u[:, 13] = np.arctan2(Mtmp2, Mtmp1) / dtr
    # 14: chi1
    u[:, 14] = np.arctan(-0.221 * sinn / (1.0 + 0.221 * cosn)) / dtr
    # 15: pi1
    u[:, 15] = 0.0
    # 16: P1
    u[:, 16] = 0.0
    # 17: S1
    u[:, 17] = 0.0
    # 18: K1
    temp1 = (-0.1554 * sinn + 0.0029 * sin2n)
    temp2 = (1.0 + 0.1158 * cosn - 0.0029 * cos2n)
    u[:, 18] = np.arctan(temp1 / temp2) / dtr
    # 19: psi1
    u[:, 19] = 0.0
    # 20: phi1
    u[:, 20] = 0.0
    # 21: theta1
    u[:, 21] = 0.0
    # 22: J1
    u[:, 22] = np.arctan(-0.227 * sinn / (1.0 + 0.169 * cosn)) / dtr
    # 23: OO1
    temp1 = -(0.640 * sinn + 0.134 * sin2n)
    temp2 = (1.0 + 0.640 * cosn + 0.134 * cos2n)
    u[:, 23] = np.arctan(temp1 / temp2) / dtr
    # 24: 2N2
    temp1 = (-0.03731 * sinn + 0.00052 * sin2n)
    temp2 = (1.0 - 0.03731 * cosn + 0.00052 * cos2n)
    u[:, 24] = np.arctan(temp1 / temp2) / dtr
    # 25-27: mu2, N2, nu2
    u[:, 25] = u[:, 24]
    u[:, 26] = u[:, 24]
    u[:, 27] = u[:, 24]
    # 28: M2a
    u[:, 28] = 0.0
    # 29: M2
    u[:, 29] = u[:, 24]
    # 30: M2b
    u[:, 30] = 0.0
    # 31: lambda2
    u[:, 31] = 0.0
    # 32: L2
    u[:, 32] = np.arctan(-Ltmp2 / Ltmp1) / dtr
    # 33: T2
    u[:, 33] = 0.0
    # 34: S2
    u[:, 34] = 0.0
    # 35: R2
    u[:, 35] = 0.0
    # 36: K2
    temp1 = -(0.3108 * sinn + 0.0324 * sin2n)
    temp2 = (1.0 + 0.2852 * cosn + 0.0324 * cos2n)
    u[:, 36] = np.arctan(temp1 / temp2) / dtr
    # 37: eta2
    u[:, 37] = np.arctan(-0.436 * sinn / (1.0 + 0.436 * cosn)) / dtr
    # 38: MNS2
    u[:, 38] = u[:, 29] * 2.0
    # 39: 2SM2
    u[:, 39] = -u[:, 29]
    # 40: M3
    u[:, 40] = 1.50 * u[:, 29]
    # 41: MK3
    u[:, 41] = u[:, 29] + u[:, 18]
    # 42: S3
    u[:, 42] = 0.0
    # 43: MN4
    u[:, 43] = 2.0 * u[:, 29]
    # 44: M4
    u[:, 44] = u[:, 43]
    # 45: MS4
    u[:, 45] = u[:, 29]
    # 46: MK4
    u[:, 46] = u[:, 29] + u[:, 36]
    # 47: S4
    u[:, 47] = 0.0
    # 48: S5
    u[:, 48] = 0.0
    # 49: M6
    u[:, 49] = 3.0 * u[:, 29]
    # 50: S6
    u[:, 50] = 0.0
    # 51: S7
    u[:, 51] = 0.0
    # 52: S8
    u[:, 52] = 0.0
    # 53: m8
    u[:, 53] = 4.0 * u[:, 29]
    # 54: mks2
    u[:, 54] = u[:, 29] + u[:, 36]
    # 55: msqm
    u[:, 55] = u[:, 4]
    # 56: mtm
    u[:, 56] = u[:, 4]
    # 57: n4
    u[:, 57] = 2.0 * u[:, 29]
    # 58: eps2
    u[:, 58] = u[:, 29]
    # 59: Z0
    u[:, 59] = 0.0

    return f, u


def nodal_corrections(mjd, constituents, corrections='OTIS', M1='Ray'):
    """
    Compute nodal modulation factors.

    Parameters
    ----------
    mjd : float or array_like
        Modified Julian Date(s)
    constituents : list of str
        Constituent names
    corrections : str
        Correction type (default 'OTIS')
    M1 : str
        M1 coefficient source ('Ray' or 'Doodson')

    Returns
    -------
    pu : ndarray, shape (nt, nc)
        Nodal phase angle corrections in radians
    pf : ndarray, shape (nt, nc)
        Nodal amplitude factors (dimensionless)
    """
    mjd = np.atleast_1d(np.asarray(mjd, dtype=float))
    nt = len(mjd)
    nc = len(constituents)

    s, h, p, n, ps = mean_longitudes(mjd)
    dtr = np.pi / 180.0

    # Compute full 60-constituent corrections
    f_all, u_all = _compute_otis_nodal(nt, n, p, M1)

    # Map to minor constituent corrections
    # m1b uses same correction as M1, l2b uses same correction as L2
    _MINOR_MAP = {
        'm1b': 13,   # same as M1
        'l2b': 32,   # same as L2
    }

    pf = np.zeros((nt, nc))
    pu = np.zeros((nt, nc))

    for i, c in enumerate(constituents):
        cname = c.lower()
        if cname in _STANDARD_60:
            idx = _STANDARD_60.index(cname)
            pf[:, i] = f_all[:, idx]
            pu[:, i] = u_all[:, idx] * dtr
        elif cname in _MINOR_MAP:
            idx = _MINOR_MAP[cname]
            pf[:, i] = f_all[:, idx]
            pu[:, i] = u_all[:, idx] * dtr
        else:
            # Default: trivial corrections
            pf[:, i] = 1.0
            pu[:, i] = 0.0

    return pu, pf


def predict_tide(times_mjd, hc_real, hc_imag, constituents, corrections='OTIS'):
    """
    Predict tidal elevation from complex harmonic constants.

    Parameters
    ----------
    times_mjd : float or array_like
        Modified Julian Date(s)
    hc_real : array_like
        Real parts of harmonic constants (length nc)
    hc_imag : array_like
        Imaginary parts of harmonic constants (length nc)
    constituents : list of str
        Constituent names
    corrections : str
        Correction type (default 'OTIS')

    Returns
    -------
    pred : ndarray, shape (nt,)
        Predicted tidal elevation
    """
    times_mjd = np.atleast_1d(np.asarray(times_mjd, dtype=float))
    hc_real = np.asarray(hc_real, dtype=float)
    hc_imag = np.asarray(hc_imag, dtype=float)

    args = equilibrium_arguments(times_mjd, constituents, corrections)
    pu, pf = nodal_corrections(times_mjd, constituents, corrections)

    theta = np.radians(args) + pu
    pred = np.sum(
        hc_real[None, :] * pf * np.cos(theta)
        - hc_imag[None, :] * pf * np.sin(theta),
        axis=1
    )
    return pred


def infer_minor(times_mjd, hc_real, hc_imag, major_constituents, corrections='OTIS'):
    """
    Infer tidal contributions from 18 minor constituents via linear admittance.

    Parameters
    ----------
    times_mjd : float or array_like
        Modified Julian Date(s)
    hc_real : array_like
        Real parts of major harmonic constants
    hc_imag : array_like
        Imaginary parts of major harmonic constants
    major_constituents : list of str
        Major constituent names
    corrections : str
        Correction type (default 'OTIS')

    Returns
    -------
    pred : ndarray, shape (nt,)
        Inferred minor tide elevations
    """
    times_mjd = np.atleast_1d(np.asarray(times_mjd, dtype=float))
    hc_real = np.asarray(hc_real, dtype=float)
    hc_imag = np.asarray(hc_imag, dtype=float)
    nt = len(times_mjd)

    major = [c.lower() for c in major_constituents]

    # Required major constituents for inference
    required = ['q1', 'o1', 'p1', 'k1', 'n2', 'm2', 's2', 'k2']
    nz = sum(c in major for c in required)
    if nz < 6:
        return np.zeros(nt)

    # Build complex harmonic constants for required majors
    major_hc = {}
    for c in required:
        if c in major:
            idx = major.index(c)
            major_hc[c] = complex(hc_real[idx], hc_imag[idx])
        else:
            major_hc[c] = 0.0 + 0.0j

    # Minor constituents and their admittance relationships
    minor_list = [
        "2q1", "sigma1", "rho1", "m1b", "m1", "chi1", "pi1", "phi1",
        "theta1", "j1", "oo1", "2n2", "mu2", "nu2", "lambda2",
        "l2", "l2b", "t2",
    ]

    # Admittance coefficients (Egbert and Erofeeva, 2002)
    minor_hc = {}
    minor_hc['2q1'] = 0.263 * major_hc['q1'] - 0.0252 * major_hc['o1']
    minor_hc['sigma1'] = 0.297 * major_hc['q1'] - 0.0264 * major_hc['o1']
    minor_hc['rho1'] = 0.164 * major_hc['q1'] + 0.0048 * major_hc['o1']
    minor_hc['m1b'] = 0.0140 * major_hc['o1'] + 0.0101 * major_hc['k1']
    minor_hc['m1'] = 0.0389 * major_hc['o1'] + 0.0282 * major_hc['k1']
    minor_hc['chi1'] = 0.0064 * major_hc['o1'] + 0.0060 * major_hc['k1']
    minor_hc['pi1'] = 0.0030 * major_hc['o1'] + 0.0171 * major_hc['k1']
    minor_hc['phi1'] = -0.0015 * major_hc['o1'] + 0.0152 * major_hc['k1']
    minor_hc['theta1'] = -0.0065 * major_hc['o1'] + 0.0155 * major_hc['k1']
    minor_hc['j1'] = -0.0389 * major_hc['o1'] + 0.0836 * major_hc['k1']
    minor_hc['oo1'] = -0.0431 * major_hc['o1'] + 0.0613 * major_hc['k1']
    minor_hc['2n2'] = 0.264 * major_hc['n2'] - 0.0253 * major_hc['m2']
    minor_hc['mu2'] = 0.298 * major_hc['n2'] - 0.0264 * major_hc['m2']
    minor_hc['nu2'] = 0.165 * major_hc['n2'] + 0.00487 * major_hc['m2']
    minor_hc['lambda2'] = 0.0040 * major_hc['m2'] + 0.0074 * major_hc['s2']
    minor_hc['l2'] = 0.0131 * major_hc['m2'] + 0.0326 * major_hc['s2']
    minor_hc['l2b'] = 0.0033 * major_hc['m2'] + 0.0082 * major_hc['s2']
    minor_hc['t2'] = 0.0585 * major_hc['s2']

    # Only infer constituents not already in the major list
    active = [c for c in minor_list if c not in major]

    if not active:
        return np.zeros(nt)

    # Compute arguments and corrections for active minor constituents
    args = equilibrium_arguments(times_mjd, active, corrections)
    pu, pf = nodal_corrections(times_mjd, active, corrections)

    # Harmonic synthesis for minor constituents
    theta = np.radians(args) + pu
    pred = np.zeros(nt)
    for i, c in enumerate(active):
        hc = minor_hc[c]
        pred += hc.real * pf[:, i] * np.cos(theta[:, i]) \
            - hc.imag * pf[:, i] * np.sin(theta[:, i])

    return pred
