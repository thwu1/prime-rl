"""
ctypes wrapper for the compiled C Brusselator RHS kernel.

The shared library librhs.so must exist in the same directory as this file.
It is built from brusselator_rhs.c.
"""
import ctypes
import numpy as np
import os

_lib = None


def _load_library():
    """Load the compiled shared library, setting argtypes and restype."""
    global _lib
    lib_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'librhs.so')
    if not os.path.exists(lib_path):
        raise FileNotFoundError(
            f"Compiled C library not found at {lib_path}. "
            f"Build it from brusselator_rhs.c before use."
        )
    _lib = ctypes.CDLL(lib_path)
    _lib.brusselator_rhs.restype = None
    _lib.brusselator_rhs.argtypes = [
        ctypes.POINTER(ctypes.c_double),   # y   (input)
        ctypes.POINTER(ctypes.c_double),   # dydt (output)
        ctypes.c_int,                      # N
        ctypes.c_double,                   # Du
        ctypes.c_double,                   # Dv
        ctypes.c_double,                   # A
        ctypes.c_double,                   # B
    ]


def c_brusselator_rhs(y, N, Du=0.02, Dv=0.02, A=1.0, B=3.0):
    """Evaluate Brusselator RHS using the compiled C kernel.

    Parameters and return value match solver.system.brusselator_rhs.
    """
    global _lib
    if _lib is None:
        _load_library()

    y_c = np.ascontiguousarray(y, dtype=np.float64)
    dydt = np.empty(2 * N, dtype=np.float64)

    _lib.brusselator_rhs(
        y_c.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        dydt.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        ctypes.c_int(N),
        ctypes.c_double(Du),
        ctypes.c_double(Dv),
        ctypes.c_double(A),
        ctypes.c_double(B),
    )

    return dydt
