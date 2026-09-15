
"""
Heston stochastic volatility model calibration engine.

Implements:
1. Heston characteristic function (stable formulation, vectorized)
2. COS Fourier-cosine expansion pricing (fully vectorized)
3. Joint multi-maturity calibration via differential evolution + L-BFGS-B
4. Greeks computation via finite differences
5. Implied volatility extraction via bisection
"""

import json
import math
import numpy as np
import scipy.stats as st
import scipy.optimize as optimize


# ---------------------------------------------------------------------------
# 1. Heston characteristic function — stable "Little Trap" formulation
#    Fully vectorized: accepts u as an ndarray and returns an ndarray.
# ---------------------------------------------------------------------------

def heston_cf(u, r, tau, kappa, gamma, vbar, v0, rho):
    i = 1j
    u = np.asarray(u, dtype=complex)

    d = np.sqrt((kappa - gamma * rho * i * u) ** 2
                + (u * u + i * u) * gamma ** 2)

    g = (kappa - gamma * rho * i * u - d) / \
        (kappa - gamma * rho * i * u + d)

    exp_neg_d_tau = np.exp(-d * tau)

    C = ((1.0 - exp_neg_d_tau)
         / (gamma ** 2 * (1.0 - g * exp_neg_d_tau))
         * (kappa - gamma * rho * i * u - d))

    A = (r * i * u * tau
         + kappa * vbar * tau / gamma ** 2
         * (kappa - gamma * rho * i * u - d)
         - 2.0 * kappa * vbar / gamma ** 2
         * np.log((1.0 - g * exp_neg_d_tau) / (1.0 - g)))

    return np.exp(A + C * v0)


# ---------------------------------------------------------------------------
# 2. COS method — fully vectorized (no Python loop over u)
# ---------------------------------------------------------------------------

def cos_price_call(S0, r, tau, K_arr, kappa, gamma, vbar, v0, rho,
                   N=2048, L=10):
    i = 1j
    K_arr = np.asarray(K_arr, dtype=float).reshape(-1, 1)
    x0 = np.log(S0 / K_arr)          # (nK, 1)

    a = -L * np.sqrt(tau)
    b =  L * np.sqrt(tau)

    k = np.arange(N, dtype=float).reshape(N, 1)
    u = k * np.pi / (b - a)          # (N, 1)

    # Put cosine coefficients  [c, d] = [a, 0]
    c_lo, d_hi = a, 0.0

    psi = (np.sin(k * np.pi * (d_hi - a) / (b - a))
           - np.sin(k * np.pi * (c_lo - a) / (b - a)))
    psi[1:] = psi[1:] * (b - a) / (k[1:] * np.pi)
    psi[0] = d_hi - c_lo

    chi = 1.0 / (1.0 + (k * np.pi / (b - a)) ** 2)
    expr1 = (np.cos(k * np.pi * (d_hi - a) / (b - a)) * np.exp(d_hi)
             - np.cos(k * np.pi * (c_lo - a) / (b - a)) * np.exp(c_lo))
    expr2 = (k * np.pi / (b - a)
             * np.sin(k * np.pi * (d_hi - a) / (b - a))
             - k * np.pi / (b - a)
             * np.sin(k * np.pi * (c_lo - a) / (b - a)) * np.exp(c_lo))
    chi = chi * (expr1 + expr2)

    H_k = 2.0 / (b - a) * (-chi + psi)        # (N, 1)

    # Vectorized CF evaluation — pass whole u array
    cf_vals = heston_cf(u.flatten(), r, tau, kappa, gamma, vbar, v0, rho)
    cf_vals = cf_vals.reshape(N, 1)

    mat = np.exp(i * np.outer(x0.flatten() - a, u.flatten()))  # (nK, N)
    temp = cf_vals * H_k                                        # (N, 1)
    temp[0] = 0.5 * temp[0]

    put_value = np.exp(-r * tau) * K_arr * np.real(mat @ temp)
    call_value = put_value + S0 - K_arr * np.exp(-r * tau)
    return call_value.flatten()


# ---------------------------------------------------------------------------
# 3. Black-Scholes helpers
# ---------------------------------------------------------------------------

def bs_call(S0, K, sigma, T, r):
    d1 = (math.log(S0 / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return st.norm.cdf(d1) * S0 - st.norm.cdf(d2) * K * math.exp(-r * T)


def implied_vol(price, S0, K, T, r, tol=1e-12):
    if price <= 0 or price >= S0:
        return 0.0
    lo, hi = 0.001, 3.0
    for _ in range(300):
        mid = (lo + hi) / 2.0
        p = bs_call(S0, K, mid, T, r)
        if p < price:
            lo = mid
        else:
            hi = mid
        if hi - lo < tol:
            break
    return (lo + hi) / 2.0


# ---------------------------------------------------------------------------
# 4. Calibration
# ---------------------------------------------------------------------------

def calibrate(market_data, config):
    S0 = market_data["S0"]
    r = market_data["r"]
    maturities = market_data["maturities"]
    strikes = market_data["strikes"]
    market_prices = market_data["call_prices"]

    bounds = config["parameter_bounds"]

    def objective(params):
        kappa, gamma, vbar, v0, rho = params
        total_err = 0.0
        for T in maturities:
            T_str = str(T)
            model = cos_price_call(S0, r, T, strikes,
                                   kappa, gamma, vbar, v0, rho,
                                   N=1024, L=10)
            mkt = np.array(market_prices[T_str])
            mask = mkt > 0.01
            rel_err = ((model[mask] - mkt[mask]) / mkt[mask]) ** 2
            total_err += np.sum(rel_err)
        return total_err

    opt_bounds = [
        tuple(bounds["kappa"]),
        tuple(bounds["gamma"]),
        tuple(bounds["vbar"]),
        tuple(bounds["v0"]),
        tuple(bounds["rho"]),
    ]

    # Global search
    result = optimize.differential_evolution(
        objective,
        bounds=opt_bounds,
        seed=42,
        maxiter=150,
        tol=1e-12,
        polish=False,
        mutation=(0.5, 1.5),
        recombination=0.9,
        popsize=20,
    )

    # Local refinement
    result_local = optimize.minimize(
        objective,
        result.x,
        method="L-BFGS-B",
        bounds=opt_bounds,
        options={"maxiter": 500, "ftol": 1e-15},
    )

    params = result_local.x
    return {
        "kappa": float(params[0]),
        "gamma": float(params[1]),
        "vbar": float(params[2]),
        "v0": float(params[3]),
        "rho": float(params[4]),
    }


# ---------------------------------------------------------------------------
# 5. Greeks via finite differences
# ---------------------------------------------------------------------------

def compute_greeks(params, S0, r, T, strikes_greeks):
    kappa = params["kappa"]
    gamma = params["gamma"]
    vbar = params["vbar"]
    v0 = params["v0"]
    rho = params["rho"]

    bump_S = 0.01
    bump_v = 0.001

    prices_base = cos_price_call(S0, r, T, strikes_greeks,
                                 kappa, gamma, vbar, v0, rho)
    prices_up = cos_price_call(S0 + bump_S, r, T, strikes_greeks,
                               kappa, gamma, vbar, v0, rho)
    prices_dn = cos_price_call(S0 - bump_S, r, T, strikes_greeks,
                               kappa, gamma, vbar, v0, rho)
    deltas = (prices_up - prices_dn) / (2 * bump_S)
    gammas = (prices_up + prices_dn - 2 * prices_base) / (bump_S ** 2)

    prices_vup = cos_price_call(S0, r, T, strikes_greeks,
                                kappa, gamma, vbar, v0 + bump_v, rho)
    prices_vdn = cos_price_call(S0, r, T, strikes_greeks,
                                kappa, gamma, vbar, v0 - bump_v, rho)
    vegas = (prices_vup - prices_vdn) / (2 * bump_v)

    greeks = {}
    for j, K in enumerate(strikes_greeks):
        greeks[str(float(K))] = {
            "delta": round(float(deltas[j]), 6),
            "gamma_greek": round(float(gammas[j]), 6),
            "vega": round(float(vegas[j]), 6),
        }
    return greeks


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    with open("/app/market_data.json") as f:
        market_data = json.load(f)
    with open("/app/config.json") as f:
        config = json.load(f)

    S0 = market_data["S0"]
    r = market_data["r"]
    maturities = market_data["maturities"]
    strikes = market_data["strikes"]

    print("Starting calibration...")
    params = calibrate(market_data, config)
    print(f"Calibrated parameters: {params}")

    # Model prices and implied vols with higher N for final output
    model_prices = {}
    model_ivs = {}
    for T in maturities:
        T_str = str(T)
        prices = cos_price_call(S0, r, T, strikes,
                                params["kappa"], params["gamma"],
                                params["vbar"], params["v0"], params["rho"],
                                N=4096, L=12)
        model_prices[T_str] = [round(float(p), 8) for p in prices]

        ivs = []
        for j, K in enumerate(strikes):
            iv = implied_vol(float(prices[j]), S0, K, T, r)
            ivs.append(round(iv, 6))
        model_ivs[T_str] = ivs

    # Greeks
    greeks_spec = market_data["greeks_spec"]
    greeks = compute_greeks(
        params, S0, r,
        greeks_spec["maturity"],
        greeks_spec["strikes"],
    )

    results = {
        "calibrated_params": params,
        "model_prices": model_prices,
        "model_implied_vols": model_ivs,
        "greeks": greeks,
    }

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print("Results written to /app/results.json")


if __name__ == "__main__":
    main()
