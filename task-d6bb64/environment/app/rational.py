"""Elliptic rational function R_N(x) and degree equation solver."""

import numpy as np
from elliptic_k import complete_elliptic_K
from jacobi_cd import elliptic_cd
from cd_inverse import elliptic_cd_inv


def _solve_degree_equation(N, k):
    """Solve K'(k_tilde)/K(k_tilde) = N * K'(k)/K(k) for k_tilde.

    Parameters
    ----------
    N : int
        Filter order.
    k : float
        Selectivity parameter.

    Returns
    -------
    float
        k_tilde satisfying the degree equation.
    """
    kp = np.sqrt(1.0 - k * k)
    K_val = complete_elliptic_K(k)
    Kp_val = complete_elliptic_K(kp)
    target = N * Kp_val / K_val

    lo, hi = 1e-18, 1.0 - 1e-15
    for _ in range(200):
        mid = (lo + hi) / 2.0
        midp = np.sqrt(1.0 - mid * mid)
        K_mid = complete_elliptic_K(mid)
        Kp_mid = complete_elliptic_K(midp)
        ratio = Kp_mid / K_mid
        if ratio < target:
            hi = mid
        else:
            lo = mid
        if abs(ratio - target) / (abs(target) + 1e-30) < 1e-14:
            break
    return (lo + hi) / 2.0


def elliptic_rational_function(x, N, k):
    """Evaluate the N-th order elliptic rational function R_N(x).

    Parameters
    ----------
    x : complex or float
        Argument.
    N : int
        Order.
    k : float
        Selectivity parameter (elliptic modulus).

    Returns
    -------
    complex
        R_N(x).
    """
    x = complex(x)
    k_tilde = _solve_degree_equation(N, k)

    K_val = complete_elliptic_K(k)
    K_tilde = complete_elliptic_K(k_tilde)

    u = elliptic_cd_inv(x, k)
    v = N * (K_tilde / K_val) * u
    return elliptic_cd(v, k_tilde)
