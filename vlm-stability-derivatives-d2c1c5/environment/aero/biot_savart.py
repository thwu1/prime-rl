"""Ctypes wrapper for the libvortex C shared library.

Provides Biot-Savart velocity computations for vortex filaments.
All functions return velocity per unit circulation (no 1/(4*pi) factor).
"""
import ctypes
import os
import numpy as np

_LIB_DIR = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'libvortex')
)
_LIB_PATH = os.path.join(_LIB_DIR, 'libvortex.so')

if not os.path.exists(_LIB_PATH):
    raise RuntimeError(f"Required shared library not found: {_LIB_PATH}")

_lib = ctypes.CDLL(_LIB_PATH)
_dptr = ctypes.POINTER(ctypes.c_double)

_lib.biot_savart_finite.argtypes = [_dptr, _dptr, _dptr, _dptr]
_lib.biot_savart_finite.restype = None

_lib.biot_savart_semi_inf.argtypes = [_dptr, _dptr, _dptr, _dptr]
_lib.biot_savart_semi_inf.restype = None

_lib.horseshoe_velocity.argtypes = [_dptr, _dptr, _dptr, _dptr, _dptr]
_lib.horseshoe_velocity.restype = None


def _cptr(arr):
    """Return ctypes double pointer for a contiguous float64 array."""
    return arr.ctypes.data_as(_dptr)


def biot_savart_finite(P, A, B):
    """Induced velocity at point P from finite vortex segment A -> B."""
    P = np.ascontiguousarray(P, dtype=np.float64)
    A = np.ascontiguousarray(A, dtype=np.float64)
    B = np.ascontiguousarray(B, dtype=np.float64)
    vel = np.zeros(3, dtype=np.float64)
    _lib.biot_savart_finite(_cptr(P), _cptr(A), _cptr(B), _cptr(vel))
    return vel


def biot_savart_semi_inf(P, Q, d):
    """Induced velocity at point P from semi-infinite vortex at Q in direction d."""
    P = np.ascontiguousarray(P, dtype=np.float64)
    Q = np.ascontiguousarray(Q, dtype=np.float64)
    d = np.ascontiguousarray(d, dtype=np.float64)
    vel = np.zeros(3, dtype=np.float64)
    _lib.biot_savart_semi_inf(_cptr(P), _cptr(Q), _cptr(d), _cptr(vel))
    return vel


def horseshoe_velocity(P, A, B, d_inf):
    """Induced velocity from horseshoe vortex with bound segment A->B."""
    P = np.ascontiguousarray(P, dtype=np.float64)
    A = np.ascontiguousarray(A, dtype=np.float64)
    B = np.ascontiguousarray(B, dtype=np.float64)
    d_inf = np.ascontiguousarray(d_inf, dtype=np.float64)
    vel = np.zeros(3, dtype=np.float64)
    _lib.horseshoe_velocity(
        _cptr(P), _cptr(A), _cptr(B), _cptr(d_inf), _cptr(vel))
    return vel
