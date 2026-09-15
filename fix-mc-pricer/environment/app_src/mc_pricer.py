"""Monte Carlo option pricing engine.
Supports three variance reduction strategies:
  - crude: no variance reduction
  - antithetic: antithetic variates
  - control_variate: geometric Asian control variate (for Asian options only)
"""
import math

from qrng_wrapper import SobolEngine, norm_inv
from gbm_paths import simulate_paths
from payoffs import european_call, european_put, asian_call, barrier_up_out_call
from geo_asian import geometric_asian_call


def _geo_avg_payoff(path, K, r, T):
    """Geometric-average call payoff for use as control variate."""
    g = 1.0
    for S in path:
        g *= S
    g = g ** (1.0 / len(path))
    return math.exp(-r * T) * max(g - K, 0.0)


def price_option(contract, n_paths=16384, method="antithetic"):
    """Price a single option contract via Quasi-Monte Carlo.

    Parameters
    ----------
    contract : dict  - must contain keys: type, S0, K, r, sigma, T
                       and optionally n_steps, barrier.
    n_paths  : int   - number of Sobol sample paths (should be power of 2).
    method   : str   - "crude", "antithetic", or "control_variate"

    Returns
    -------
    float - estimated discounted option price.
    """
    S0    = contract["S0"]
    K     = contract["K"]
    r     = contract["r"]
    sigma = contract["sigma"]
    T     = contract["T"]
    opt_type = contract["type"]

    n_steps = 1 if opt_type.startswith("european") else contract.get("n_steps", 4)

    engine = SobolEngine(n_steps)
    sobol_points = engine.generate(n_paths)

    payoffs_list = []
    geo_payoffs = []

    for i in range(n_paths):
        uniforms = sobol_points[i]

        # Transform Sobol uniforms -> standard normals
        normals = []
        for u in uniforms:
            u_c = max(1e-10, min(1.0 - 1e-10, u))
            normals.append(norm_inv(u_c))

        # Primary path
        path = simulate_paths(S0, r, sigma, T, n_steps, normals)

        # Evaluate payoff
        if opt_type == "european_call":
            p = european_call(path, K, r, T)
        elif opt_type == "european_put":
            p = european_put(path, K, r, T)
        elif opt_type == "asian_call":
            p = asian_call(path, K, r, T, S0)
        elif opt_type == "barrier_up_out_call":
            p = barrier_up_out_call(path, K, r, T, S0, contract["barrier"])
        else:
            raise ValueError(f"Unknown option type: {opt_type}")

        if method == "antithetic":
            # Antithetic variates
            anti_normals = [1.0 - z for z in normals]
            anti_path = simulate_paths(S0, r, sigma, T, n_steps, anti_normals)

            if opt_type == "european_call":
                p2 = european_call(anti_path, K, r, T)
            elif opt_type == "european_put":
                p2 = european_put(anti_path, K, r, T)
            elif opt_type == "asian_call":
                p2 = asian_call(anti_path, K, r, T, S0)
            elif opt_type == "barrier_up_out_call":
                p2 = barrier_up_out_call(anti_path, K, r, T, S0, contract["barrier"])
            p = 0.5 * (p + p2)

        payoffs_list.append(p)

        if method == "control_variate" and opt_type == "asian_call":
            geo_payoffs.append(_geo_avg_payoff(path, K, r, T))

    # Control variate adjustment for Asian options
    if method == "control_variate" and opt_type == "asian_call" and len(geo_payoffs) > 1:
        mean_p = sum(payoffs_list) / len(payoffs_list)
        mean_g = sum(geo_payoffs) / len(geo_payoffs)

        cov = sum((payoffs_list[i] - mean_p) * (geo_payoffs[i] - mean_g)
                  for i in range(len(payoffs_list))) / (len(payoffs_list) - 1)
        var_g = sum((geo_payoffs[i] - mean_g) ** 2
                    for i in range(len(payoffs_list))) / (len(payoffs_list) - 1)

        if var_g > 1e-15:
            beta = cov / var_g
            adjusted = [payoffs_list[i] - beta * geo_payoffs[i]
                        for i in range(len(payoffs_list))]
            return sum(adjusted) / len(adjusted)

    return sum(payoffs_list) / len(payoffs_list)
