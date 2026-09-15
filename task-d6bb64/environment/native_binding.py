"""ctypes bindings for the libelliptic native shared library.

Loads the compiled C shared library and exposes Python-callable wrappers
for the core elliptic function routines: Landen sequence, K(k), and cd(u,k).
"""

import ctypes
import os

_dir = os.path.dirname(os.path.abspath(__file__))
_lib = ctypes.CDLL(os.path.join(_dir, "libelliptic.so"))


class LandenResult(ctypes.Structure):
    """Mirrors the C LandenResult struct."""
    _fields_ = [
        ("values", ctypes.c_double * 30),
        ("length", ctypes.c_int),
    ]


class CmplxResult(ctypes.Structure):
    """Mirrors the C CmplxResult struct."""
    _fields_ = [
        ("imag", ctypes.c_double),
        ("real", ctypes.c_double),
    ]


# Function signatures
_lib.landen_sequence_c.argtypes = [ctypes.c_double, ctypes.c_int]
_lib.landen_sequence_c.restype = LandenResult

_lib.complete_elliptic_K_c.argtypes = [ctypes.c_double]
_lib.complete_elliptic_K_c.restype = ctypes.c_double

_lib.elliptic_cd_c.argtypes = [ctypes.c_double, ctypes.c_double, ctypes.c_double]
_lib.elliptic_cd_c.restype = CmplxResult


def landen_sequence(k, n=7):
    """Compute descending Landen sequence via native C library.

    Parameters
    ----------
    k : float
        Starting elliptic modulus, 0 < k < 1.
    n : int
        Maximum number of sequence elements.

    Returns
    -------
    list of float
        Descending Landen sequence [k_0, k_{-1}, ...].
    """
    result = _lib.landen_sequence_c(float(k), int(n))
    return [result.values[i] for i in range(result.length)]


def complete_elliptic_K(k):
    """Compute K(k) via native C library.

    Parameters
    ----------
    k : float
        Elliptic modulus, 0 <= k < 1.

    Returns
    -------
    float
        K(k).
    """
    return _lib.complete_elliptic_K_c(float(k))


def elliptic_cd(u, k):
    """Evaluate cd(u, k) via native C library.

    Parameters
    ----------
    u : complex or float
        Argument (not normalized by K).
    k : float
        Elliptic modulus, 0 < k < 1.

    Returns
    -------
    complex
        cd(u, k).
    """
    u = complex(u)
    result = _lib.elliptic_cd_c(u.real, u.imag, float(k))
    return complex(result.real, result.imag)
