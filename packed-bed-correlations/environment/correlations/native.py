"""ctypes bridge for native C correlation implementations (libcorr.so)."""

import ctypes
import os

_lib_path = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "libcorr.so",
)
_lib = ctypes.CDLL(_lib_path)

# -- Idelchik --
_lib.idelchik_dp.restype = ctypes.c_double
_lib.idelchik_dp.argtypes = [ctypes.c_double] * 6

# -- Harrison-Brunner-Hecker --
_lib.harrison_brunner_hecker_dp.restype = ctypes.c_double
_lib.harrison_brunner_hecker_dp.argtypes = [ctypes.c_double] * 7 + [ctypes.c_int]


def idelchik(dp, voidage, vs, rho, mu, L=1.0, **_):
    """Idelchik pressure drop via native C implementation."""
    return _lib.idelchik_dp(dp, voidage, vs, rho, mu, L)


def harrison_brunner_hecker(dp, voidage, vs, rho, mu, L=1.0, Dt=None, **_):
    """Harrison-Brunner-Hecker pressure drop via native C implementation."""
    if Dt is None:
        return _lib.harrison_brunner_hecker_dp(dp, voidage, vs, rho, mu, L, 0.0, 0)
    return _lib.harrison_brunner_hecker_dp(dp, voidage, vs, rho, mu, L, Dt, 1)
