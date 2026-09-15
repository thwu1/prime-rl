"""
Partial reference implementation from the RefET library (WSWUP).
Selected calculation functions for the ASCE-EWRI 2005 standardized
reference evapotranspiration equation.

This is a partial extract — some functions have been removed.
The original library uses NumPy arrays; this extract uses scalar math.

Source: https://github.com/WSWUP/RefET

"""

import math


def air_pressure(elev, method='asce'):
    """Mean atmospheric pressure [kPa] from elevation [m].

    ASCE-EWRI (2005) Eq. 3 and RefET software implementation.
    """
    base = (293.0 - 0.0065 * elev) / 293.0
    if method == 'asce':
        return 101.3 * base ** 5.26
    elif method == 'refet':
        return 101.3 * base ** (9.8 / (0.0065 * 286.9))
    else:
        raise ValueError(f'Unsupported method: {method}')


def precipitable_water(pair, ea):
    """Precipitable water in the atmosphere [mm] (Eq. D.3).

    Used in the full clear-sky solar radiation model (Appendix D).
    W = P * 0.14 * ea + 2.1
    """
    return pair * 0.14 * ea + 2.1


def doy_fraction(doy):
    """DOY fraction [radians] (Eq. 50)."""
    return doy * (2.0 * math.pi / 365.0)


def dr(doy):
    """Inverse square of earth-sun distance (Eq. 50)."""
    return 1.0 + 0.033 * math.cos(doy_fraction(doy))


def seasonal_correction(doy):
    """Seasonal correction for solar time [hours] (Eqs. 57 & 58)."""
    b = 2.0 * math.pi * (doy - 81) / 364.0
    return 0.1645 * math.sin(2.0 * b) - 0.1255 * math.cos(b) - 0.0250 * math.sin(b)


def solar_time_rad(lon, time_mid, sc):
    """Solar time (noon = 0) [hours] (Eq. 55). lon in radians."""
    return time_mid + (lon * 24.0 / (2.0 * math.pi)) + sc - 12.0


def solar_hour_angle(solar_time):
    """Solar hour angle [radians], wrapped to [-pi, pi]."""
    omega = (2.0 * math.pi / 24.0) * solar_time
    return ((omega + math.pi) % (2.0 * math.pi)) - math.pi


def sunset_hour_angle(lat, delta):
    """Sunset hour angle [radians] (Eq. 59). Clipped to [0, pi]."""
    x = -math.tan(lat) * math.tan(delta)
    return math.acos(max(min(x, 1.0), -1.0))


def wind_height_adjust(uz, zw):
    """Wind speed adjusted to 2m height [m s-1] (Eq. 33)."""
    return uz * 4.87 / math.log(67.8 * zw - 5.42)


# -------------------------------------------------------------------------
# The following functions are available in the full library but have been
# removed from this extract:
#   - sat_vapor_pressure, es_slope, vpd, actual_vapor_pressure
#   - specific_humidity
#   - declination (ASCE and RefET variants differ)
#   - ra_daily, ra_hourly (extraterrestrial radiation)
#   - rso_simple, rso_daily (full Appendix D model), rso_hourly
#   - fcd_daily, fcd_hourly (cloudiness fraction)
#   - rnl_daily, rnl_hourly (net long-wave radiation)
#   - rn_daily, rn_hourly (net radiation)
#   - etsz (standardized reference ET equation)
#
# Refer to the ASCE-EWRI (2005) specification for equation details.
# -------------------------------------------------------------------------
