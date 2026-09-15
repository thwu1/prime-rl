"""Python ctypes bindings for the PDE kernel shared library (libpde_kernels.so)."""
import ctypes
import os

import numpy as np

_lib_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "libpde_kernels.so")
_lib = ctypes.CDLL(_lib_path)

# void thomas_solve(int, const double*, const double*, const double*, const double*, double*)
_lib.thomas_solve.argtypes = [
    ctypes.c_int,
    ctypes.POINTER(ctypes.c_double),
    ctypes.POINTER(ctypes.c_double),
    ctypes.POINTER(ctypes.c_double),
    ctypes.POINTER(ctypes.c_double),
    ctypes.POINTER(ctypes.c_double),
]
_lib.thomas_solve.restype = None

# void lax_wendroff_step(const double*, double*, int, double)
_lib.lax_wendroff_step.argtypes = [
    ctypes.POINTER(ctypes.c_double),
    ctypes.POINTER(ctypes.c_double),
    ctypes.c_int,
    ctypes.c_int,  # nu: should be c_double, not c_int
]
_lib.lax_wendroff_step.restype = None

# double compute_rms_error(const double*, const double*, int)
_lib.compute_rms_error.argtypes = [
    ctypes.POINTER(ctypes.c_double),
    ctypes.POINTER(ctypes.c_double),
    ctypes.c_int,
]
_lib.compute_rms_error.restype = ctypes.c_double


def thomas_solve(a, b, c, d):
    """Solve tridiagonal system Ax = d using the Thomas algorithm.

    a: lower diagonal (n,), a[0] is unused
    b: main diagonal (n,)
    c: upper diagonal (n,), c[n-1] is unused
    d: right-hand side (n,)
    Returns: solution vector x (n,)
    """
    n = len(b)
    a_c = np.ascontiguousarray(a, dtype=np.float64)
    b_c = np.ascontiguousarray(b, dtype=np.float64)
    c_c = np.ascontiguousarray(c, dtype=np.float64)
    d_c = np.ascontiguousarray(d, dtype=np.float64)
    x_c = np.empty(n, dtype=np.float64)

    _lib.thomas_solve(
        n,
        a_c.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        b_c.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        c_c.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        d_c.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        x_c.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
    )
    return x_c


def lax_wendroff_step(u, nu):
    """Perform a single time step for periodic advection.

    u: solution at current time (N,)
    nu: Courant number c*dt/h
    Returns: solution at next time step (N,)
    """
    N = len(u)
    u_c = np.ascontiguousarray(u, dtype=np.float64)
    u_new = np.empty(N, dtype=np.float64)

    _lib.lax_wendroff_step(
        u_c.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        u_new.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        N,
        float(nu),
    )
    return u_new


def rms_error(u_num, u_exact):
    """Compute RMS error between numerical and exact solutions."""
    n = len(u_num)
    u_n = np.ascontiguousarray(u_num, dtype=np.float64)
    u_e = np.ascontiguousarray(u_exact, dtype=np.float64)
    return _lib.compute_rms_error(
        u_n.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        u_e.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        n,
    )
