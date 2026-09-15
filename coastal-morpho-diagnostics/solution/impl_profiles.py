"""
Profile computations — delegates to compiled Fortran sedtrans module.
"""

import numpy as np


import sedtrans as _fort


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
    ws = _fort.fall_velocity(D50, temperature)
    return float(ws)


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
    ws = fall_velocity_vanrijn(D50, temperature)
    A = 0.51 * ws ** 0.44  # Dean scale parameter

    x = np.asarray(x, dtype=float)
    z = np.empty_like(x)

    offshore = x >= 0
    landward = ~offshore

    # Standard Dean equilibrium: z = z_offset - A * x^(2/3)
    z[offshore] = z_offset - A * np.power(x[offshore], 2.0 / 3.0)

    # Linear dry beach slope
    z[landward] = z_offset + beta_dry * np.abs(x[landward])

    return z
