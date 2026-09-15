#!/usr/bin/env python3

"""Write the complete digitize.py module to /app/."""

code = r'''"""Analog-to-digital filter conversion and evaluation.

Provides bilinear transform, SOS decomposition, and minimum-order search.
Uses only numpy and the elliptic_filter module (no scipy).
"""

import os
import sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from elliptic_filter import design_elliptic_lowpass


def bilinear_zpk(z, p, k, fs):
    """Convert analog zpk to digital via bilinear transform.

    Parameters
    ----------
    z : array_like
        Analog zeros.
    p : array_like
        Analog poles.
    k : float
        Analog gain.
    fs : float
        Sample rate in Hz.

    Returns
    -------
    z_d : ndarray
        Digital zeros.
    p_d : ndarray
        Digital poles.
    k_d : float
        Digital gain.
    """
    z = np.atleast_1d(np.asarray(z, dtype=complex))
    p = np.atleast_1d(np.asarray(p, dtype=complex))
    fs2 = 2.0 * fs

    # Bilinear mapping: s -> z via z = (1 + s/(2fs)) / (1 - s/(2fs))
    z_d = (fs2 + z) / (fs2 - z)
    p_d = (fs2 + p) / (fs2 - p)

    # Extra zeros at Nyquist (z = -1) for degree matching
    z_d = np.append(z_d, -np.ones(len(p) - len(z)))

    # Gain compensation
    k_d = float(k * np.real(np.prod(fs2 - z) / np.prod(fs2 - p)))

    return z_d, p_d, k_d


def _eval_digital_response(z, p, k, w):
    """Evaluate H(e^jw) from zpk at digital frequencies w (radians)."""
    z = np.atleast_1d(np.asarray(z, dtype=complex))
    p = np.atleast_1d(np.asarray(p, dtype=complex))
    ejw = np.exp(1j * np.asarray(w, dtype=float))
    h = np.ones(len(ejw), dtype=complex) * k
    for zi in z:
        h *= (ejw - zi)
    for pi in p:
        h /= (ejw - pi)
    return h


def zpk_to_sos(z, p, k):
    """Decompose digital zpk into second-order sections.

    Parameters
    ----------
    z : array_like
        Digital zeros.
    p : array_like
        Digital poles.
    k : float
        Digital gain.

    Returns
    -------
    sos : ndarray, shape (L, 6)
        SOS coefficients [b0, b1, b2, 1, a1, a2] per section.
    """
    z = np.atleast_1d(np.asarray(z, dtype=complex)).copy()
    p = np.atleast_1d(np.asarray(p, dtype=complex)).copy()

    def _group_conjugates(arr):
        """Group array elements into conjugate pairs and lone reals."""
        remaining = list(arr)
        groups = []
        while remaining:
            x = remaining.pop(0)
            if abs(x.imag) < 1e-12:
                groups.append([complex(x.real, 0)])
            else:
                best_idx = None
                best_dist = np.inf
                for i, xi in enumerate(remaining):
                    d = abs(xi - np.conj(x))
                    if d < best_dist:
                        best_dist = d
                        best_idx = i
                if best_idx is not None and best_dist < 1e-8:
                    remaining.pop(best_idx)
                groups.append([x, np.conj(x)])
        return groups

    pole_groups = _group_conjugates(p)
    zero_groups = _group_conjugates(z)

    # Sort pole groups by increasing maximum pole magnitude
    pole_groups.sort(key=lambda g: max(abs(x) for x in g))

    # Pair each pole group with nearest zero group by angular frequency
    z_avail = list(zero_groups)
    sections = []

    for pg in pole_groups:
        p_ang = np.mean([abs(np.angle(x)) for x in pg])
        if z_avail:
            best_i = 0
            best_d = abs(np.mean([abs(np.angle(x)) for x in z_avail[0]]) - p_ang)
            for i in range(1, len(z_avail)):
                d = abs(np.mean([abs(np.angle(x)) for x in z_avail[i]]) - p_ang)
                if d < best_d:
                    best_d = d
                    best_i = i
            zg = z_avail.pop(best_i)
        else:
            zg = []
        sections.append((pg, zg))

    # Build SOS coefficient matrix
    sos = np.zeros((len(sections), 6))

    for i, (pg, zg) in enumerate(sections):
        # Denominator coefficients: (1 + a1*z^{-1} + a2*z^{-2})
        if len(pg) == 2:
            a = np.array([1.0, -2.0 * pg[0].real, abs(pg[0]) ** 2])
        else:
            a = np.array([1.0, -pg[0].real, 0.0])

        # Numerator coefficients: (b0 + b1*z^{-1} + b2*z^{-2})
        if len(zg) == 2:
            b = np.array([1.0, -2.0 * zg[0].real, abs(zg[0]) ** 2])
        elif len(zg) == 1:
            b = np.array([1.0, -zg[0].real, 0.0])
        else:
            b = np.array([1.0, 0.0, 0.0])

        sos[i] = np.concatenate([b, a])

    # Apply overall gain to first section
    sos[0, :3] *= k

    return sos


def min_order_for_spec(passband_hz, stopband_hz, ripple_db, atten_db, fs):
    """Find minimum elliptic filter order meeting digital specifications.

    Prewarp band-edge frequencies, iterate orders 2-15, design analog
    prototype, digitize via bilinear transform, and verify digital
    frequency response.

    Parameters
    ----------
    passband_hz : float
        Passband edge frequency in Hz.
    stopband_hz : float
        Stopband edge frequency in Hz.
    ripple_db : float
        Maximum passband ripple in dB.
    atten_db : float
        Minimum stopband attenuation in dB.
    fs : float
        Sample rate in Hz.

    Returns
    -------
    order : int
        Minimum filter order (2-15).
    achieved_ripple_db : float
        Actual maximum passband deviation in dB.
    achieved_atten_db : float
        Actual minimum stopband attenuation in dB.
    """
    # Prewarp digital frequencies to analog domain
    wp = 2 * fs * np.tan(np.pi * passband_hz / fs)
    ws = 2 * fs * np.tan(np.pi * stopband_hz / fs)

    for N in range(2, 16):
        try:
            # Design analog prototype (passband at 1 rad/s)
            z_a, p_a, k_a = design_elliptic_lowpass(N, ripple_db, atten_db)

            # Frequency-scale to prewarped passband
            z_a_scaled = z_a * wp
            p_a_scaled = p_a * wp
            k_a_scaled = k_a * wp ** (len(p_a) - len(z_a))

            # Bilinear transform to digital
            z_d, p_d, k_d = bilinear_zpk(z_a_scaled, p_a_scaled, k_a_scaled, fs)

            # Evaluate passband frequency response
            f_pb = np.linspace(0.01 * passband_hz, passband_hz, 400)
            w_pb = 2 * np.pi * f_pb / fs
            h_pb = _eval_digital_response(z_d, p_d, k_d, w_pb)
            pb_mag_db = 20 * np.log10(np.abs(h_pb) + 1e-30)
            max_ripple = -np.min(pb_mag_db)

            # Evaluate stopband frequency response
            f_sb = np.linspace(stopband_hz, fs / 2 * 0.98, 400)
            w_sb = 2 * np.pi * f_sb / fs
            h_sb = _eval_digital_response(z_d, p_d, k_d, w_sb)
            sb_mag_db = 20 * np.log10(np.abs(h_sb) + 1e-30)
            min_atten = -np.max(sb_mag_db)

            if max_ripple <= ripple_db + 0.01 and min_atten >= atten_db - 0.1:
                return N, float(max_ripple), float(min_atten)
        except Exception:
            continue

    return 15, 0.0, 0.0
'''

with open("/app/digitize.py", "w") as f:
    f.write(code)

print("digitize.py written to /app/")
