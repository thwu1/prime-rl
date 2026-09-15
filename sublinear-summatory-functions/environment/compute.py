"""
Python wrapper for the Dirichlet series computation library.
Loads libdirichlet.so via ctypes and exposes summatory functions.
"""
import ctypes
import os

_dir = os.path.dirname(os.path.abspath(__file__))
_lib = ctypes.CDLL(os.path.join(_dir, "libdirichlet.so"))

_lib.mertens.argtypes = [ctypes.c_int64]
_lib.mertens.restype = ctypes.c_int64

_lib.totient_sum.argtypes = [ctypes.c_int64]
_lib.totient_sum.restype = ctypes.c_int64

_lib.liouville_sum.argtypes = [ctypes.c_int64]
_lib.liouville_sum.restype = ctypes.c_int64


def mertens(n: int) -> int:
    """Compute M(n) = sum of mu(k) for k = 1..n."""
    return _lib.mertens(n)


def totient_sum(n: int) -> int:
    """Compute sum of phi(k) for k = 1..n, modulo 998244353."""
    return _lib.totient_sum(n)


def liouville_sum(n: int) -> int:
    """Compute L(n) = sum of lambda(k) for k = 1..n."""
    return _lib.liouville_sum(n)
