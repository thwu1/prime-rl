#!/usr/bin/env python3
"""Generate synthetic market data from a Heston stochastic volatility model.

Produces European call option prices via COS (Fourier cosine expansion) method
for use as calibration targets in the SZHW model calibration task.
"""
import numpy as np
import json

I_UNIT = complex(0.0, 1.0)


def heston_cf_frwd(u, r, tau, kappa, gamma, vbar, v0, rho):
    """Heston model characteristic function (forward formulation).

    Includes discounting term (-r*tau) in A so the COS method produces
    discounted option prices directly.
    """
    D1 = np.sqrt((kappa - gamma * rho * I_UNIT * u) ** 2
                 + (u * u + I_UNIT * u) * gamma ** 2)
    g = ((kappa - gamma * rho * I_UNIT * u - D1)
         / (kappa - gamma * rho * I_UNIT * u + D1))
    C = ((1.0 - np.exp(-D1 * tau))
         / (gamma ** 2 * (1.0 - g * np.exp(-D1 * tau)))
         * (kappa - gamma * rho * I_UNIT * u - D1))
    A = (-r * tau
         + r * I_UNIT * u * tau
         + kappa * vbar * tau / (gamma ** 2)
         * (kappa - gamma * rho * I_UNIT * u - D1)
         - 2.0 * kappa * vbar / (gamma ** 2)
         * np.log((1.0 - g * np.exp(-D1 * tau)) / (1.0 - g)))
    return np.exp(A + C * v0)


def chi_psi(a, b, c, d, k):
    """Compute Chi and Psi coefficients for the COS method."""
    psi = (np.sin(k * np.pi * (d - a) / (b - a))
           - np.sin(k * np.pi * (c - a) / (b - a)))
    psi[1:] = psi[1:] * (b - a) / (k[1:] * np.pi)
    psi[0] = d - c

    chi = 1.0 / (1.0 + np.power(k * np.pi / (b - a), 2.0))
    expr1 = (np.cos(k * np.pi * (d - a) / (b - a)) * np.exp(d)
             - np.cos(k * np.pi * (c - a) / (b - a)) * np.exp(c))
    expr2 = (k * np.pi / (b - a)
             * np.sin(k * np.pi * (d - a) / (b - a))
             - k * np.pi / (b - a)
             * np.sin(k * np.pi * (c - a) / (b - a)) * np.exp(c))
    chi = chi * (expr1 + expr2)
    return chi, psi


def cos_call_prices(cf_func, S0, tau, K_list, r, N=2000, L=15):
    """COS method for European call option pricing.

    Computes put prices via cosine expansion, then uses put-call parity.
    """
    P0T = np.exp(-r * tau)
    K = np.array(K_list).reshape([len(K_list), 1])
    x0 = np.log(S0 / K)
    a = -L * np.sqrt(tau)
    b = L * np.sqrt(tau)
    k = np.linspace(0, N - 1, N).reshape([N, 1])
    u = k * np.pi / (b - a)

    # Put coefficients (c=a, d=0)
    chi, psi = chi_psi(a, b, a, 0.0, k)
    H_k = 2.0 / (b - a) * (-chi + psi)

    mat = np.exp(I_UNIT * np.outer((x0 - a), u))
    cf_vals = cf_func(u)
    temp = cf_vals * H_k
    temp[0] = 0.5 * temp[0]
    put_value = K * np.real(mat.dot(temp))
    call_value = put_value + S0 - K * P0T
    return call_value


def main():
    # Market / asset parameters
    S0 = 100.0
    r = 0.03
    T = 5.0

    # Heston model parameters (used to generate "market" prices)
    kappa_h = 0.5
    gamma_h = 0.4
    vbar_h = 0.08
    v0_h = 0.04
    rho_h = -0.65

    strikes = np.linspace(60.0, 160.0, 15).tolist()

    cf = lambda u: heston_cf_frwd(u, r, T, kappa_h, gamma_h, vbar_h, v0_h, rho_h)
    prices = cos_call_prices(cf, S0, T, strikes, r)

    market_data = {
        "S0": S0,
        "r": r,
        "T": T,
        "strikes": strikes,
        "call_prices": [round(float(p), 10) for p in prices.flatten()],
        "szhw_fixed_params": {
            "kappa": 0.5,
            "Rxr": 0.3,
            "lambd": 1.0,
            "eta": 0.02
        }
    }

    with open("/app/market_data.json", "w") as f:
        json.dump(market_data, f, indent=2)

    print("Market data generated successfully.")
    for k_val, p_val in zip(strikes, market_data["call_prices"]):
        print(f"  K={k_val:.1f}: price={p_val:.6f}")


if __name__ == "__main__":
    main()
