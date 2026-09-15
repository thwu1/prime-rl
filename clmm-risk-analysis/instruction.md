Build a risk analysis engine for concentrated liquidity market maker (CLMM) positions that computes impermanent loss, analytical Greeks, break-even volatility, and options-based gamma hedging.

## Input

- `/app/positions.json` — Array of CLMM positions, each with: `liquidity` (L), `price_lower` (pa), `price_upper` (pb), `entry_price` (S0), `fee_tier`, `daily_volume`, `total_liquidity`, and `eval_prices` (price grid for analysis).
- `/app/market_data.json` — Contains `risk_free_rate` (r), `implied_volatility` (sigma), `option_expiry_days`, and `days_per_year`.

## Task

Write `/app/analyzer.py` (run via `python3 /app/analyzer.py`) that reads the inputs and writes `/app/results.json`.

For each position, at each price S in its `eval_prices` grid, compute the CLMM position's token amounts, value, impermanent loss, and analytical Greeks. A CLMM position with liquidity L in range [pa, pb] holds:

- In range (pa <= S <= pb): x(S) = L(1/sqrt(S) - 1/sqrt(pb)), y(S) = L(sqrt(S) - sqrt(pa))
- Below range (S < pa): x = L(1/sqrt(pa) - 1/sqrt(pb)), y = 0
- Above range (S > pb): x = 0, y = L(sqrt(pb) - sqrt(pa))

Position value V(S) = x(S)*S + y(S). Hold value = x0*S + y0 where x0, y0 are token amounts at entry price. Impermanent loss = V(S) - hold value. Delta = dV/dS and gamma = d^2V/dS^2 (compute analytically; at range boundaries use in-range formulas).

For each position at entry price, also compute:

1. **Daily fee income**: fee_tier * daily_volume * L / total_liquidity
2. **Break-even annualized volatility**: the realized vol at which expected IL rate equals fee income. Use the gamma-based IL approximation: expected IL per day = |gamma| * sigma^2 * S^2 / (2 * days_per_year). Set equal to daily fee income and solve for sigma.
3. **Gamma-neutral hedge straddle count**: number of ATM straddles (K = S0) to neutralize gamma at entry. Use Black-Scholes: ATM straddle gamma = 2 * phi(d1) / (S * sigma * sqrt(T)), where d1 = (r + sigma^2/2) * sqrt(T) / sigma, T = option_expiry_days / days_per_year, phi is the standard normal PDF.

## Output format (`/app/results.json`)

```json
{
  "positions": [
    {
      "position_id": 0,
      "entry_x": ..., "entry_y": ..., "entry_value": ...,
      "delta_at_entry": ..., "gamma_at_entry": ...,
      "daily_fee_income": ...,
      "break_even_volatility_annual": ...,
      "hedge_straddles_count": ...,
      "price_grid": [
        {"price": ..., "x": ..., "y": ..., "value": ..., "hold_value": ..., "impermanent_loss": ..., "delta": ..., "gamma": ...},
        ...
      ]
    },
    ...
  ]
}
```