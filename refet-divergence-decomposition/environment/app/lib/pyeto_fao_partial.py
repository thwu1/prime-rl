"""
Partial reference implementation from the PyETo library (FAO-56).
These functions implement the FAO-56 Penman-Monteith method, which shares
the same physical basis as ASCE-EWRI 2005 but uses different constants
and coefficient choices in some equations.

Source: https://github.com/woodcrafty/PyETo

"""

import math

# FAO-56 solar constant [MJ m-2 min-1]
SOLAR_CONSTANT = 0.0820

# Stefan-Boltzmann constant [MJ K-4 m-2 day-1]
STEFAN_BOLTZMANN_CONSTANT = 4.903e-9


def atm_pressure(altitude):
    """Atmospheric pressure [kPa] from altitude [m] (FAO Eq. 7).

    Simplification of ideal gas law assuming 20C standard atmosphere.
    """
    tmp = (293.0 - (0.0065 * altitude)) / 293.0
    return math.pow(tmp, 5.26) * 101.3


def sol_dec(day_of_year):
    """Solar declination [radians] (FAO Eq. 24)."""
    return 0.409 * math.sin(((2.0 * math.pi / 365.0) * day_of_year - 1.39))


def inv_rel_dist_earth_sun(day_of_year):
    """Inverse relative distance earth-sun (FAO Eq. 23)."""
    return 1 + (0.033 * math.cos((2.0 * math.pi / 365.0) * day_of_year))


def sunset_hour_angle(latitude, sol_dec):
    """Sunset hour angle [radians] (FAO Eq. 25)."""
    cos_sha = -math.tan(latitude) * math.tan(sol_dec)
    return math.acos(min(max(cos_sha, -1.0), 1.0))


def et_rad(latitude, sol_dec, sha, ird):
    """Daily extraterrestrial radiation [MJ m-2 day-1] (FAO Eq. 21).

    Uses SOLAR_CONSTANT = 0.0820 MJ m-2 min-1.
    """
    tmp1 = (24.0 * 60.0) / math.pi
    tmp2 = sha * math.sin(latitude) * math.sin(sol_dec)
    tmp3 = math.cos(latitude) * math.cos(sol_dec) * math.sin(sha)
    return tmp1 * SOLAR_CONSTANT * ird * (tmp2 + tmp3)


def cs_rad(altitude, et_rad):
    """Clear sky radiation [MJ m-2 day-1] (FAO Eq. 37).

    Simplified model: (0.00002 * altitude + 0.75) * Ra
    """
    return (0.00002 * altitude + 0.75) * et_rad


def delta_svp(t):
    """Slope of saturation vapour pressure curve [kPa degC-1] (FAO Eq. 13).

    delta = 4098 * [0.6108 * exp(17.27*T / (T+237.3))] / (T+237.3)^2
    """
    tmp = 4098 * (0.6108 * math.exp((17.27 * t) / (t + 237.3)))
    return tmp / math.pow((t + 237.3), 2)


def svp_from_t(t):
    """Saturation vapour pressure [kPa] from temperature [C] (FAO Eqs. 11-12)."""
    return 0.6108 * math.exp((17.27 * t) / (t + 237.3))


def net_out_lw_rad(tmin, tmax, sol_rad, cs_rad, avp):
    """Net outgoing longwave radiation [MJ m-2 day-1] (FAO Eq. 39).

    Note: tmin/tmax are in Celsius; internally converts to Kelvin (+273.16).
    """
    tmp1 = STEFAN_BOLTZMANN_CONSTANT * (
        (math.pow(tmax + 273.16, 4) + math.pow(tmin + 273.16, 4)) / 2
    )
    tmp2 = 0.34 - 0.14 * math.sqrt(avp)
    tmp3 = 1.35 * (sol_rad / cs_rad) - 0.35
    return tmp1 * tmp2 * tmp3


def psy_const(atmos_pres):
    """Psychrometric constant [kPa degC-1] (FAO Eq. 8)."""
    return 0.000665 * atmos_pres
