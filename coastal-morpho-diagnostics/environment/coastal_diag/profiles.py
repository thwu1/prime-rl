"""
Profile computations — delegates to compiled Fortran sedtrans module.
Ported from XBeach diagnostic test framework (reference: /app/reference/xbeach_bathy.py).
"""

import numpy as np


try:
    import sedtrans as _fort
    _HAS_FORTRAN = True
except ImportError:
    _HAS_FORTRAN = False


def fall_velocity_vanrijn(D50, temperature=15.0):
    """Compute sediment fall velocity (m/s) using Van Rijn (2007).

    Parameters
    ----------
    D50 : float
        Median grain diameter in metres.
    temperature : float
        Water temperature in degrees Celsius (default 15).

    Returns
    -------
    float
        Fall velocity in m/s.
    """
    if not _HAS_FORTRAN:
        raise ImportError(
            "Compiled Fortran module 'sedtrans' not found. "
            "Build /app/fortran/sedtrans.f90 with f2py first."
        )
    ws = np.empty(1, dtype=np.float64)
    _fort.fall_velocity(D50, temperature, ws)
    return float(ws[0])


def dean_profile(x, D50, temperature=15.0, beta_dry=0.1, z_offset=0.0):
    """Generate a Dean equilibrium beach profile.

    Parameters
    ----------
    x : array_like
        Cross-shore positions in metres. x >= 0 is offshore, x < 0 is landward.
    D50 : float
        Median grain diameter in metres.
    temperature : float
        Water temperature in C (default 15).
    beta_dry : float
        Linear slope of the dry beach / dune (default 0.1).
    z_offset : float
        Vertical datum shift applied to entire profile.

    Returns
    -------
    numpy.ndarray
        Elevations (m) at each x position.
    """
    if not _HAS_FORTRAN:
        raise ImportError(
            "Compiled Fortran module 'sedtrans' not found."
        )

    ws = fall_velocity_vanrijn(D50, temperature)
    A = 0.51 * ws ** 0.44  # Dean scale parameter

    x = np.asarray(x, dtype=float)
    z = np.empty_like(x)

    offshore = x >= 0
    landward = ~offshore

    # Delegate offshore profile to Fortran equilibrium_profile
    x_off = np.ascontiguousarray(x[offshore], dtype=np.float64)
    if len(x_off) > 0:
        z_off = np.empty_like(x_off)
        _fort.equilibrium_profile(x_off, A, z_offset, z_off, len(x_off))
        z[offshore] = z_off

    # Linear dry beach slope
    z[landward] = z_offset + beta_dry * np.abs(x[landward])

    return z
