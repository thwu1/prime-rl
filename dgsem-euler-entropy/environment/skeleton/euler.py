"""
Compressible Euler equations in 1D: conserved variables, fluxes, and
entropy-related quantities.

Conserved variables: U = [rho, rho*v, E]
where E = p/(gamma-1) + 0.5*rho*v^2

Primitive variables: W = [rho, v, p]
"""

import numpy as np

GAMMA = 1.4


def conserved_to_primitive(U):
    """Convert conserved variables to primitive variables.

    Parameters
    ----------
    U : np.ndarray, shape (3,) or (3, n)
        Conserved variables [rho, rho*v, E].

    Returns
    -------
    W : np.ndarray, same shape as U
        Primitive variables [rho, v, p].
    """
    rho = U[0]
    v = U[1] / rho
    p = (GAMMA - 1.0) * (U[2] - 0.5 * rho * v**2)
    return np.array([rho, v, p])


def primitive_to_conserved(W):
    """Convert primitive variables to conserved variables.

    Parameters
    ----------
    W : np.ndarray, shape (3,) or (3, n)
        Primitive variables [rho, v, p].

    Returns
    -------
    U : np.ndarray, same shape as W
        Conserved variables [rho, rho*v, E].
    """
    rho, v, p = W[0], W[1], W[2]
    E = p / (GAMMA - 1.0) + 0.5 * rho * v**2
    return np.array([rho, rho * v, E])


def euler_flux(U):
    """Physical flux F(U) for the 1D Euler equations.

    Parameters
    ----------
    U : np.ndarray, shape (3,)
        Conserved variables at a single point.

    Returns
    -------
    F : np.ndarray, shape (3,)
    """
    rho, rho_v, E = U[0], U[1], U[2]
    v = rho_v / rho
    p = (GAMMA - 1.0) * (E - 0.5 * rho * v**2)
    return np.array([rho_v, rho_v * v + p, (E + p) * v])


def max_wave_speed(U):
    """Maximum wave speed |v| + c for the 1D Euler equations.

    Parameters
    ----------
    U : np.ndarray, shape (3,) or (3, n)

    Returns
    -------
    lambda_max : float or np.ndarray
    """
    rho = U[0]
    v = U[1] / rho
    p = (GAMMA - 1.0) * (U[2] - 0.5 * rho * v**2)
    c = np.sqrt(GAMMA * p / rho)
    return np.abs(v) + c


def lax_friedrichs_flux(U_L, U_R):
    """Local Lax-Friedrichs (Rusanov) numerical flux.

    Parameters
    ----------
    U_L, U_R : np.ndarray, shape (3,)
        Left and right conserved states.

    Returns
    -------
    F_num : np.ndarray, shape (3,)
    """
    F_L = euler_flux(U_L)
    F_R = euler_flux(U_R)
    lambda_max = max(max_wave_speed(U_L), max_wave_speed(U_R))
    return 0.5 * (F_L + F_R) - 0.5 * lambda_max * (U_R - U_L)


def ln_mean(a, b):
    """Logarithmic mean of two positive numbers.

    ln_mean(a, b) = (a - b) / (ln(a) - ln(b))

    Uses a numerically stable implementation when a ≈ b.

    TODO: Implement this function. Must handle the case a ≈ b carefully
    to avoid division by zero. Use a Taylor expansion when |a-b|/max(a,b) < 1e-4.
    """
    raise NotImplementedError("Logarithmic mean not implemented")


def chandrashekar_flux(U_L, U_R):
    """Entropy-conservative two-point flux of Chandrashekar (2013).

    This flux is entropy-conservative for the compressible Euler equations,
    meaning it exactly preserves the mathematical entropy when used in a
    flux-differencing DG formulation.

    Reference: Chandrashekar, "Kinetic Energy Preserving and Entropy Stable
    Finite Volume Schemes for Compressible Euler and Navier-Stokes Equations",
    Communications in Computational Physics, 2013.

    Parameters
    ----------
    U_L, U_R : np.ndarray, shape (3,)
        Left and right conserved states.

    Returns
    -------
    F_num : np.ndarray, shape (3,)
        The entropy-conservative numerical flux.

    TODO: Implement the Chandrashekar flux. Define beta = rho / (2*p) (inverse
    temperature). Use logarithmic means of rho and beta. The flux components are:
        f1 = rho_ln * v_avg
        f2 = f1 * v_avg + p_avg
        f3 = f1 * (1/(2*(gamma-1)*beta_ln) + v_avg^2 - 0.5*v2_avg) + p_avg * v_avg
    where rho_ln = ln_mean(rho_L, rho_R), beta_ln = ln_mean(beta_L, beta_R),
    v_avg = 0.5*(v_L+v_R), v2_avg = 0.5*(v_L^2+v_R^2),
    p_avg = 0.5*(rho_L+rho_R)/(2*beta_ln) = rho_avg/(2*beta_ln).
    """
    raise NotImplementedError("Chandrashekar entropy-conservative flux not implemented")


def mathematical_entropy(U):
    """Compute the mathematical entropy S = -rho * s / (gamma - 1)
    where s = ln(p) - gamma * ln(rho).

    Parameters
    ----------
    U : np.ndarray, shape (3,)
        Conserved variables at a single point.

    Returns
    -------
    S : float
        Mathematical entropy density.
    """
    rho = U[0]
    v = U[1] / rho
    p = (GAMMA - 1.0) * (U[2] - 0.5 * rho * v**2)
    s = np.log(p) - GAMMA * np.log(rho)
    return -rho * s / (GAMMA - 1.0)
