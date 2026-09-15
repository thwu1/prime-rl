"""Monte Carlo option pricing engine.

Uses Sobol quasi-random sequences with antithetic variates
for variance reduction.
"""
from sobol import SobolEngine
from norm_inv import norm_inv
from gbm_paths import simulate_paths
from payoffs import european_call, european_put, asian_call


def price_option(contract, n_paths=8192):
    """Price a single option contract via Quasi-Monte Carlo.

    Parameters
    ----------
    contract : dict  – must contain keys: type, S0, K, r, sigma, T
                       and optionally n_steps (for path-dependent types).
    n_paths  : int   – number of Sobol sample paths (should be power of 2).

    Returns
    -------
    float – estimated discounted option price.
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

    payoff_sum = 0.0
    for i in range(n_paths):
        uniforms = sobol_points[i]

        # Transform Sobol uniforms → standard normals
        normals = []
        for u in uniforms:
            u_c = max(1e-10, min(1.0 - 1e-10, u))
            normals.append(norm_inv(u_c))

        # Primary path
        path = simulate_paths(S0, r, sigma, T, n_steps, normals)

        # Antithetic path
        anti_normals = [1.0 - z for z in normals]
        anti_path = simulate_paths(S0, r, sigma, T, n_steps, anti_normals)

        # Evaluate payoffs
        if opt_type == "european_call":
            p1 = european_call(path, K, r, T)
            p2 = european_call(anti_path, K, r, T)
        elif opt_type == "european_put":
            p1 = european_put(path, K, r, T)
            p2 = european_put(anti_path, K, r, T)
        elif opt_type == "asian_call":
            p1 = asian_call(path, K, r, T, S0)
            p2 = asian_call(anti_path, K, r, T, S0)
        else:
            raise ValueError(f"Unknown option type: {opt_type}")

        payoff_sum += 0.5 * (p1 + p2)

    return payoff_sum / n_paths
