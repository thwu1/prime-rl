"""Special function implementations for rough volatility models."""
import numpy as np
import scipy.special as sp


def mittag_leffler_two(z, alpha, beta, n_terms=200):
    """Evaluate the two-parameter Mittag-Leffler function E_{alpha,beta}(z).

    Uses a truncated power series expansion with early termination.
    """
    z = np.atleast_1d(np.asarray(z, dtype=complex))
    result = np.zeros_like(z, dtype=complex)
    for k in range(1, n_terms):
        term = z**k / sp.gamma(alpha * k + beta)
        result += term
        if np.all(np.abs(term) < 1e-15):
            break
    return np.real(result)


def norm_lev_contract_rheston(H, nu, rho, lbd, T):
    """Normalized leverage contract under rough Heston with mean reversion.

    Parameters
    ----------
    H : float
        Hurst parameter.
    nu : float
        Vol-of-vol parameter.
    rho : float
        Spot-vol correlation.
    lbd : float
        Mean reversion speed.
    T : array_like
        Maturities.
    """
    alpha = H + 0.5
    lbdp = lbd - rho * nu
    T = np.atleast_1d(np.asarray(T))
    return (
        (1.0 - mittag_leffler_two(z=-lbdp * T**alpha, alpha=alpha, beta=2))
        * rho * nu / lbdp
    )
