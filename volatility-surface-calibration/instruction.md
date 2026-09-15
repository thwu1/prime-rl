Build an options volatility surface calibration engine from European index option market data. Write all outputs to `/app/output/`.

## Input Data

- `/app/data/option_chain.csv` — European index options (underlying at 5000). Columns: `expiry_days,strike,option_type,mid_price,underlying_price,risk_free_rate,dividend_yield`. Five expiration slices (30, 90, 180, 365, 730 days), 17 strikes each.
- `/app/data/exotic_specs.json` — Four exotic contracts: down-and-out call, up-and-out call, arithmetic Asian call, down-and-in put.
- `/app/data/portfolio.json` — Short iron condor (four legs) for Greeks aggregation.

## SVI Total Variance Model

For each slice, fit raw SVI to total implied variance `w(k) = a + b * (rho * (k - m) + sqrt((k - m)^2 + sigma^2))` where `k = ln(K/F)`, `F = S*exp((r-q)*T)`. Constraints: `b >= 0`, `-1 < rho < 1`, `sigma > 0`.

## Required Outputs

**`implied_vols.csv`** — One row per input option. Columns: `expiry_days,strike,option_type,implied_vol`. Newton-Raphson with bisection fallback. Roundtrip accuracy: `|BS(IV) - market_price| < 0.05`.

**`svi_params.json`** — Keyed by `expiry_days` (string). Each value: `{"a", "b", "rho", "m", "sigma"}`. Average call/put IVs per strike before fitting. Per-slice RMSE of fitted vs. market total variance `< 5e-5`.

**`arbitrage_check.json`** — `{"butterfly_free": bool, "calendar_free": bool}`. Butterfly: Durrleman's condition `g(k) >= 0` where `g(k) = (1 - k*w'/(2w))^2 - (w')^2*(1/w + 1/4)/4 + w''/2`, evaluated across `k in [-0.5, 0.5]` with `>= 200` points per slice. Calendar: total variance `w(k,T)` non-decreasing in T at each chain strike.

**`exotic_prices.json`** — Keyed by exotic name. Each: `{"price": float, "std_error": float}`. Use `numpy.random.default_rng(42)`, `>= 200,000` paths, `>= 252` steps/year. For each exotic, determine its BS implied vol from the calibrated SVI surface at its log-forward-moneyness (interpolate total variance between bracketing slices if needed). Constant vol GBM. Barrier: continuous monitoring. Asian: daily monitoring.

**`portfolio_greeks.json`** — `{"delta", "gamma", "vega", "theta", "rho"}`. Analytical BS Greeks at each position's IV. Theta per calendar day. Vega per unit sigma change. Aggregate with position sign and quantity.