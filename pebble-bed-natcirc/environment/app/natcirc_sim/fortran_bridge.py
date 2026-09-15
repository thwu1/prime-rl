"""
Bridge to Fortran packed-bed correlations library via ctypes.

Loads libpackedbed.so and exposes the Ergun pressure gradient and
Wakao-Kaguei Nusselt number subroutines as Python callables that
accept and return numpy arrays.
"""
import ctypes
import numpy as np

_lib = None


def _get_lib():
    """Load the Fortran shared library (lazy singleton)."""
    global _lib
    if _lib is None:
        _lib = ctypes.CDLL("/app/libpackedbed.so")

        # ergun_dp(n, rho, vs, mu, dp_peb, eps, dp_dz)
        _lib.ergun_dp.restype = None
        _lib.ergun_dp.argtypes = [
            ctypes.c_int,      # n (by value)
            ctypes.c_void_p,   # rho array
            ctypes.c_void_p,   # vs array
            ctypes.c_void_p,   # mu array
            ctypes.c_double,   # dp_peb (by value)
            ctypes.c_double,   # eps (by value)
            ctypes.c_void_p,   # dp_dz output array
        ]

        # wakao_nu(n, Re, Pr, Nu)
        _lib.wakao_nu.restype = None
        _lib.wakao_nu.argtypes = [
            ctypes.c_int,      # n (by value)
            ctypes.c_void_p,   # Re array
            ctypes.c_void_p,   # Pr array
            ctypes.c_void_p,   # Nu output array
        ]
    return _lib


def ergun_pressure_gradient(rho, v_s, mu, d_p, epsilon):
    """
    Compute Ergun pressure gradient through packed bed [Pa/m].

    Calls the Fortran ergun_dp subroutine.

    Parameters
    ----------
    rho : ndarray
        Fluid density at each axial node [kg/m^3]
    v_s : ndarray
        Superficial velocity at each node [m/s]
    mu : ndarray
        Dynamic viscosity at each node [Pa.s]
    d_p : float
        Particle diameter [m]
    epsilon : float
        Bed void fraction [-]

    Returns
    -------
    ndarray
        Pressure gradient at each node [Pa/m]
    """
    lib = _get_lib()
    n = len(rho)
    rho_c = np.ascontiguousarray(rho, dtype=np.float64)
    vs_c = np.ascontiguousarray(v_s, dtype=np.float64)
    mu_c = np.ascontiguousarray(mu, dtype=np.float64)
    dp_dz = np.empty(n, dtype=np.float64)

    lib.ergun_dp(
        ctypes.c_int(n),
        rho_c.ctypes.data,
        vs_c.ctypes.data,
        mu_c.ctypes.data,
        ctypes.c_double(d_p),
        ctypes.c_double(epsilon),
        dp_dz.ctypes.data,
    )
    return dp_dz


def wakao_kaguei_nusselt(Re, Pr):
    """
    Compute Wakao-Kaguei Nusselt number for packed beds.

    Calls the Fortran wakao_nu subroutine.

    Parameters
    ----------
    Re : ndarray
        Particle Reynolds number at each node
    Pr : ndarray
        Prandtl number at each node

    Returns
    -------
    ndarray
        Nusselt number at each node
    """
    lib = _get_lib()
    n = len(Re)
    Re_c = np.ascontiguousarray(Re, dtype=np.float64)
    Pr_c = np.ascontiguousarray(Pr, dtype=np.float64)
    Nu = np.empty(n, dtype=np.float64)

    lib.wakao_nu(
        ctypes.c_int(n),
        Re_c.ctypes.data,
        Pr_c.ctypes.data,
        Nu.ctypes.data,
    )
    return Nu
