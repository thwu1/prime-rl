FRED economic time series CSVs are at `/fred_data/`:
- `GDP.csv` — Quarterly nominal GDP (billions $, 1947–present)
- `CPIAUCSL.csv` — Monthly CPI-U (index 1982-84=100)
- `UNRATE.csv` — Monthly civilian unemployment rate (%)
- `FEDFUNDS.csv` — Monthly effective federal funds rate (%)
- `T10Y2Y.csv` — Daily 10-Year minus 2-Year Treasury constant-maturity spread (%), contains non-numeric entries for non-trading days

Each CSV has columns `observation_date` and the series name. Produce `/app/output/analysis.json` with six keys:

**`sahm_rule`**: The Claudia Sahm recession indicator for the full unemployment rate history, using the standard 0.50 percentage-point trigger threshold. Keys: `trigger_dates` (list of `YYYY-MM-01` strings where the indicator first breaches the threshold from below — a new trigger requires the indicator to have fallen back below the threshold since the previous trigger), `indicator` (dict mapping `YYYY-MM-01` → float for every month with sufficient data).

**`output_gap`**: A real GDP series constructed from nominal GDP and CPI, with the cyclical component extracted using the standard filtering approach for quarterly macroeconomic data. Express as percentage deviation of actual from trend. Keys: `lambda` (integer — the smoothing parameter used), `values` (dict mapping `YYYY-QN` → float, N is quarter 1–4).

**`taylor_rule`**: The prescribed federal funds rate from Taylor's original 1993 specification (r\*=2.0, π\*=2.0), using year-over-year CPI inflation and the output gap. Keys: `r_star` (2.0), `pi_star` (2.0), `prescribed_rates` (dict mapping `YYYY-MM-01` → float).

**`yield_curve_inversions`**: Contiguous episodes where the 10Y-2Y spread is negative, after removing non-numeric entries. Only report episodes spanning ≥5 trading days. List of objects: `start` (YYYY-MM-DD), `end` (YYYY-MM-DD), `duration_days` (int, trading days), `min_spread` (float, most negative value in episode).

**`real_fed_funds_rate`**: The ex-post real federal funds rate for each month. Dict mapping `YYYY-MM-01` → float.

**`monetary_stance`**: For each quarter where both actual and Taylor-prescribed rates are available, compute the quarterly average of each. Report the deviation (actual minus prescribed) and classify policy stance: "accommodative" if deviation < −2.0, "restrictive" if deviation > +2.0, "neutral" otherwise. Keys: `quarterly_deviation` (dict mapping `YYYY-QN` → float), `stance` (dict mapping `YYYY-QN` → string).

All float values rounded to 4 decimal places.