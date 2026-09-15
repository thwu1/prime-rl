Eight FRED economic time series are available as CSV files in `/app/data/`: CPIAUCSL (CPI for All Urban Consumers), GDP (Gross Domestic Product, nominal SAAR), FEDFUNDS (Effective Federal Funds Rate), UNRATE (Civilian Unemployment Rate), M2SL (M2 Money Stock), DGS10 (10-Year Treasury Constant Maturity Rate), T10Y2Y (10-Year Minus 2-Year Treasury Spread), and PAYEMS (Total Nonfarm Payrolls). These series span different date ranges and are published at different frequencies. Examine them carefully — their characteristics vary and must be handled appropriately to produce correct results.

Produce `/app/output/indicators.json` containing a unified monthly macroeconomic analysis for January 1977 through December 2025 (588 months). The output must conform to this structure:

```json
{
  "metadata": {"start_date": "1977-01", "end_date": "2025-12", "num_months": 588, "series_used": [...]},
  "monthly_data": {
    "YYYY-MM": {
      "cpi": ...,
      "cpi_yoy_inflation": ...,
      "fedfunds": ...,
      "real_fed_funds_rate": ...,
      "unrate": ...,
      "sahm_rule_indicator": ...,
      "m2_velocity": ...,
      "taylor_rule_rate": ...,
      "taylor_gap": ...,
      "t10y2y_monthly_avg": ...,
      "dgs10_monthly_avg": ...,
      "payroll_momentum": ...
    }
  },
  "inversion_episodes": [
    {"start_month": ..., "end_month": ..., "duration_months": ..., "min_monthly_avg_spread": ..., "mean_monthly_avg_spread": ...}
  ],
  "sahm_rule_triggers": ["YYYY-MM", ...],
  "summary": {
    "total_months": 588,
    "max_inflation": {"date": ..., "value": ...},
    "min_real_rate": {"date": ..., "value": ...},
    "max_taylor_gap": {"date": ..., "value": ...},
    "num_inversion_episodes": ...,
    "num_sahm_triggers": ...,
    "longest_inversion_months": ...
  }
}
```

Field definitions:

- `real_fed_funds_rate`: ex-post real federal funds rate
- `sahm_rule_indicator`: Claudia Sahm's real-time recession indicator
- `sahm_rule_triggers`: months where the indicator reaches the standard recession-signal threshold
- `m2_velocity`: velocity of M2 money stock
- `taylor_rule_rate`: Taylor (1993) Rule prescribed federal funds rate
- `taylor_gap`: Taylor Rule prescribed rate minus actual federal funds rate
- `inversion_episodes`: contiguous periods where the yield curve was inverted on a monthly-average basis
- `payroll_momentum`: short-term smoothed trend in month-over-month nonfarm payroll changes

Use `null` for months where a value cannot be computed. No NaN values (string or float) permitted anywhere in the output. Sahm trigger dates must be sorted chronologically.