#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Excerpt from groundhog geotechnical library - phaserelations module
# Author: Bruno Stuyts
# Reference: Budhu (2011). Soil mechanics and foundation engineering.
#
# NOTE: This file requires numpy and groundhog dependencies to run.
# It is provided as domain reference only.

import numpy as np
from groundhog.general.validation import Validator


# ============================================================================
# Void ratio from porosity
# ============================================================================

def voidratio_porosity(porosity):
    """
    Converts porosity to void ratio.

    .. math::
        e = \\frac{n}{1-n}
    """
    return porosity / (1 - porosity)


# ============================================================================
# Porosity from void ratio
# ============================================================================

def porosity_voidratio(voidratio):
    """
    Calculates the porosity from void ratio.

    .. math::
        n = \\frac{e}{e+1}
    """
    return voidratio / (1 + voidratio)


# ============================================================================
# Void ratio from bulk unit weight
# ============================================================================

VOIDRATIO_BULKUNITWEIGHT = {
    'bulkunitweight': {'type': 'float', 'min_value': 10.0, 'max_value': 25.0},
    'saturation': {'type': 'float', 'min_value': 0.0, 'max_value': 1.0},
    'specific_gravity': {'type': 'float', 'min_value': 2.4, 'max_value': 2.9},
    'unitweight_water': {'type': 'float', 'min_value': 9.0, 'max_value': 11.0},
}


@Validator(VOIDRATIO_BULKUNITWEIGHT, {})
def voidratio_bulkunitweight(
        bulkunitweight,
        saturation=1.0, specific_gravity=2.65, unitweight_water=10.0, **kwargs):
    """
    Calculates the void ratio from the bulk unit weight for a soil with
    varying saturation.

    Since unit weight is generally better known or measured than void ratio,
    this conversion can be useful to derive the in-situ void ratio in a
    soil profile.

    The default behaviour assumes saturated soil but the saturation can be
    changed for dry or partially saturated soil.

    :param bulkunitweight: The bulk unit weight of the soil (gamma) [kN/m3]
    :param saturation: Saturation S, 0 (dry) to 1 (fully saturated) [-]
    :param specific_gravity: Specific gravity Gs [-]
    :param unitweight_water: Unit weight of water (gamma_w) [kN/m3]

    .. math::
        \\gamma = \\left( \\frac{G_s + S e}{1 + e} \\right) \\gamma_w

        \\implies e = \\frac{\\gamma_w G_s - \\gamma}{\\gamma - S \\gamma_w}

        w = \\frac{S e}{G_s}

    Reference - Budhu (2011). Soil mechanics and foundation engineering
    """
    _e = (unitweight_water * specific_gravity - bulkunitweight) / \
         (bulkunitweight - saturation * unitweight_water)
    _w = (saturation * _e) / specific_gravity

    return {
        'e [-]': _e,
        'w [-]': _w
    }
