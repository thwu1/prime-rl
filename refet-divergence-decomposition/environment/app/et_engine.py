"""
ASCE Standardized Reference Evapotranspiration Engine

Delegates atmospheric pressure and clear-sky radiation to a compiled
C shared library (/app/lib/libatmos.so) loaded via ctypes.

Several intermediate functions may contain errors. The 'refet' method
variant is not yet supported in all method-dependent functions.
Hourly computation and divergence decomposition are not yet implemented.

"""

import math
import ctypes
import os


# ---------------------------------------------------------------------------
# Load C shared library for atmospheric / clear-sky calculations
# ---------------------------------------------------------------------------

_LIB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         'lib', 'libatmos.so')
_atmos = ctypes.CDLL(_LIB_PATH)

# Configure ctypes function signatures
_atmos.air_pressure.argtypes = [ctypes.c_double, ctypes.c_int]
_atmos.air_pressure.restype = ctypes.c_double

_atmos.precipitable_water.argtypes = [ctypes.c_double, ctypes.c_double]
_atmos.precipitable_water.restype = ctypes.c_double

_atmos.rso_clearsky.argtypes = [ctypes.c_double, ctypes.c_double,
                                 ctypes.c_double, ctypes.c_double,
                                 ctypes.c_double]
_atmos.rso_clearsky.restype = ctypes.c_double

# NOTE: sin_beta_24_daily and sin_beta_hourly signatures are not yet
# configured — add argtypes/restype before calling these functions.


# ---------------------------------------------------------------------------
# Atmospheric / thermodynamic functions
# ---------------------------------------------------------------------------

def _air_pressure(elev, method='asce'):
    """Mean atmospheric pressure [kPa] from elevation [m]."""
    mode = 0 if method == 'asce' else 1
    return _atmos.air_pressure(elev, mode)


def _sat_vapor_pressure(t):
    """Saturation vapor pressure [kPa] from temperature [C]."""
    return 0.6108 * math.exp(17.27 * t / (t + 237.3))


def _es_slope(tmean, method='asce'):
    """Slope of saturation vapor pressure curve [kPa C-1]."""
    exp_term = math.exp(17.27 * tmean / (tmean + 237.3))
    denom = (tmean + 237.3) ** 2
    # TODO: add refet variant
    return 2504.0 * exp_term / denom


# ---------------------------------------------------------------------------
# Solar geometry
# ---------------------------------------------------------------------------

def _doy_fraction(doy):
    """DOY fraction [radians]."""
    return doy * 2.0 * math.pi / 365.0


def _declination(doy, method='asce'):
    """Earth declination [radians]."""
    # TODO: add refet variant
    return 0.409 * math.sin(_doy_fraction(doy) - 1.40)


def _dr(doy):
    """Inverse square of earth-sun distance."""
    return 1.0 + 0.033 * math.cos(_doy_fraction(doy))


def _sunset_hour_angle(lat, delta):
    """Sunset hour angle [radians], clipped to [0, pi]."""
    x = -math.tan(lat) * math.tan(delta)
    x = max(min(x, 1.0), -1.0)
    return math.acos(x)


# ---------------------------------------------------------------------------
# Radiation
# ---------------------------------------------------------------------------

def _ra_daily(lat, doy, method='asce'):
    """Daily extraterrestrial radiation [MJ m-2 d-1]."""
    delta = _declination(doy, method)
    omega_s = _sunset_hour_angle(lat, delta)
    theta = (
        omega_s * math.sin(lat) * math.sin(delta)
        + math.cos(lat) * math.cos(delta) * math.sin(omega_s)
    )
    dr_val = _dr(doy)
    # TODO: add refet variant (different solar constant)
    return (24.0 / math.pi) * 4.92 * dr_val * theta


def _rso_simple(ra, elev):
    """Simplified clear-sky solar radiation [MJ m-2]."""
    return (0.75 + 2.5e-5 * elev) * ra


def _rso_daily_full(ra, ea, pair, doy, lat):
    """Full daily clear-sky radiation (Appendix D), via C library."""
    sin_b24 = _atmos.sin_beta_24_daily(lat, float(doy))
    return _atmos.rso_clearsky(ra, pair, ea, float(sin_b24), 0.1)


def _fcd_daily(rs, rso):
    """Daytime cloudiness fraction for daily timestep."""
    if rso <= 0:
        return 1.0
    ratio = max(min(rs / rso, 1.0), 0.3)
    return 1.35 * ratio - 0.35


def _rnl_daily(tmax, tmin, ea, fcd):
    """Daily net long-wave radiation [MJ m-2 d-1]."""
    return (
        4.901e-9 * fcd * (0.34 - 0.14 * math.sqrt(ea))
        * 0.5 * ((tmax + 273.16) ** 4 + (tmin + 273.16) ** 4)
    )


def _rn(rs, rnl):
    """Net radiation [MJ m-2]."""
    return 0.77 * rs - rnl


# ---------------------------------------------------------------------------
# Wind
# ---------------------------------------------------------------------------

def _wind_height_adjust(uz, zw):
    """Adjust wind speed to 2m height [m s-1]."""
    return uz * 4.87 / math.log(67.8 * zw - 5.42)


# ---------------------------------------------------------------------------
# Final ET equation
# ---------------------------------------------------------------------------

def _etsz(rn, g, tmean, u2, vpd, es_slope, psy, cn, cd):
    """Standardized reference ET [mm]."""
    numerator = 0.408 * es_slope * (rn - g) + psy * cn * u2 * vpd / (tmean + 273.0)
    denominator = es_slope + psy * (cd * u2 + 1.0)
    return numerator / denominator


# ===========================================================================
# Public API
# ===========================================================================

def compute_daily(tmin, tmax, ea, rs, uz, zw, elev, lat, doy, method='asce'):
    """Compute daily reference ET with all intermediates.

    Parameters
    ----------
    tmin, tmax : float  Temperature [C]
    ea : float          Actual vapor pressure [kPa]
    rs : float          Incoming solar radiation [MJ m-2 d-1]
    uz : float          Wind speed [m s-1]
    zw : float          Wind measurement height [m]
    elev : float        Elevation [m]
    lat : float         Latitude [radians]
    doy : int           Day of year
    method : str        'asce' or 'refet'

    Returns
    -------
    dict with all intermediates and 'eto', 'etr'.
    """
    pair = _air_pressure(elev, method)
    tmean = 0.5 * (tmin + tmax)
    es = 0.5 * (_sat_vapor_pressure(tmin) + _sat_vapor_pressure(tmax))
    es_s = _es_slope(tmean, method)
    vpd = max(es - ea, 0.0)
    psy = 0.000665 * pair
    u2 = _wind_height_adjust(uz, zw)

    delta_val = _declination(doy, method)
    dr_val = _dr(doy)
    omega_s = _sunset_hour_angle(lat, delta_val)
    ra = _ra_daily(lat, doy, method)
    rso = _rso_simple(ra, elev)

    fcd = _fcd_daily(rs, rso)
    rnl = _rnl_daily(tmax, tmin, ea, fcd)
    rn = _rn(rs, rnl)
    g = 0.0

    eto = _etsz(rn, g, tmean, u2, vpd, es_s, psy, 900.0, 0.34)
    etr = _etsz(rn, g, tmean, u2, vpd, es_s, psy, 1600.0, 0.38)

    return {
        'pair': pair, 'tmean': tmean, 'es': es, 'ea': ea,
        'es_slope': es_s, 'vpd': vpd, 'psy': psy, 'u2': u2,
        'delta': delta_val, 'dr': dr_val, 'omega_s': omega_s,
        'ra': ra, 'rso': rso, 'fcd': fcd, 'rnl': rnl, 'rn': rn,
        'eto': eto, 'etr': etr,
    }


def compute_hourly(tmean, ea, rs, uz, zw, elev, lat, lon, doy, time, method='asce'):
    """Compute hourly reference ET with all intermediates."""
    raise NotImplementedError("Hourly computation not yet implemented")


def decompose_daily_divergence(tmin, tmax, ea, rs, uz, zw, elev, lat, doy,
                               surface='etr'):
    """Decompose daily ET divergence between 'asce' and 'refet' variants."""
    raise NotImplementedError("Divergence decomposition not yet implemented")
