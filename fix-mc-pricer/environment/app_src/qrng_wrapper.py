"""Python ctypes wrapper for the QRNG C shared library (libqrng.so)."""
import ctypes
import os

_lib_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "libqrng.so")
_lib = ctypes.CDLL(_lib_path)

# Function signatures
_lib.sobol_init.argtypes = [ctypes.c_int]
_lib.sobol_init.restype = None

_lib.sobol_generate.argtypes = [
    ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_double)
]
_lib.sobol_generate.restype = None

_lib.norm_inv.argtypes = [ctypes.c_double]
_lib.norm_inv.restype = ctypes.c_double


class SobolEngine:
    """Sobol quasi-random number generator backed by C shared library."""

    def __init__(self, dimension):
        if not 1 <= dimension <= 6:
            raise ValueError(f"dimension must be 1..6, got {dimension}")
        self.dim = dimension
        _lib.sobol_init(dimension)

    def generate(self, n):
        """Generate n quasi-random points in [0,1]^dim."""
        buf = (ctypes.c_double * (n * self.dim))()
        _lib.sobol_generate(self.dim, n, buf)
        result = []
        for i in range(n):
            point = [float(buf[i * self.dim + d]) for d in range(self.dim)]
            result.append(point)
        return result


def norm_inv(u):
    """Compute inverse standard normal CDF at probability u in (0,1)."""
    if u <= 0.0 or u >= 1.0:
        raise ValueError(f"u must be in (0, 1), got {u}")
    return _lib.norm_inv(u)
