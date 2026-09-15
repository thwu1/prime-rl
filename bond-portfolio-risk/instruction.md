Build a fixed-income risk analytics engine using QuantLib Python. Given SOFR OIS market quotes and a portfolio of bonds (including a callable bond), produce a comprehensive analytics report.

## Inputs

- `/app/market_data.json` — SOFR OIS swap rate quotes for yield curve bootstrapping
- `/app/portfolio.json` — Bond specifications (4 fixed-rate, 1 callable), stress scenario definitions, key-rate tenor points

## Output

Write `/app/results.json` with three sections:

### Curve

Bootstrap a SOFR OIS discount curve from the provided quotes. Report continuous zero rates (in %) and discount factors at tenors 1Y, 5Y, 10Y, 20Y, 30Y relative to the evaluation date.

### Per-Bond Analytics

For each bond compute:
- `model_clean_price` — price from discounting off the bootstrapped curve. For the callable bond, use a Hull-White trinomial tree engine (100 time steps) with the model parameters given in the portfolio spec.
- `ytm_pct` — yield to maturity (%) from the quoted clean price. For the callable bond, compute as if it were a straight bond (ignore the call).
- `z_spread_bps` — Z-spread in basis points over the OIS curve. For the callable bond, compute as if straight.
- `oas_bps` — (callable bond only) option-adjusted spread in basis points via Hull-White tree.
- `modified_duration` — from the YTM. For the callable bond, treat as straight.
- `dv01_per_million_face` — modified_duration x (quoted_price / 100) x face_amount x 0.0001

### Portfolio Analytics

- `total_market_value` — sum of (quoted_price / 100) x face_amount across all bonds
- `portfolio_dv01` — sum of individual bond DV01s
- `scenarios` — for each scenario in the portfolio spec, compute total P&L (change in portfolio model value vs. base model value using a discounting engine for all bonds). Parallel: uniform zero-rate spread. Twist: linearly interpolated time-varying spread between short and long end dates.
- `key_rate_durations` — for each key-rate tenor, apply a localized 1bp upward bump with linear interpolation between adjacent tenors. KRD = -(delta_V / V) / 0.0001 where V is total base model value.

## Conventions

| Parameter | Value |
|---|---|
| Calendar | US Government Bond |
| Curve day counter | Actual/360 |
| Bond day counter | 30/360 BondBasis |
| Coupon frequency | Semiannual |
| Yield compounding | Compounded, Semiannual |
| Bond schedule convention | Unadjusted |
| OIS settlement | T+2 |
| OIS payment frequency | Annual |

## Output JSON Structure

```json
{
  "curve": {
    "zero_rates_continuous_pct": {"1Y": ..., "5Y": ..., "10Y": ..., "20Y": ..., "30Y": ...},
    "discount_factors": {"1Y": ..., "5Y": ..., "10Y": ..., "20Y": ..., "30Y": ...}
  },
  "bonds": {
    "<bond_id>": {
      "model_clean_price": ...,
      "ytm_pct": ...,
      "z_spread_bps": ...,
      "modified_duration": ...,
      "dv01_per_million_face": ...,
      "oas_bps": ...
    }
  },
  "portfolio": {
    "total_market_value": ...,
    "portfolio_dv01": ...,
    "scenarios": {"parallel_up_100bp": ..., "parallel_down_100bp": ..., "flattening": ..., "steepening": ...},
    "key_rate_durations": {"2Y": ..., "5Y": ..., "10Y": ..., "20Y": ..., "30Y": ...}
  }
}
```