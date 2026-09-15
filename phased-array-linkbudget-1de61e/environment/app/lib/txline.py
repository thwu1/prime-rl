"""Transmission line and impedance matching utilities.

All electrical lengths are in DEGREES.
"""

import math

C_LIGHT = 299792458.0  # m/s


def input_impedance(z_load, z0, length_deg):
    """Input impedance of a lossless transmission line.

    Parameters
    ----------
    z_load : complex
        Load impedance in ohms.
    z0 : float
        Characteristic impedance in ohms (real).
    length_deg : float
        Electrical length in degrees.

    Returns
    -------
    complex  -- input impedance in ohms
    """
    beta_l = math.radians(length_deg)
    tan_bl = math.tan(beta_l)
    return z0 * (z_load + 1j * z0 * tan_bl) / (z0 + 1j * z_load * tan_bl)


def reflection_coeff(z_in, z0):
    """Complex voltage reflection coefficient."""
    return (z_in - z0) / (z_in + z0)


def reflection_coeff_mag(z_in, z0):
    """Magnitude of the voltage reflection coefficient."""
    return abs(reflection_coeff(z_in, z0))


def vswr(gamma_mag):
    """Voltage standing wave ratio from |Gamma|."""
    if gamma_mag >= 1.0:
        return float("inf")
    return (1.0 + gamma_mag) / (1.0 - gamma_mag)


def mismatch_loss_db(gamma_mag):
    """Mismatch loss in dB (non-negative)."""
    if gamma_mag >= 1.0:
        return float("inf")
    return -10.0 * math.log10(1.0 - gamma_mag ** 2)


def fspl_db(freq_hz, distance_m):
    """Free-space path loss in dB."""
    return 20.0 * math.log10(
        4.0 * math.pi * distance_m * freq_hz / C_LIGHT
    )
