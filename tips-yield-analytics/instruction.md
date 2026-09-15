Build a data pipeline and analytics CLI at `/app/` that ingests U.S. Treasury data into SQLite and serves fixed-income queries.

**Data** at `/app/data/`: `nominal_yields.xml`, `real_yields.xml` (XML feeds of daily Treasury par yield curves), `h15_rates.csv` (Fed H.15 selected interest rates; metadata header rows; `ND` = non-trading), `tips_securities.json` (TIPS auction records with golden ref-CPI and index-ratio values), `cpi_u_nsa.csv` (FRED monthly CPI-U NSA). Available tools: `xsltproc`, `sqlite3`, `make`, `python3`.

**Required files:**

`/app/xsl/nominal.xsl`, `/app/xsl/real.xsl` — Running `xsltproc /app/xsl/nominal.xsl /app/data/nominal_yields.xml` must emit headerless CSV. Nominal: 14 columns (date + 13 tenors by ascending maturity: 1Mo, 2Mo, 3Mo, 4Mo, 6Mo, 1Yr, 2Yr, 3Yr, 5Yr, 7Yr, 10Yr, 20Yr, 30Yr), dates `YYYY-MM-DD`, >200 rows. Real: 6 columns (date + 5Yr, 7Yr, 10Yr, 20Yr, 30Yr), >200 rows.

`/app/schema.sql` — DDL for: `nominal_yields(date TEXT, tenor REAL, rate REAL)`, `real_yields(date TEXT, tenor REAL, rate REAL)`, `h15_rates(date TEXT, series_id TEXT, rate REAL)`, `cpi_monthly(year INT, month INT, value REAL)`, `tips_securities(cusip TEXT, issue_date TEXT, maturity_date TEXT, interest_rate REAL, ref_cpi_issue REAL, ref_cpi_dated REAL, index_ratio_issue REAL)`. Uniqueness constraints must prevent duplicate inserts.

`/app/Makefile` — `make db` produces `/app/treasury.db` from all five sources; idempotent. `make clean` removes all generated artifacts. Expected row counts: >2000 nominal (13 tenors/day), >1000 real (5 tenors/day), >2000 h15, >=48 cpi, >=50 tips. `make clean && make db` must succeed with analytics intact afterward.

`/app/tips_analytics.py` — Python CLI outputting JSON to stdout:

- `ref-cpi --date YYYY-MM-DD` → `{"date": str, "ref_cpi": float}`. Daily Treasury Reference CPI. Exit non-zero when CPI data is insufficient.
- `index-ratio --date YYYY-MM-DD --cusip CUSIP` → `{"date": str, "cusip": str, "ref_cpi_settlement": float, "ref_cpi_base": float, "index_ratio": float, "floored_index_ratio": float}`. Deflation floor: `floored_index_ratio = max(1.0, index_ratio)`.
- `bootstrap --date MM/DD/YYYY --curve nominal|real` → `{"date": str, "curve_type": str, "tenors": [float], "spot_rates": [float], "discount_factors": [float], "max_roundtrip_error_bps": float}`. Zero-coupon spot rates, semi-annual compounding. Tenors in fractional years, rates in percent. Spot rates must be positive; discount factors strictly decreasing. Roundtrip par-price error < 0.1 bps. Nominal: 13 tenors; real: 5.
- `forward-breakeven --date MM/DD/YYYY` → `{"par_breakeven": {"5": float, "7": float, "10": float, "20": float, "30": float}, "forward_5y5y_nominal": float, "forward_5y5y_real": float, "forward_5y5y_breakeven": float}`. All forward rates positive. Consistency: `forward_5y5y_breakeven = forward_5y5y_nominal - forward_5y5y_real` (within 0.01).
- `validate` → `{"total_checked": int, "passed": int, "max_ref_cpi_error": float, "max_index_ratio_error": float, "failures": list}`. Verify computed values against golden data in `tips_securities`. Tolerances: ref_cpi error < 0.001, index_ratio error < 0.00005. >=50 records checked, >=95% pass rate.
- `reconcile --date YYYY-MM-DD` → `{"date": str, "matched_tenors": int, "max_abs_diff": float, "diffs": dict}`. Cross-reference nominal yields vs H.15 at 11 common tenors. `max_abs_diff` < 0.01. Exit non-zero for non-trading days.
