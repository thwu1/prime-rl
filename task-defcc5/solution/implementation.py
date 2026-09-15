"""
Reference implementation of the rectangular prism gravity forward model.

Based on Nagy (2000) with Fukushima (2020) numerically stable functions.
"""
import math
import numpy as np

GRAVITATIONAL_CONST = 6.6743e-11


def safe_atan2(y, x):
    if x == 0.0:
        if y > 0.0:
            return math.pi / 2
        elif y < 0.0:
            return -math.pi / 2
        else:
            return 0.0
    return math.atan(y / x)


def safe_log(x, y, z, r):
    if r == 0.0:
        return 0.0
    if x < 0.0:
        if y == 0.0 and z == 0.0:
            return -math.log(-2.0 * x)
        else:
            return math.log((y ** 2 + z ** 2) / (r - x))
    return math.log(x + r)


def kernel_pot(easting, northing, upward, radius):
    return (
        easting * northing * safe_log(upward, easting, northing, radius)
        + northing * upward * safe_log(easting, northing, upward, radius)
        + easting * upward * safe_log(northing, upward, easting, radius)
        - 0.5 * easting ** 2 * safe_atan2(upward * northing, easting * radius)
        - 0.5 * northing ** 2 * safe_atan2(upward * easting, northing * radius)
        - 0.5 * upward ** 2 * safe_atan2(easting * northing, upward * radius)
    )


def kernel_e(easting, northing, upward, radius):
    return -(
        northing * safe_log(upward, easting, northing, radius)
        + upward * safe_log(northing, upward, easting, radius)
        - easting * safe_atan2(northing * upward, easting * radius)
    )


def kernel_n(easting, northing, upward, radius):
    return -(
        upward * safe_log(easting, northing, upward, radius)
        + easting * safe_log(upward, easting, northing, radius)
        - northing * safe_atan2(easting * upward, northing * radius)
    )


def kernel_u(easting, northing, upward, radius):
    return -(
        easting * safe_log(northing, upward, easting, radius)
        + northing * safe_log(easting, northing, upward, radius)
        - upward * safe_atan2(easting * northing, upward * radius)
    )


def kernel_ee(easting, northing, upward, radius):
    if radius == 0.0:
        return float("nan")
    return -safe_atan2(northing * upward, easting * radius)


def kernel_nn(easting, northing, upward, radius):
    if radius == 0.0:
        return float("nan")
    return -safe_atan2(easting * upward, northing * radius)


def kernel_uu(easting, northing, upward, radius):
    if radius == 0.0:
        return float("nan")
    return -safe_atan2(easting * northing, upward * radius)


def kernel_en(easting, northing, upward, radius):
    if radius == 0.0:
        return float("nan")
    return safe_log(upward, easting, northing, radius)


def kernel_eu(easting, northing, upward, radius):
    if radius == 0.0:
        return float("nan")
    return safe_log(northing, easting, upward, radius)


def kernel_nu(easting, northing, upward, radius):
    if radius == 0.0:
        return float("nan")
    return safe_log(easting, northing, upward, radius)


_FIELD_KERNELS = {
    "potential": kernel_pot,
    "g_e": kernel_e,
    "g_n": kernel_n,
    "g_u": kernel_u,
    "g_ee": kernel_ee,
    "g_nn": kernel_nn,
    "g_uu": kernel_uu,
    "g_en": kernel_en,
    "g_eu": kernel_eu,
    "g_nu": kernel_nu,
}


def _evaluate_kernel(easting, northing, upward, prism, kernel_func):
    west, east, south, north, bottom, top = prism
    result = 0.0
    for i in range(2):
        shift_east = east - easting if i == 0 else west - easting
        for j in range(2):
            shift_north = north - northing if j == 0 else south - northing
            for k in range(2):
                shift_upward = top - upward if k == 0 else bottom - upward
                radius = math.sqrt(
                    shift_east ** 2 + shift_north ** 2 + shift_upward ** 2
                )
                sign = (-1) ** (i + j + k)
                result += sign * kernel_func(shift_east, shift_north, shift_upward, radius)
    return result


def prism_gravity(easting, northing, upward, prism, density, field):
    if field not in _FIELD_KERNELS:
        raise ValueError(f"Unknown field: {field}")
    kernel_func = _FIELD_KERNELS[field]
    kernel_sum = _evaluate_kernel(easting, northing, upward, prism, kernel_func)
    return GRAVITATIONAL_CONST * density * kernel_sum
