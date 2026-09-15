"""
Time integration methods for the DGSEM solver.
"""

import numpy as np


def ssp_rk3_step(U, dt, rhs_func):
    """Perform one step of the 3rd-order SSP Runge-Kutta method (Shu-Osher).

    The SSP-RK3 method is:
        U^(1) = U^n + dt * L(U^n)
        U^(2) = (3/4)*U^n + (1/4)*(U^(1) + dt * L(U^(1)))
        U^(3) = (1/3)*U^n + (2/3)*(U^(2) + dt * L(U^(2)))
        U^{n+1} = U^(3)

    Parameters
    ----------
    U : np.ndarray
        Current solution.
    dt : float
        Time step.
    rhs_func : callable
        Function computing dU/dt = rhs_func(U).

    Returns
    -------
    U_new : np.ndarray
        Solution after one time step.

    TODO: Implement the three-stage SSP-RK3 method.
    """
    raise NotImplementedError("SSP-RK3 time stepping not implemented")
