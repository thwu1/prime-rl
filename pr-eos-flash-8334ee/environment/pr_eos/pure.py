"""Pure component Peng-Robinson parameters.

"""
import math
from .constants import R, OMEGA_A, OMEGA_B


def pr_pure_a_alpha_b(Tc, Pc, omega, T):
    """Return (a*alpha(T), b) for one pure component."""
    a = OMEGA_A * R * R * Tc * Tc / Pc
    b = OMEGA_B * R * Tc / Pc
    kappa = 0.37464 + 1.48226 * omega - 0.17992 * omega * omega
    sqrtTr = math.sqrt(T / Tc)
    alpha = (1.0 + kappa * (1.0 - sqrtTr)) ** 2
    return a * alpha, b
