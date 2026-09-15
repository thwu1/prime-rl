"""
ASCE Standardized Reference Evapotranspiration Engine

Implements both 'asce' (ASCE-EWRI 2005 simplified) and 'refet' (RefET software
full-precision) calculation variants for daily and hourly timesteps, plus a
divergence decomposition between the two variants.

Delegates atmospheric pressure and clear-sky radiation calculations to a
compiled C shared library (/app/lib/libatmos.so) via ctypes.

"""

import math
import ctypes
import os


# ---------------------------------------------------------------------------
# Load C shared library
# ---------------------------------------------------------------------------

_LIB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         'lib', 'libatmos.so')
_atmos = ctypes.CDLL(_LIB_PATH)

_atmos.air_pressure.argtypes = [ctypes.c_double, ctypes.c_int]
_atmos.air_pressure.restype = ctypes.c_double

_atmos.precipitable_water.argtypes = [ctypes.c_double, ctypes.c_double]
_atmos.precipitable_water.restype = ctypes.c_double

_atmos.sin_beta_24_daily.argtypes = [ctypes.c_double, ctypes.c_double]
_atmos.sin_beta_24_daily.restype = ctypes.c_double

_atmos.sin_beta_hourly.argtypes = [ctypes.c_double, ctypes.c_double,
                                    ctypes.c_double]
_atmos.sin_beta_hourly.restype = ctypes.c_double

_atmos.rso_clearsky.argtypes = [ctypes.c_double, ctypes.c_double,
                                 ctypes.c_double, ctypes.c_double,
                                 ctypes.c_double]
_atmos.rso_clearsky.restype = ctypes.c_double


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
    if method == 'asce':
        return 2503.0 * exp_term / denom
    else:
        return 4098.0 * 0.6108 * exp_term / denom


# ---------------------------------------------------------------------------
# Solar geometry
# ---------------------------------------------------------------------------

def _doy_fraction(doy):
    """DOY fraction [radians]."""
    return doy * 2.0 * math.pi / 365.0


def _declination(doy, method='asce'):
    """Earth declination [radians]."""
    if method == 'asce':
        return 0.409 * math.sin(_doy_fraction(doy) - 1.39)
    else:
        return 23.45 * (math.pi / 180.0) * math.sin(
            2.0 * math.pi * (doy + 284) / 365.0
        )


def _dr(doy):
    """Inverse square of earth-sun distance."""
    return 1.0 + 0.033 * math.cos(_doy_fraction(doy))


def _seasonal_correction(doy):
    """Seasonal correction for solar time [hours]."""
    b = 2.0 * math.pi * (doy - 81) / 364.0
    return 0.1645 * math.sin(2.0 * b) - 0.1255 * math.cos(b) - 0.0250 * math.sin(b)


def _solar_time_rad(lon, time_mid, sc):
    """Solar time [hours] (noon = 0). lon in radians."""
    return time_mid + (lon * 24.0 / (2.0 * math.pi)) + sc - 12.0


def _solar_hour_angle(solar_time):
    """Solar hour angle [radians], wrapped to [-pi, pi]."""
    omega = (2.0 * math.pi / 24.0) * solar_time
    return ((omega + math.pi) % (2.0 * math.pi)) - math.pi


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
    if method == 'asce':
        return (24.0 / math.pi) * 4.92 * dr_val * theta
    else:
        return (24.0 / math.pi) * (1367.0 * 0.0036) * dr_val * theta


def _ra_daily_split(lat, doy, dec_method='asce', sc_method='asce'):
    """Ra with separate control over declination and solar constant."""
    delta = _declination(doy, dec_method)
    omega_s = _sunset_hour_angle(lat, delta)
    theta = (
        omega_s * math.sin(lat) * math.sin(delta)
        + math.cos(lat) * math.cos(delta) * math.sin(omega_s)
    )
    dr_val = _dr(doy)
    if sc_method == 'asce':
        return (24.0 / math.pi) * 4.92 * dr_val * theta, delta, omega_s
    else:
        return (24.0 / math.pi) * (1367.0 * 0.0036) * dr_val * theta, delta, omega_s


def _ra_hourly(lat, lon, doy, time_mid, method='asce'):
    """Hourly extraterrestrial radiation [MJ m-2 h-1]."""
    sc = _seasonal_correction(doy)
    omega = _solar_hour_angle(_solar_time_rad(lon, time_mid, sc))
    delta = _declination(doy, method)
    omega_s = _sunset_hour_angle(lat, delta)

    omega1 = max(min(omega - math.pi / 24.0, omega_s), -omega_s)
    omega2 = max(min(omega + math.pi / 24.0, omega_s), -omega_s)
    omega1 = min(omega1, omega2)

    theta = (
        (omega2 - omega1) * math.sin(lat) * math.sin(delta)
        + math.cos(lat) * math.cos(delta) * (math.sin(omega2) - math.sin(omega1))
    )
    dr_val = _dr(doy)
    if method == 'asce':
        return (12.0 / math.pi) * 4.92 * dr_val * theta
    else:
        return (12.0 / math.pi) * (1367.0 * 0.0036) * dr_val * theta


def _rso_simple(ra, elev):
    """Simplified clear-sky solar radiation [MJ m-2]."""
    return (0.75 + 2.0e-5 * elev) * ra


def _rso_daily_full(ra, ea, pair, doy, lat):
    """Full daily clear-sky radiation (Appendix D) via C library."""
    sin_b24 = _atmos.sin_beta_24_daily(lat, float(doy))
    return _atmos.rso_clearsky(ra, pair, ea, sin_b24, 0.1)


def _rso_hourly_full(ra, ea, pair, doy, time_mid, lat, lon, method='asce'):
    """Full hourly clear-sky radiation (Appendix D) via C library."""
    sc = _seasonal_correction(doy)
    omega = _solar_hour_angle(_solar_time_rad(lon, time_mid, sc))
    delta = _declination(doy, method)
    sin_beta = _atmos.sin_beta_hourly(lat, delta, omega)
    return _atmos.rso_clearsky(ra, pair, ea, sin_beta, 0.01)


# ---------------------------------------------------------------------------
# Cloudiness and net radiation
# ---------------------------------------------------------------------------

def _fcd_daily(rs, rso):
    """Daytime cloudiness fraction for daily timestep."""
    if rso <= 0:
        return 1.0
    ratio = max(min(rs / rso, 1.0), 0.3)
    return 1.35 * ratio - 0.35


def _fcd_hourly(rs, rso, doy, time, lat, lon, method='asce'):
    """Cloudiness fraction for hourly timestep. Uses time (period start) for beta."""
    sc = _seasonal_correction(doy)
    delta = _declination(doy, method)
    omega = _solar_hour_angle(_solar_time_rad(lon, time, sc))
    sin_val = (
        math.sin(lat) * math.sin(delta)
        + math.cos(lat) * math.cos(delta) * math.cos(omega)
    )
    beta = math.asin(max(min(sin_val, 1.0), -1.0))

    if rso <= 0:
        fcd = 1.0
    else:
        ratio = max(min(rs / rso, 1.0), 0.3)
        fcd = 1.35 * ratio - 0.35

    if beta < 0.3:
        fcd = 1.0
    return fcd


def _rnl_daily(tmax, tmin, ea, fcd):
    """Daily net long-wave radiation [MJ m-2 d-1]."""
    return (
        4.901e-9 * fcd * (0.34 - 0.14 * math.sqrt(ea))
        * 0.5 * ((tmax + 273.16) ** 4 + (tmin + 273.16) ** 4)
    )


def _rnl_hourly(tmean, ea, fcd):
    """Hourly net long-wave radiation [MJ m-2 h-1]."""
    return 2.042e-10 * fcd * (0.34 - 0.14 * math.sqrt(ea)) * (tmean + 273.16) ** 4


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
    """Compute daily reference ET with all intermediates."""
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

    if method == 'asce':
        rso = _rso_simple(ra, elev)
    else:
        rso = _rso_daily_full(ra, ea, pair, doy, lat)

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
    time_mid = time + 0.5

    pair = _air_pressure(elev, method)
    es = _sat_vapor_pressure(tmean)
    es_s = _es_slope(tmean, method)
    vpd = es - ea  # Hourly: not clipped
    psy = 0.000665 * pair
    u2 = _wind_height_adjust(uz, zw)

    delta_val = _declination(doy, method)
    dr_val = _dr(doy)
    sc = _seasonal_correction(doy)
    omega = _solar_hour_angle(_solar_time_rad(lon, time_mid, sc))
    omega_s = _sunset_hour_angle(lat, delta_val)
    ra = _ra_hourly(lat, lon, doy, time_mid, method)

    if method == 'asce':
        rso = _rso_simple(ra, elev)
    else:
        rso = _rso_hourly_full(ra, ea, pair, doy, time_mid, lat, lon, method)

    # fcd uses period start time (not time_mid) for beta clamping
    fcd = _fcd_hourly(rs, rso, doy, time, lat, lon, method)
    rnl = _rnl_hourly(tmean, ea, fcd)
    rn = _rn(rs, rnl)

    # --- ETo (grass / short reference) ---
    cn_eto = 37.0
    if rn < 0:
        cd_eto, g_rn_eto = 0.96, 0.5
    else:
        cd_eto, g_rn_eto = 0.24, 0.1
    g_eto = rn * g_rn_eto
    eto = _etsz(rn, g_eto, tmean, u2, vpd, es_s, psy, cn_eto, cd_eto)

    # --- ETr (alfalfa / tall reference) ---
    cn_etr = 66.0
    if rn < 0:
        cd_etr, g_rn_etr = 1.7, 0.2
    else:
        cd_etr, g_rn_etr = 0.25, 0.04
    g_etr = rn * g_rn_etr
    etr = _etsz(rn, g_etr, tmean, u2, vpd, es_s, psy, cn_etr, cd_etr)

    return {
        'pair': pair, 'es': es, 'ea': ea,
        'es_slope': es_s, 'vpd': vpd, 'psy': psy, 'u2': u2,
        'delta': delta_val, 'dr': dr_val, 'sc': sc,
        'omega': omega, 'omega_s': omega_s,
        'ra': ra, 'rso': rso, 'fcd': fcd, 'rnl': rnl, 'rn': rn,
        'eto': eto, 'etr': etr,
    }


def decompose_daily_divergence(tmin, tmax, ea, rs, uz, zw, elev, lat, doy,
                               surface='etr'):
    """Decompose daily ET divergence between 'asce' and 'refet' variants."""
    et_key = surface.lower()

    # Baseline: full asce and full refet
    et_asce = compute_daily(tmin, tmax, ea, rs, uz, zw, elev, lat, doy, 'asce')[et_key]
    et_refet = compute_daily(tmin, tmax, ea, rs, uz, zw, elev, lat, doy, 'refet')[et_key]
    total = et_asce - et_refet

    sources = ['air_pressure', 'es_slope', 'declination',
               'solar_constant', 'clear_sky_radiation']
    contributions = {}
    for source in sources:
        et_swap = _compute_daily_with_swap(
            tmin, tmax, ea, rs, uz, zw, elev, lat, doy, et_key, source
        )
        contributions[source] = et_asce - et_swap

    residual = total - sum(contributions.values())

    result = {'total': total}
    result.update(contributions)
    result['residual'] = residual
    return result


def _compute_daily_with_swap(tmin, tmax, ea, rs, uz, zw, elev, lat, doy,
                             et_key, swap_source):
    """Compute daily ET using 'asce' baseline with one equation swapped to 'refet'."""
    ap_method = 'refet' if swap_source == 'air_pressure' else 'asce'
    es_method = 'refet' if swap_source == 'es_slope' else 'asce'
    dec_method = 'refet' if swap_source == 'declination' else 'asce'
    sc_method = 'refet' if swap_source == 'solar_constant' else 'asce'
    rso_swap = swap_source == 'clear_sky_radiation'

    pair = _air_pressure(elev, ap_method)
    tmean = 0.5 * (tmin + tmax)
    es = 0.5 * (_sat_vapor_pressure(tmin) + _sat_vapor_pressure(tmax))
    es_s = _es_slope(tmean, es_method)
    vpd = max(es - ea, 0.0)
    psy = 0.000665 * pair
    u2 = _wind_height_adjust(uz, zw)

    # Ra with separate control of declination and solar constant
    ra, delta_val, omega_s = _ra_daily_split(lat, doy, dec_method, sc_method)

    # Clear-sky radiation
    if rso_swap:
        rso = _rso_daily_full(ra, ea, pair, doy, lat)
    else:
        rso = _rso_simple(ra, elev)

    fcd = _fcd_daily(rs, rso)
    rnl = _rnl_daily(tmax, tmin, ea, fcd)
    rn = _rn(rs, rnl)
    g = 0.0

    if et_key == 'eto':
        return _etsz(rn, g, tmean, u2, vpd, es_s, psy, 900.0, 0.34)
    else:
        return _etsz(rn, g, tmean, u2, vpd, es_s, psy, 1600.0, 0.38)
