You are given three years of hourly electrical load and temperature data for a utility zone (2019-01-01 through 2021-12-31). Produce a one-month-ahead **probabilistic** forecast for January 2022: the 99 quantiles (tau = 0.01 through 0.99) of the load distribution for each hour.

## Data

- `/app/data/train.csv` — Hourly training data. Columns: `datetime`, `temperature` (°C), `load` (MW).
- `/app/data/test_temperatures.csv` — Temperature forecasts for January 2022 (hourly). Columns: `datetime`, `temperature`.
- `/app/data/holidays.csv` — Public holiday dates. Column: `date`.

## Output

Write your forecast to `/app/output/forecast.csv` with columns:
- `datetime` — matching timestamps in `test_temperatures.csv`, formatted as `YYYY-MM-DD HH:MM:SS`
- `q01`, `q02`, ..., `q99` — quantile forecasts for tau = 0.01, 0.02, ..., 0.99

The file must contain exactly 744 rows (one per hour of January 2022) and 100 columns (datetime + 99 quantiles).

## Constraints

All quantile values must satisfy:
- **Finite**: no NaN or Inf values.
- **Non-negative**: load forecasts cannot be negative (load is in MW).
- **Non-decreasing**: quantiles must be monotonically non-decreasing for each hour (no quantile crossing), i.e., q_tau1 <= q_tau2 whenever tau1 < tau2.
- **Physically reasonable median**: the mean of the median forecast (q50) across all 744 hours must be between 500 and 5000 MW.
- **Meaningful uncertainty**: the mean width of the 90% prediction interval (q95 minus q05) across all hours must be between 20 and 2000 MW.

## Scoring

Your forecast is evaluated using the **mean pinball loss** averaged across all 99 quantiles and all 744 hours:

    L(y, q, tau) = tau * (y - q)       if y >= q
    L(y, q, tau) = (1 - tau) * (q - y) if y < q

Your mean pinball loss must be below **45.0 MW**.