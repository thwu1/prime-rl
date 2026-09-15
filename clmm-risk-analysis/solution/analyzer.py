#!/usr/bin/env python3
"""
CLMM Position Risk Analyzer with Options-Based Hedging.

Computes token amounts, position value, impermanent loss, analytical Greeks,
break-even volatility, and gamma-neutral hedge ratio for concentrated liquidity
AMM positions.
"""

import json
import math
from scipy.stats import norm


def load_json(path):
    with open(path) as f:
        return json.load(f)


def clmm_token_amounts(L, pa, pb, S):
    """Compute token X and Y amounts for a CLMM position."""
    sqrt_pa = math.sqrt(pa)
    sqrt_pb = math.sqrt(pb)
    sqrt_S = math.sqrt(S)

    if S < pa:
        x = L * (1.0 / sqrt_pa - 1.0 / sqrt_pb)
        y = 0.0
    elif S > pb:
        x = 0.0
        y = L * (sqrt_pb - sqrt_pa)
    else:
        x = L * (1.0 / sqrt_S - 1.0 / sqrt_pb)
        y = L * (sqrt_S - sqrt_pa)

    return x, y


def clmm_delta(L, pa, pb, S):
    """Analytical dV/dS for a CLMM position."""
    sqrt_pb = math.sqrt(pb)
    sqrt_pa = math.sqrt(pa)

    if S < pa:
        return L * (1.0 / sqrt_pa - 1.0 / sqrt_pb)
    elif S > pb:
        return 0.0
    else:
        return L * (1.0 / math.sqrt(S) - 1.0 / sqrt_pb)


def clmm_gamma(L, pa, pb, S):
    """Analytical d²V/dS² for a CLMM position."""
    if S < pa:
        return 0.0
    elif S > pb:
        return 0.0
    else:
        return -L / (2.0 * S ** 1.5)


def break_even_volatility(fee_income, L, S, days_per_year):
    """
    Compute annualized break-even volatility.

    Expected IL per day = |gamma| * sigma^2 * S^2 / (2 * days_per_year)
    where gamma = -L / (2 * S^1.5)
    So: expected IL per day = L * sigma^2 * sqrt(S) / (4 * days_per_year)

    Setting equal to fee_income:
    sigma_be = sqrt(4 * days_per_year * fee_income / (L * sqrt(S)))
    """
    sqrt_S = math.sqrt(S)
    return math.sqrt(4.0 * days_per_year * fee_income / (L * sqrt_S))


def straddle_gamma(S, sigma, r, T):
    """ATM straddle gamma using Black-Scholes."""
    d1 = (r + sigma ** 2 / 2.0) * math.sqrt(T) / sigma
    phi_d1 = norm.pdf(d1)
    gamma_call = phi_d1 / (S * sigma * math.sqrt(T))
    return 2.0 * gamma_call


def analyze_position(pos, market_data):
    """Run full analysis for a single CLMM position."""
    L = pos["liquidity"]
    pa = pos["price_lower"]
    pb = pos["price_upper"]
    S0 = pos["entry_price"]
    fee_tier = pos["fee_tier"]
    daily_volume = pos["daily_volume"]
    total_liquidity = pos["total_liquidity"]
    eval_prices = pos["eval_prices"]

    r = market_data["risk_free_rate"]
    sigma = market_data["implied_volatility"]
    T = market_data["option_expiry_days"] / market_data["days_per_year"]
    days_per_year = market_data["days_per_year"]

    # Entry-point values
    x0, y0 = clmm_token_amounts(L, pa, pb, S0)
    V0 = x0 * S0 + y0
    delta0 = clmm_delta(L, pa, pb, S0)
    gamma0 = clmm_gamma(L, pa, pb, S0)

    # Fee income
    fee_income = fee_tier * daily_volume * L / total_liquidity

    # Break-even volatility
    bev = break_even_volatility(fee_income, L, S0, days_per_year)

    # Gamma-neutral hedge
    gamma_straddle_val = straddle_gamma(S0, sigma, r, T)
    n_straddles = abs(gamma0) / gamma_straddle_val

    # Price grid analysis
    price_grid = []
    for S in eval_prices:
        x, y = clmm_token_amounts(L, pa, pb, S)
        value = x * S + y
        hold_value = x0 * S + y0
        il = value - hold_value
        delta = clmm_delta(L, pa, pb, S)
        gamma = clmm_gamma(L, pa, pb, S)

        price_grid.append({
            "price": S,
            "x": x,
            "y": y,
            "value": value,
            "hold_value": hold_value,
            "impermanent_loss": il,
            "delta": delta,
            "gamma": gamma,
        })

    return {
        "position_id": pos["id"],
        "entry_x": x0,
        "entry_y": y0,
        "entry_value": V0,
        "delta_at_entry": delta0,
        "gamma_at_entry": gamma0,
        "daily_fee_income": fee_income,
        "break_even_volatility_annual": bev,
        "hedge_straddles_count": n_straddles,
        "price_grid": price_grid,
    }


def main():
    positions = load_json("/app/positions.json")
    market_data = load_json("/app/market_data.json")

    results = {
        "positions": [analyze_position(pos, market_data) for pos in positions]
    }

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print("Analysis complete. Results written to /app/results.json")


if __name__ == "__main__":
    main()
