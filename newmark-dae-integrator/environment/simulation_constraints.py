"""
Constraint equations and Jacobians for the spatial double pendulum.


Constraints (6 total, all holonomic):
  C1 (3 eqs): Spherical joint 1 -- top of link1 coincides with fixed pivot
  C2 (3 eqs): Spherical joint 2 -- bottom of link1 coincides with top of link2

Quaternion unit-norm is NOT a DAE constraint; it is enforced by algebraic
renormalization after each position update.

The constraint Jacobian Phi_v is the 6x12 matrix of partial derivatives
of the constraint velocity equations with respect to generalized velocities.
It is computed by a native C shared library loaded via ctypes.
"""

import os
import ctypes
import numpy as np
from bodies import quat_to_rotation, skew

_LIB_PATH = '/app/native/libconstraints.so'
_native_lib = None


def _get_native_lib():
    """Load and cache the native constraint library."""
    global _native_lib
    if _native_lib is not None:
        return _native_lib
    if not os.path.exists(_LIB_PATH):
        raise RuntimeError(
            f"Native constraint library not found at {_LIB_PATH}. "
            f"Build it with: make -C /app/native"
        )
    _native_lib = ctypes.CDLL(_LIB_PATH)
    _native_lib.compute_jacobian_native.restype = None
    _native_lib.compute_jacobian_native.argtypes = [
        ctypes.POINTER(ctypes.c_double),  # R1 (3x3, row-major)
        ctypes.POINTER(ctypes.c_double),  # R2 (3x3, row-major)
        ctypes.POINTER(ctypes.c_double),  # s1_top (3,)
        ctypes.POINTER(ctypes.c_double),  # s1_bot (3,)
        ctypes.POINTER(ctypes.c_double),  # s2_top (3,)
        ctypes.POINTER(ctypes.c_double),  # Phi_v (6x12, row-major)
    ]
    return _native_lib


def compute_constraints(system):
    """
    Evaluate the 6 constraint equations.
    Returns a 6-vector of constraint violations.
    """
    C = np.zeros(6)

    link1 = system.link1
    link2 = system.link2

    # C1: Spherical joint 1 (link1 top = pivot)
    R1 = link1.get_rotation_matrix()
    top1_global = link1.pos + R1 @ system.link1_top_local
    C[0:3] = top1_global - system.pivot

    # C2: Spherical joint 2 (link1 bottom = link2 top)
    bot1_global = link1.pos + R1 @ system.link1_bot_local
    R2 = link2.get_rotation_matrix()
    top2_global = link2.pos + R2 @ system.link2_top_local
    C[3:6] = bot1_global - top2_global

    return C


def compute_constraint_velocity(system):
    """
    Evaluate the time derivative of constraints: dC/dt = Phi_v * v
    Returns a 6-vector.
    """
    Phi_v = compute_jacobian(system)
    v = system.get_all_velocities()
    return Phi_v @ v


def compute_jacobian(system):
    """
    Compute the constraint Jacobian Phi_v (6 x 12) with respect to
    generalized velocities v = [v1, omega1, v2, omega2].

    Delegates to the native C library via ctypes.
    """
    lib = _get_native_lib()

    R1 = np.ascontiguousarray(system.link1.get_rotation_matrix(), dtype=np.float64)
    R2 = np.ascontiguousarray(system.link2.get_rotation_matrix(), dtype=np.float64)
    s1_top = np.ascontiguousarray(system.link1_top_local, dtype=np.float64)
    s1_bot = np.ascontiguousarray(system.link1_bot_local, dtype=np.float64)
    s2_top = np.ascontiguousarray(system.link2_top_local, dtype=np.float64)
    Phi_v = np.zeros((6, 12), dtype=np.float64, order='C')

    lib.compute_jacobian_native(
        R1.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        R2.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        s1_top.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        s1_bot.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        s2_top.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        Phi_v.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
    )

    return Phi_v


def compute_gamma(system):
    """
    Compute the gamma vector: the right-hand side acceleration-level term.
    gamma = -d(Phi_v)/dt * v  (the quadratic velocity term)

    For spherical joints, gamma_i = R_i * (omega_i x (omega_i x s_i))
    This is the centripetal acceleration term.
    """
    gamma = np.zeros(6)

    link1 = system.link1
    link2 = system.link2
    R1 = link1.get_rotation_matrix()
    R2 = link2.get_rotation_matrix()

    # Spherical joint 1
    s1_top = system.link1_top_local
    omega1 = link1.omega
    gamma[0:3] = -(R1 @ np.cross(omega1, np.cross(omega1, s1_top)))

    # Spherical joint 2
    s1_bot = system.link1_bot_local
    s2_top = system.link2_top_local
    omega2 = link2.omega
    gamma[3:6] = -(R1 @ np.cross(omega1, np.cross(omega1, s1_bot))
                   - R2 @ np.cross(omega2, np.cross(omega2, s2_top)))

    return gamma
