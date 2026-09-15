"""Geometric Brownian Motion path simulation under risk-neutral measure."""
import math


def simulate_paths(S0, r, sigma, T, n_steps, normals):
    """Simulate a GBM price path given a sequence of standard normal draws.

    Parameters
    ----------
    S0 : float      – initial stock price
    r  : float      – risk-free rate (annualised)
    sigma : float   – volatility (annualised)
    T  : float      – time to maturity in years
    n_steps : int   – number of discrete time steps
    normals : list   – list of *n_steps* standard-normal random numbers

    Returns
    -------
    list of float – stock prices [S_1, S_2, …, S_{n_steps}] at each step.
    """
    dt = T / n_steps
    drift = r * dt
    diffusion = sigma * math.sqrt(dt)

    path = []
    S = S0
    for z in normals:
        S = S * math.exp(drift + diffusion * z)
        path.append(S)
    return path
