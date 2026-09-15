"""
QCM-D analysis library — partial implementation.
"""


import cmath
import math
import ctypes
import os

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
    """Compute |G*|rho at overtone n."""
    return grho3 * (n / 3) ** (phi / 180.0)


def zstar_bulk(n, grho3, phi):
    """Compute complex acoustic impedance for bulk material."""
    grho_n = grho(n, grho3, phi)
    gstar = grho_n * cmath.exp(1j * math.pi * phi / 180)
    return cmath.sqrt(gstar)


def calc_delfstar(n, layers):
    """Compute complex frequency shift via C library."""
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
    raise NotImplementedError("Inverse solver not yet implemented")


def compute_sensitivity(n, layers, param_name, layer_idx=1):
    """Compute d(delfstar)/d(param)."""
    raise NotImplementedError("Sensitivity analysis not yet implemented")
