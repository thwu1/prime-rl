"""

Compressible Euler equations in 1D: conserved variables, fluxes, and
entropy-related quantities.
"""

import numpy as np

GAMMA = 1.4


def conserved_to_primitive(U):
    """Convert conserved [rho, rho*v, E] to primitive [rho, v, p]."""
    rho = U[0]
    v = U[1] / rho
    p = (GAMMA - 1.0) * (U[2] - 0.5 * rho * v**2)
    return np.array([rho, v, p])


def primitive_to_conserved(W):
    """Convert primitive [rho, v, p] to conserved [rho, rho*v, E]."""
    rho, v, p = W[0], W[1], W[2]
    E = p / (GAMMA - 1.0) + 0.5 * rho * v**2
    return np.array([rho, rho * v, E])


def euler_flux(U):
    """Physical flux F(U) for the 1D Euler equations."""
    rho, rho_v, E = U[0], U[1], U[2]
    v = rho_v / rho
    p = (GAMMA - 1.0) * (E - 0.5 * rho * v**2)
    return np.array([rho_v, rho_v * v + p, (E + p) * v])


def max_wave_speed(U):
    """Maximum wave speed |v| + c."""
    rho = U[0]
    v = U[1] / rho
    p = (GAMMA - 1.0) * (U[2] - 0.5 * rho * v**2)
    c = np.sqrt(GAMMA * np.abs(p) / rho)
    return np.abs(v) + c


def lax_friedrichs_flux(U_L, U_R):
    """Local Lax-Friedrichs (Rusanov) numerical flux."""
    F_L = euler_flux(U_L)
    F_R = euler_flux(U_R)
    lambda_max = max(max_wave_speed(U_L), max_wave_speed(U_R))
    return 0.5 * (F_L + F_R) - 0.5 * lambda_max * (U_R - U_L)


def ln_mean(a, b):
    """Logarithmic mean with numerically stable implementation.

    ln_mean(a, b) = (a - b) / (ln(a) - ln(b))
    Uses Taylor expansion when a ≈ b to avoid cancellation.
    """
    xi = a / b
    f = (xi - 1.0) / (xi + 1.0)
    u = f * f
    if u < 1e-4:
        F = 1.0 + u / 3.0 + u * u / 5.0 + u * u * u / 7.0
        return (a + b) / (2.0 * F)
    else:
        return (a - b) / (np.log(a) - np.log(b))


def chandrashekar_flux(U_L, U_R):
    """Entropy-conservative two-point flux of Chandrashekar (2013).

    Reference: Chandrashekar, "Kinetic Energy Preserving and Entropy Stable
    Finite Volume Schemes for Compressible Euler and Navier-Stokes Equations",
    Communications in Computational Physics, 2013.
    """
    rho_L = U_L[0]
    v_L = U_L[1] / rho_L
    p_L = (GAMMA - 1.0) * (U_L[2] - 0.5 * rho_L * v_L**2)

    rho_R = U_R[0]
    v_R = U_R[1] / rho_R
    p_R = (GAMMA - 1.0) * (U_R[2] - 0.5 * rho_R * v_R**2)

    # Inverse temperature: beta = rho / (2*p)
    beta_L = rho_L / (2.0 * p_L)
    beta_R = rho_R / (2.0 * p_R)

    # Logarithmic means
    rho_ln = ln_mean(rho_L, rho_R)
    beta_ln = ln_mean(beta_L, beta_R)

    # Averages
    rho_avg = 0.5 * (rho_L + rho_R)
    v_avg = 0.5 * (v_L + v_R)
    v2_avg = 0.5 * (v_L**2 + v_R**2)
    p_avg = rho_avg / (2.0 * beta_ln)

    # Flux components
    f1 = rho_ln * v_avg
    f2 = f1 * v_avg + p_avg
    # Energy flux: note v_avg**2 (NOT 0.5*v_avg**2)
    f3 = f1 * (1.0 / (2.0 * (GAMMA - 1.0) * beta_ln)
               + v_avg**2 - 0.5 * v2_avg) + p_avg * v_avg

    return np.array([f1, f2, f3])


def mathematical_entropy(U):
    """S = -rho * s / (gamma - 1) where s = ln(p) - gamma * ln(rho)."""
    rho = U[0]
    v = U[1] / rho
    p = (GAMMA - 1.0) * (U[2] - 0.5 * rho * v**2)
    s = np.log(p) - GAMMA * np.log(rho)
    return -rho * s / (GAMMA - 1.0)
