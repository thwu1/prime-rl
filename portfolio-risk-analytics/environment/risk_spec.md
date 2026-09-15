# Risk Report Specification

## Output

CSV at `/app/output/risk_report.csv` with columns (exact names, this order):

portfolio_id, total_return, ewma_volatility, cf_var_99, expected_shortfall_95, max_drawdown, sortino_ratio, beta, tracking_error

Round all values to 6 decimal places. Sort by portfolio_id ascending.

## Data Conventions

- Base currency: USD. Convert non-USD positions using daily FX rates; USD rate is 1.0 (not stored in database).
- Forward-fill missing FX rate entries where a rate is unavailable for a given trading date.
- Holdings are post-corporate-action quantities. Reverse recorded corporate actions to reconstruct historical positions.
- Returns must be total returns inclusive of reinvested dividends. The `dividends` table records per-share cash amounts and ex-dates in local currency.

## Metrics

**total_return** — Compounded total return over the full period.

**ewma_volatility** — Annualized terminal EWMA volatility estimate. Half-life = 60 trading days. RiskMetrics zero-mean recursive formulation, seeded with the first squared return.

**cf_var_99** — Cornish-Fisher VaR at 99% confidence. Apply the standard Cornish-Fisher expansion to the normal quantile using Fisher's unbiased estimators for skewness and excess kurtosis. Report as the adjusted return quantile (negative number).

**expected_shortfall_95** — Expected Shortfall at 95% confidence: conditional mean of daily returns at or below the 5th percentile.

**max_drawdown** — Maximum peak-to-trough decline from the cumulative wealth index.

**sortino_ratio** — Annualized Sortino ratio with 0% daily target return. Annualize via sqrt(252).

**beta** — CAPM beta from excess returns (net of daily risk-free rate). Sample covariance with ddof=1.

**tracking_error** — Annualized tracking error: standard deviation of active returns (ddof=1) times sqrt(252).

## References

- Benchmark for each portfolio: `portfolios.benchmark_id`
- Benchmark daily returns: `benchmark_returns` table
- Risk-free daily rate: `risk_free_rates` table
