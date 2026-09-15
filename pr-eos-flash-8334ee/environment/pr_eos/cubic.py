"""Cubic equation solver wrapper using C shared library via ctypes.

"""
import ctypes
import os
from .constants import R

_dir = os.path.dirname(os.path.abspath(__file__))
_lib_path = os.path.join(_dir, '..', 'libcubic', 'libcubic.so')

_lib = ctypes.CDLL(_lib_path)
_solve_cubic = _lib.solve_cubic_eos
_solve_cubic.argtypes = [ctypes.c_double, ctypes.c_double, ctypes.c_double * 3]
_solve_cubic.restype = ctypes.c_int


def solve_cubic_volumes(T, P, a_alpha, b):
    """Solve PR EOS cubic for molar volumes; return sorted physical roots."""
    RT = R * T
    A = a_alpha * P / (RT * RT)
    B = b * P / RT

    roots_arr = (ctypes.c_double * 3)()
    count = _solve_cubic(A, B, roots_arr)

    volumes = []
    for i in range(count):
        Z = roots_arr[i]
        V = Z * RT / P
        if V > b:
            volumes.append(V)

    volumes.sort()
    return volumes
