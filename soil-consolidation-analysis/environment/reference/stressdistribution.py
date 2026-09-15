#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Excerpt from groundhog geotechnical library - stressdistribution module
# Author: Bruno Stuyts
# Reference: Budhu (2011). Soil mechanics and foundation engineering.
#
# NOTE: This file requires numpy and groundhog dependencies to run.
# It is provided as domain reference only.

import numpy as np
from groundhog.general.validation import Validator


# ============================================================================
# Strip load stress distribution
# ============================================================================

STRESSES_STRIPLOAD = {
    'z': {'type': 'float', 'min_value': 0.0, 'max_value': None},
    'x': {'type': 'float', 'min_value': None, 'max_value': None},
    'width': {'type': 'float', 'min_value': 0.0, 'max_value': None},
    'imposedstress': {'type': 'float', 'min_value': None, 'max_value': None},
    'triangular': {'type': 'bool', },
}

STRESSES_STRIPLOAD_ERRORRETURN = {
    'delta sigma z [kPa]': np.nan,
    'delta sigma x [kPa]': np.nan,
    'delta tau zx [kPa]': np.nan,
}


@Validator(STRESSES_STRIPLOAD, STRESSES_STRIPLOAD_ERRORRETURN)
def stresses_stripload(z, x, width, imposedstress, triangular=False, **kwargs):
    """
    Calculates the stress redistribution at a point in the subsoil due to a
    strip load with a given width, applied at the surface.

    :param z: Vertical distance from the soil surface (z) [m]
    :param x: Horizontal offset from the leftmost corner of the strip footing (x) [m]
    :param width: Width of the strip footing (B) [m]
    :param imposedstress: Maximum value of the imposed force per unit area (q_s) [kN/m^2]
    :param triangular: Boolean for triangular load pattern (default=False)

    .. math::
        R_1 = \\sqrt{x^2 + z^2}

        R_2 = \\sqrt{(x - B)^2 + z^2}

        \\cos (\\alpha + \\beta) = z / R_1

        \\cos \\beta = z / R_2

        \\text{Uniform load:}

        \\Delta \\sigma_z = \\frac{q_s}{\\pi} [ \\alpha + \\sin \\alpha \\cos(\\alpha + 2\\beta) ]

        \\Delta \\sigma_x = \\frac{q_s}{\\pi} [ \\alpha - \\sin \\alpha \\cos(\\alpha + 2\\beta) ]

        \\Delta \\tau_{zx} = \\frac{q_s}{\\pi} [ \\sin \\alpha \\sin(\\alpha + 2\\beta) ]

    Reference - Budhu (2011). Soil mechanics and foundation engineering
    """

    R_1 = np.sqrt(x ** 2 + z ** 2)
    R_2 = np.sqrt((x - width) ** 2 + z ** 2)

    _theta1 = np.arccos(z / R_1)
    _theta2 = np.arccos(z / R_2)
    if x < width:
        _theta2 = -_theta2
    beta = _theta2
    alpha = _theta1 - beta

    if triangular:
        _delta_sigma_z = (imposedstress / np.pi) * (
            (x / width) * alpha - 0.5 * np.sin(2 * beta))
        _delta_sigma_x = (imposedstress / np.pi) * (
            (x / width) * alpha -
            (z / width) * np.log((R_1 ** 2) / (R_2 ** 2)) +
            0.5 * np.sin(2 * beta))
        _delta_tau_zx = (imposedstress / (2 * np.pi)) * (
            1 + np.cos(2 * beta) - 2 * (z / width) * alpha)
    else:
        _delta_sigma_z = (imposedstress / np.pi) * (
            alpha + np.sin(alpha) * np.cos(alpha + 2 * beta))
        _delta_sigma_x = (imposedstress / np.pi) * (
            alpha - np.sin(alpha) * np.cos(alpha + 2 * beta))
        _delta_tau_zx = (imposedstress / np.pi) * (
            np.sin(alpha) * np.sin(alpha + 2 * beta))

    return {
        'delta sigma z [kPa]': _delta_sigma_z,
        'delta sigma x [kPa]': _delta_sigma_x,
        'delta tau zx [kPa]': _delta_tau_zx,
    }


# ============================================================================
# Circular footing stress distribution
# ============================================================================

STRESSES_CIRCLE = {
    'z': {'type': 'float', 'min_value': 0.0, 'max_value': None},
    'footing_radius': {'type': 'float', 'min_value': 0.0, 'max_value': None},
    'imposedstress': {'type': 'float', 'min_value': None, 'max_value': None},
    'poissonsratio': {'type': 'float', 'min_value': 0.0, 'max_value': 0.5},
}


@Validator(STRESSES_CIRCLE, {})
def stresses_circle(z, footing_radius, imposedstress, poissonsratio, **kwargs):
    """
    Calculates stress below center of a uniformly loaded circular foundation.

    .. math::
        \\Delta \\sigma_z = q_s [ 1 - (1 / (1 + (r_0/z)^2))^{3/2} ]

    Reference - Budhu (2011). Soil mechanics and foundation engineering
    """
    _delta_sigma_z = imposedstress * (
        1 - (1 / (1 + ((footing_radius / z) ** 2))) ** (3 / 2))
    _delta_sigma_r = 0.5 * imposedstress * (
        (1 + 2 * poissonsratio) -
        (4 * (1 + poissonsratio)) / np.sqrt(1 + (footing_radius / z) ** 2) +
        (1 / ((1 + ((footing_radius / z) ** 2)) ** (3 / 2))))
    return {
        'delta sigma z [kPa]': _delta_sigma_z,
        'delta sigma r [kPa]': _delta_sigma_r,
    }


# ============================================================================
# Rectangular footing stress distribution
# ============================================================================

STRESSES_RECTANGLE = {
    'imposedstress': {'type': 'float', 'min_value': None, 'max_value': None},
    'length': {'type': 'float', 'min_value': 0.0, 'max_value': None},
    'width': {'type': 'float', 'min_value': 0.0, 'max_value': None},
    'z': {'type': 'float', 'min_value': 0.0, 'max_value': None},
}


@Validator(STRESSES_RECTANGLE, {})
def stresses_rectangle(imposedstress, length, width, z, **kwargs):
    """
    Calculates the stresses under the CORNER of a uniformly loaded rectangular
    area. Stresses under other points can be calculated by subdividing the
    rectangle into smaller sub-rectangles and using superposition.

    E.g. the stresses under the CENTER of a rectangle is calculated by
    subdividing the rectangle into four equal sub-areas and calculating the
    stress below the corner of each and summing them.

    .. math::
        \\Delta \\sigma_z = \\frac{q_s}{2\\pi} [ \\tan^{-1}\\frac{LB}{zR_3}
            + \\frac{LBz}{R_3}(\\frac{1}{R_1^2} + \\frac{1}{R_2^2}) ]

        R_1 = \\sqrt{L^2 + z^2}, \\quad
        R_2 = \\sqrt{B^2 + z^2}, \\quad
        R_3 = \\sqrt{L^2 + B^2 + z^2}

    Reference - Budhu (2011). Soil mechanics and foundation engineering
    """
    R_1 = np.sqrt(length ** 2 + z ** 2)
    R_2 = np.sqrt(width ** 2 + z ** 2)
    R_3 = np.sqrt(length ** 2 + width ** 2 + z ** 2)

    _delta_sigma_z = (imposedstress / (2 * np.pi)) * (
        np.arctan((length * width) / (z * R_3)) +
        ((length * width * z) / R_3) * ((1 / R_1 ** 2) + (1 / (R_2 ** 2))))

    return {
        'delta sigma z [kPa]': _delta_sigma_z,
    }
