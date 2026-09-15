"""

Time integration methods for the DGSEM solver.
"""

import numpy as np


def ssp_rk3_step(U, dt, rhs_func):
    """Perform one step of the 3rd-order SSP Runge-Kutta method (Shu-Osher).

    U^(1) = U^n + dt * L(U^n)
    U^(2) = (3/4)*U^n + (1/4)*(U^(1) + dt * L(U^(1)))
    U^(3) = (1/3)*U^n + (2/3)*(U^(2) + dt * L(U^(2)))
    """
    k1 = rhs_func(U)
    U1 = U + dt * k1

    k2 = rhs_func(U1)
    U2 = 0.75 * U + 0.25 * (U1 + dt * k2)

    k3 = rhs_func(U2)
    U3 = (1.0 / 3.0) * U + (2.0 / 3.0) * (U2 + dt * k3)

    return U3
