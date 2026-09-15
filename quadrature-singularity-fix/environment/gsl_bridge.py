"""
Python bridge to the GSL quadrature C library via ctypes.

Loads libquad.so and provides gsl_integrate() for calling GSL's
adaptive Gauss-Kronrod quadrature from Python.

See src/quad_wrapper.h for the C API:
    typedef double (*py_integrand)(double x);
    double quad_integrate(py_integrand f, double a, double b,
                          double epsabs, double epsrel, int method,
                          double *abserr, int *neval, int *status);
"""

import ctypes
import os

_LIB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'libquad.so')
_lib = ctypes.CDLL(_LIB_PATH)

# Callback type matching: typedef double (*py_integrand)(double x);
INTEGRAND_FUNC = ctypes.CFUNCTYPE(ctypes.c_double, ctypes.c_double)

# Configure quad_integrate prototype
_lib.quad_integrate.argtypes = [
    INTEGRAND_FUNC,
    ctypes.c_double,
    ctypes.c_double,
    ctypes.c_double,
    ctypes.c_double,
    ctypes.c_int,
    ctypes.c_double,
    ctypes.c_int,
    ctypes.c_int,
]
_lib.quad_integrate.restype = ctypes.c_int


def gsl_integrate(f, a, b, epsabs=1e-12, epsrel=1e-12, method=0):
    """Integrate f(x) from a to b using GSL adaptive quadrature.

    Parameters
    ----------
    f : callable
        Python function: float -> float.
    a, b : float
        Integration limits (finite only).
    epsabs, epsrel : float
        Absolute and relative tolerances.
    method : int
        Quadrature method index (0=GK15 .. 5=GK61, 6=QAGS).

    Returns
    -------
    (result, abserr) : (float, float)
    """
    abserr = ctypes.c_double(0.0)
    neval = ctypes.c_int(0)
    status = ctypes.c_int(0)

    cb = INTEGRAND_FUNC(f)

    result = _lib.quad_integrate(
        cb, a, b, epsabs, epsrel, method,
        abserr, neval, status
    )

    if status.value != 0:
        raise RuntimeError(
            f"GSL integration failed with status {status.value}"
        )

    return float(result), float(abserr.value)
