# Risk Metrics Specification

All metrics are computed from daily simple returns: r_t = V_t / V_{t-1} - 1

Portfolio value on each day: V_t = sum over all holdings of (quantity_t × close_price_t × fx_rate_to_usd_t)

## Output Format

CSV file at `/app/output/risk_report.csv` with columns in this exact order:

portfolio_id, total_return, ann_volatility, sharpe_ratio, max_drawdown, var_95, var_99, beta, tracking_error, information_ratio

## Metric Definitions

Let r = {r_1, r_2, ..., r_n} be the series of daily simple returns of a portfolio.

- **total_return**: V_last / V_first - 1
- **ann_volatility**: std(r, ddof=1) × sqrt(252)
- **sharpe_ratio**: mean(r - r_f) / std(r, ddof=1) × sqrt(252), where r_f is the daily risk-free rate
- **max_drawdown**: min_t((W_t / max_{s<=t} W_s) - 1), where W_t = prod_{i=1}^{t}(1 + r_i)
- **var_95**: numpy.percentile(r, 5) using linear interpolation
- **var_99**: numpy.percentile(r, 1) using linear interpolation
- **beta**: cov(r, r_b)[0,1] / var(r_b), where r_b is the benchmark return series, using numpy.cov (ddof=1 default)
- **tracking_error**: std(r - r_b, ddof=1) × sqrt(252)
- **information_ratio**: mean(r - r_b) / std(r - r_b, ddof=1) × sqrt(252)

## Notes

- Each portfolio's benchmark is specified by the `benchmark_id` column in the `portfolios` table
- All portfolio values must be denominated in USD
- Round all output values to 6 decimal places
- Sort output rows by portfolio_id ascending
