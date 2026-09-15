"""
Numerical flux functions for the DGSEM solver.

IMPLEMENT the three stub functions below:
  - ln_mean(a, b)
  - ec_flux(u_L, u_R)
  - rs_flux(u_L, u_R)

The functions lax_friedrichs_flux and central_flux are provided as working
reference implementations.
"""
import numpy as np
from core import GAMMA, cons2prim, euler_flux, max_wavespeed


def ln_mean(a, b):
    """Compute a specific weighted mean of two positive real numbers.

    This mean arises naturally in the construction of entropy-conservative
    numerical fluxes for gas dynamics. It must satisfy:

    - Symmetry:    ln_mean(a, b) == ln_mean(b, a)
    - Consistency: ln_mean(a, a) == a
    - Bounds:      min(a, b) <= ln_mean(a, b) <= (a + b) / 2

    Must be numerically stable when a is close to b (avoid catastrophic
    cancellation or division by near-zero quantities).

    Parameters:
        a, b: positive floats
    Returns:
        float: the mean value
    """
    raise NotImplementedError("Implement the weighted mean")


def ec_flux(u_L, u_R):
    """Entropy-conservative two-point numerical flux for the 1D Euler equations.

    Must satisfy these mathematical properties:

    1. Consistency:  ec_flux(u, u) == euler_flux(u)
    2. Symmetry:     ec_flux(u_L, u_R) == ec_flux(u_R, u_L)
    3. Entropy conservation:
           (w_R - w_L)^T * f = psi_R - psi_L
       where w are the entropy variables derived from the mathematical entropy
           S = -rho * s / (gamma - 1),    s = ln(p) - gamma * ln(rho)
       and psi = rho * v is the entropy flux potential.

    The entropy variables are:
        w1 = (gamma - s) / (gamma - 1) - beta * v^2
        w2 = 2 * beta * v
        w3 = -2 * beta
    where beta = rho / (2 * p).

    Parameters:
        u_L, u_R: conservative state vectors [rho, rho*v, E]
    Returns:
        numpy array [f1, f2, f3] -- the entropy-conservative flux
    """
    raise NotImplementedError("Implement the entropy-conservative flux")


def rs_flux(u_L, u_R):
    """Approximate Riemann solver for the 1D Euler equations.

    Must satisfy:

    1. Consistency: rs_flux(u, u) == euler_flux(u)
    2. Exact resolution of isolated contact discontinuities
       (states with identical velocity and pressure but different density)
    3. Correct handling of all wave configurations (subsonic, supersonic,
       transonic) including supersonic flow in either direction

    Parameters:
        u_L, u_R: conservative state vectors [rho, rho*v, E]
    Returns:
        numpy array [f1, f2, f3] -- the numerical flux
    """
    raise NotImplementedError("Implement the Riemann solver flux")


def lax_friedrichs_flux(u_L, u_R):
    """Local Lax-Friedrichs (Rusanov) flux -- provided for reference."""
    lam = max(max_wavespeed(u_L), max_wavespeed(u_R))
    return 0.5 * (euler_flux(u_L) + euler_flux(u_R)) - 0.5 * lam * (u_R - u_L)


def central_flux(u_L, u_R):
    """Central (average) flux -- provided for reference."""
    return 0.5 * (euler_flux(u_L) + euler_flux(u_R))
