"""Kernel functions for QMC lattice rules.

Wraps the C shared library libqmc.so via ctypes for performance.
The library provides omega(x), the shift-invariant kernel function
used in worst-case error evaluation for lattice rule construction.
"""
import ctypes
import os
import numpy as np

_dir = os.path.dirname(os.path.abspath(__file__))
_lib = ctypes.CDLL(os.path.join(_dir, 'libqmc.so'))
_lib.omega.restype = ctypes.c_double
_lib.omega.argtypes = [ctypes.c_double]


def omega(x):
    """Shift-invariant kernel omega(x) = 2*pi^2 * B_2({x})."""
    scalar = np.isscalar(x)
    x = np.atleast_1d(np.asarray(x, dtype=float))
    out = np.empty_like(x)
    for i in range(x.size):
        out.flat[i] = _lib.omega(x.flat[i])
    return float(out.item()) if scalar else out
