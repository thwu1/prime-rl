Implement two components in `/app/`:

**1. `/app/muni_calc.py`** -- Municipal bond pricing engine conforming to MSRB Rule G-33.

CLI: `python3 /app/muni_calc.py <input.json>` reads a JSON trade specification, writes JSON to stdout, exits 0.

Input schema (rates as decimals, e.g. 0.05 = 5%):

```json
{
  "security_type": "periodic|at_redemption|discounted",
  "coupon_rate": 0.05,
  "settlement_date": "YYYY-MM-DD",
  "maturity_date": "YYYY-MM-DD",
  "dated_date": "YYYY-MM-DD",
  "first_coupon_date": "YYYY-MM-DD",
  "frequency": 2,
  "redemption_value": 100.0,
  "compute": "price|yield",
  "yield_input": 0.04,
  "price_input": null,
  "discount_rate": null,
  "call_schedule": [{"date": "YYYY-MM-DD", "price": 102.0}]
}
```

`frequency`: coupon payments per year (2=semi-annual, 4=quarterly). `discount_rate`: used only for discounted securities with `compute=price`.

Output schema:

```json
{
  "accrued_interest": 1.25,
  "dollar_price": 104.491,
  "yield": 0.040,
  "yield_to_worst": 0.038,
  "worst_date": "2027-01-01",
  "worst_rv": 102.0
}
```

When `call_schedule` is absent or empty, `yield_to_worst`, `worst_date`, and `worst_rv` must be `null`.

The G-33 specification is at `/app/specs/rule_g33.txt`.

**2. `/app/reconcile.sh`** -- Trade reconciliation pipeline (shell script).

Run: `bash /app/reconcile.sh` (no arguments).

Reads:
- `/app/data/trades.csv` -- pipe-delimited trade records with header
- `/app/data/call_schedules.json` -- call schedules keyed by trade_id
- `/app/data/vendor_report.csv` -- pipe-delimited vendor valuations with header

Computes G-33-conforming valuations for each trade via `/app/muni_calc.py`, compares against vendor values, and produces two outputs:

**`/app/output/audit.db`** -- SQLite database with tables:
- `trades` -- columns from trades.csv headers, `trade_id TEXT PRIMARY KEY`
- `computed_values` -- `trade_id TEXT PRIMARY KEY, accrued_interest REAL, dollar_price REAL, yield REAL, yield_to_worst REAL, worst_date TEXT, worst_rv REAL`
- `vendor_values` -- same column schema as `computed_values`
- `discrepancies` -- `trade_id TEXT, field TEXT, vendor_value TEXT, correct_value TEXT, PRIMARY KEY(trade_id, field)`

Include a view `validation_summary` returning columns: `trade_id`, `num_discrepancies` (integer count), `discrepant_fields` (comma-separated field names, alphabetically sorted) -- one row per trade having at least one discrepancy.

**`/app/output/discrepancies.json`** -- Array of `{trade_id, field, vendor_value, correct_value}`. Include only fields where vendor and computed values differ. Sort by `trade_id` then `field`. Numeric values as numbers, null where applicable.

Treat empty CSV fields as null. Database and JSON discrepancies must be consistent.

A legacy pricing library at `/app/lib/legacy_pricer.py` is available for reference but contains known defects.
