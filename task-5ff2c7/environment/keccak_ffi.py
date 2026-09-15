"""Keccak-f[1600] FFI wrapper.

Loads the pre-built libkeccak.so shared library and exposes the permutation
function to Python via ctypes. This module is shared by all vendor candidate
implementations and is verified correct against NIST FIPS 202 reference values.
"""

import ctypes
import os

_lib_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'libkeccak.so')
_keccak_lib = ctypes.CDLL(_lib_path)
_keccak_lib.keccak_f1600.argtypes = [ctypes.POINTER(ctypes.c_uint8)]
_keccak_lib.keccak_f1600.restype = None


def keccak_f1600(state_bytes):
    """Apply Keccak-f[1600] permutation to 200 bytes of state via C library."""
    buf = (ctypes.c_uint8 * 200)(*state_bytes)
    _keccak_lib.keccak_f1600(buf)
    return bytes(buf)
