"""Closed-form geometric Asian call option pricing.

The geometric average of lognormal prices is itself lognormal,
which allows a Black-Scholes-type closed-form solution.

Reference: Kemna & Vorst (1990), "A pricing method for options
based upon average asset values."
"""
import math


def _N(x):
    """Standard normal CDF via error function."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def geometric_asian_call(S0, K, r, sigma, T, n_steps):
    """Closed-form price of a discrete geometric Asian call option.

    The geometric average G = (S_{t1} * ... * S_{tn})^{1/n} is lognormal.
    We compute its distribution parameters and apply the Black-Scholes formula.

    Parameters
    ----------
    S0      : float - initial stock price
    K       : float - strike price
    r       : float - risk-free rate (annualised)
    sigma   : float - volatility (annualised)
    T       : float - time to maturity in years
    n_steps : int   - number of equally-spaced monitoring dates

    Returns
    -------
    float - discounted geometric Asian call price
    """
    n = n_steps

    # Mean of log(G): log(S0) + adjusted_drift * T_avg
    m = math.log(S0) + r * T * (n + 1) / (2 * n)

    # Variance of log(G): sigma^2 * covariance_sum
    v_sq = sigma ** 2 * T * (2 * n + 1) / (6 * n)

    v = math.sqrt(v_sq)

    d1 = (m - math.log(K) + v_sq) / v
    d2 = d1 - v

    price = math.exp(-r * T) * (math.exp(m + v_sq / 2) * _N(d1) - K * _N(d2))
    return price
