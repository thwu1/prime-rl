#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Excerpt from groundhog geotechnical library - settlement module
# Author: Bruno Stuyts
# Reference: Budhu (2011). Soil mechanics and foundation engineering.
#
# NOTE: This file requires numpy and groundhog dependencies to run.
# It is provided as domain reference only.

import numpy as np
from groundhog.general.validation import Validator


# ============================================================================
# Primary consolidation settlement - Normally Consolidated soil
# ============================================================================

PRIMARYCONSOLIDATIONSETTLEMENT_NC = {
    'initial_height': {'type': 'float', 'min_value': 0.0, 'max_value': None},
    'initial_voidratio': {'type': 'float', 'min_value': 0.1, 'max_value': 5.0},
    'initial_effective_stress': {'type': 'float', 'min_value': 0.0, 'max_value': None},
    'effective_stress_increase': {'type': 'float', 'min_value': 0.0, 'max_value': None},
    'compression_index': {'type': 'float', 'min_value': 0.1, 'max_value': 0.8},
    'e_min': {'type': 'float', 'min_value': 0.1, 'max_value': None},
}


@Validator(PRIMARYCONSOLIDATIONSETTLEMENT_NC, {})
def primaryconsolidationsettlement_nc(
        initial_height, initial_voidratio, initial_effective_stress,
        effective_stress_increase, compression_index, e_min=0.3, **kwargs):
    """
    Calculates the primary consolidation settlement for normally consolidated
    fine grained soil.

    .. math::
        \\Delta z = \\frac{H_0}{1 + e_0} C_c \\log_{10}
            \\frac{\\sigma_{v0}' + \\Delta \\sigma_v'}{\\sigma_{v0}'}

        \\Delta e = C_c \\log_{10}
            \\frac{\\sigma_{v0}' + \\Delta \\sigma_v'}{\\sigma_{v0}'}

    Reference - Budhu (2011). Soil mechanics and foundation engineering
    """
    _delta_e = compression_index * \
        np.log10((initial_effective_stress + effective_stress_increase) / initial_effective_stress)

    if (initial_voidratio - _delta_e) > e_min:
        pass
    else:
        _delta_e = initial_voidratio - e_min

    _delta_z = (initial_height / (1 + initial_voidratio)) * _delta_e
    _e_final = initial_voidratio - _delta_e

    return {
        'delta z [m]': _delta_z,
        'delta e [-]': _delta_e,
        'e final [-]': _e_final
    }


# ============================================================================
# Primary consolidation settlement - Overconsolidated soil
# ============================================================================

PRIMARYCONSOLIDATIONSETTLEMENT_OC = {
    'initial_height': {'type': 'float', 'min_value': 0.0, 'max_value': None},
    'initial_voidratio': {'type': 'float', 'min_value': 0.1, 'max_value': 5.0},
    'initial_effective_stress': {'type': 'float', 'min_value': 0.0, 'max_value': None},
    'preconsolidation_pressure': {'type': 'float', 'min_value': 0.0, 'max_value': None},
    'effective_stress_increase': {'type': 'float', 'min_value': 0.0, 'max_value': None},
    'compression_index': {'type': 'float', 'min_value': 0.1, 'max_value': 0.8},
    'recompression_index': {'type': 'float', 'min_value': 0.015, 'max_value': 0.35},
    'e_min': {'type': 'float', 'min_value': 0.1, 'max_value': None},
}


@Validator(PRIMARYCONSOLIDATIONSETTLEMENT_OC, {})
def primaryconsolidationsettlement_oc(
        initial_height, initial_voidratio, initial_effective_stress,
        preconsolidation_pressure, effective_stress_increase,
        compression_index, recompression_index, e_min=0.3, **kwargs):
    """
    Calculates the primary consolidation settlement for an overconsolidated clay.
    This material is characterised using a compression index and a recompression
    index which can be derived from oedometer tests.

    The settlement depends on whether the stress increase loads the layer beyond
    the preconsolidation pressure. If stresses remain below the preconsolidation
    pressure, the recompression index applies. If stresses go beyond the
    preconsolidation pressure, the compression index will apply for the increase
    beyond the preconsolidation pressure.

    .. math::
        \\Delta z = \\frac{H_0}{1 + e_0} C_r \\log_{10}
            \\frac{\\sigma_{v0}' + \\Delta \\sigma_v'}{\\sigma_{v0}'};
            \\quad \\sigma_{v0}' + \\Delta \\sigma_v' < p_c'

        \\Delta z = \\frac{H_0}{1 + e_0} ( C_r \\log_{10} \\frac{p_c'}{\\sigma_{v0}'}
            + C_c \\log_{10} \\frac{\\sigma_{v0}' + \\Delta \\sigma_v'}{p_c'} );
            \\quad \\sigma_{v0}' + \\Delta \\sigma_v' > p_c'

    Reference - Budhu (2011). Soil mechanics and foundation engineering
    """
    if (initial_effective_stress + effective_stress_increase) < preconsolidation_pressure:
        _delta_e = recompression_index * np.log10(
            (initial_effective_stress + effective_stress_increase) / initial_effective_stress)
    else:
        _delta_e = \
            recompression_index * np.log10(preconsolidation_pressure / initial_effective_stress) + \
            compression_index * np.log10(
                (initial_effective_stress + effective_stress_increase) / preconsolidation_pressure)

    if (initial_voidratio - _delta_e) > e_min:
        pass
    else:
        _delta_e = initial_voidratio - e_min

    _delta_z = (initial_height / (1 + initial_voidratio)) * _delta_e
    _e_final = initial_voidratio - _delta_e

    return {
        'delta z [m]': _delta_z,
        'delta e [-]': _delta_e,
        'e final [-]': _e_final
    }
