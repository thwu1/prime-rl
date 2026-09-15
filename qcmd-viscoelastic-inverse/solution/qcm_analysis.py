"""
QCM-D (Quartz Crystal Microbalance with Dissipation) analysis library.

Loads the compiled C shared library libqcm_transfer.so via ctypes for
forward computations. Implements inverse solver and sensitivity analysis
in Python.
"""


import cmath
import math
import ctypes
import os
import numpy as np
from scipy.optimize import least_squares
from copy import deepcopy

# Physical constants for AT-cut quartz
Zq = 8.84e6    # Shear acoustic impedance (Pa*s/m)
f1 = 5e6       # Fundamental resonant frequency (Hz)

# Load C shared library
_lib_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         'libqcm_transfer.so')
_lib = ctypes.CDLL(_lib_path)
_lib.qcm_delfstar.argtypes = [
    ctypes.c_int,                      # n
    ctypes.c_int,                      # nlayers
    ctypes.POINTER(ctypes.c_double),   # grho3
    ctypes.POINTER(ctypes.c_double),   # phi_deg
    ctypes.POINTER(ctypes.c_double),   # drho
    ctypes.c_double,                   # f1
    ctypes.c_double,                   # zq
    ctypes.POINTER(ctypes.c_double),   # out_delf
    ctypes.POINTER(ctypes.c_double),   # out_delg
]
_lib.qcm_delfstar.restype = None


def sauerbrey_mass(n, delf):
    """Calculate Sauerbrey mass (kg/m^2) from frequency shift."""
    return -delf * Zq / (2 * n * f1**2)


def grho(n, grho3, phi):
    """Compute |G*|rho at overtone n using power-law model."""
    return grho3 * (n / 3) ** (phi / 90)


def zstar_bulk(n, grho3, phi):
    """Compute complex acoustic impedance for bulk material."""
    grho_n = grho(n, grho3, phi)
    gstar = grho_n * cmath.exp(1j * math.pi * phi / 180)
    return cmath.sqrt(gstar)


def calc_delfstar(n, layers):
    """Compute complex frequency shift via C library.

    Returns complex: real = Delta f (Hz), imag = Delta Gamma (Hz).
    """
    layer_nums = sorted(layers.keys())
    nlayers = len(layer_nums)

    grho3_arr = (ctypes.c_double * nlayers)()
    phi_arr = (ctypes.c_double * nlayers)()
    drho_arr = (ctypes.c_double * nlayers)()

    for idx, key in enumerate(layer_nums):
        grho3_arr[idx] = layers[key]['grho3']
        phi_arr[idx] = layers[key]['phi']
        drho_val = layers[key]['drho']
        drho_arr[idx] = 1e200 if drho_val == float('inf') else drho_val

    out_delf = ctypes.c_double()
    out_delg = ctypes.c_double()

    _lib.qcm_delfstar(n, nlayers, grho3_arr, phi_arr, drho_arr,
                       f1, Zq, ctypes.byref(out_delf), ctypes.byref(out_delg))

    return complex(out_delf.value, out_delg.value)


def solve_inverse(delfstar_expt, harmonics_f, harmonics_g, layers_init):
    """Recover layer 1 properties from experimental frequency shifts."""
    layers = deepcopy(layers_init)

    x0 = [
        layers[1]['grho3'],
        layers[1]['phi'],
        layers[1]['drho'],
    ]

    lb = [1e4, 0.0, 0.0]
    ub = [1e13, 90.0, 0.03]
    x0 = [max(lo, min(hi, v)) for v, lo, hi in zip(x0, lb, ub)]

    def residual(x):
        layers_solve = deepcopy(layers)
        layers_solve[1]['grho3'] = x[0]
        layers_solve[1]['phi'] = x[1]
        layers_solve[1]['drho'] = x[2]

        vals = []
        for n_val in harmonics_f:
            calc = calc_delfstar(n_val, layers_solve)
            vals.append(calc.real - delfstar_expt[n_val].real)
        for n_val in harmonics_g:
            calc = calc_delfstar(n_val, layers_solve)
            vals.append(calc.imag - delfstar_expt[n_val].imag)
        return vals

    soln = least_squares(residual, x0, bounds=(lb, ub))

    return {
        'grho3': float(soln.x[0]),
        'phi': float(soln.x[1]),
        'drho': float(soln.x[2]),
    }


def compute_sensitivity(n, layers, param_name, layer_idx=1):
    """Compute d(delfstar)/d(param) via central finite differences."""
    val = layers[layer_idx][param_name]
    h = max(abs(val) * 1e-7, 1e-15)

    layers_plus = deepcopy(layers)
    layers_minus = deepcopy(layers)
    layers_plus[layer_idx][param_name] = val + h
    layers_minus[layer_idx][param_name] = val - h

    f_plus = calc_delfstar(n, layers_plus)
    f_minus = calc_delfstar(n, layers_minus)
    return (f_plus - f_minus) / (2 * h)
