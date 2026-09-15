Build a pipeline under `/app/` that constructs an OIS discount curve with intra-month seasonality, calibrates it to market quotes, prices a swap portfolio, and computes risk sensitivities. Entry point: `make -C /app all`.

**Inputs** (`/app/data/`):

- `market_data.json` — OIS swap quotes, calibration node dates, valuation date, conventions.
- `holidays.json` — US holiday calendar as `{"us_holidays": ["YYYY-MM-DD", ...]}`.
- `sofr_fixings.csv` — Historical daily SOFR fixings (columns: `date`, `rate`). Contains systematic intra-month patterns by business-day position within each calendar month. Quantify and incorporate these into the curve.
- `portfolio.yaml` — Swaps to price (all spot-starting).

**Conventions:** Effective = T+2 business days. Fixed leg: annual (tenor ≤ 12M), semi-annual otherwise. Day count: ACT/360. Business-day rule: modified following.

**`/app/Makefile` targets:**

- `calibrate` — produce `/app/output/results.json` and `/app/output/curves.db`.
- `report` — use `jq` to read `results.json` and write `/app/output/summary.json`: `{"num_nodes": int, "num_forward_dates": int, "min_df": float, "max_df": float, "swap_ids": [str], "total_abs_pv01": {"swap_id": float}}`. `total_abs_pv01` is the sum of absolute values of each swap's bucketed PV01.
- `views` — use the `sqlite3` CLI to create views in `curves.db`:
  - `df_monthly(month TEXT, min_df REAL)` — minimum DF per calendar month (month format `YYYY-MM`).
  - `rate_stats(swap_id TEXT, total_pv01 REAL, max_abs_bucket REAL)` — aggregated PV01 per swap.
- `all` — runs `calibrate`, `report`, `views` in order.

**`/app/output/results.json`:**
```json
{"discount_factors": {"YYYY-MM-DD": float}, "forward_overnight_rates": {"YYYY-MM-DD": float}, "swap_pvs": {"swap_id": float}, "bucketed_pv01": {"swap_id": {"tenor_label": float}}}
```

**`/app/output/curves.db`** tables: `discount_factors(node_date TEXT PK, df REAL)`, `forward_rates(business_date TEXT PK, rate REAL)`, `swap_pvs(swap_id TEXT PK, pv REAL)`, `bucketed_pv01(swap_id TEXT, tenor_label TEXT, pv01 REAL, PK(swap_id, tenor_label))`.

**Acceptance criteria:**

1. Calibrated curve reprices every input OIS par swap within 0.01 basis points.
2. Discount factors: strictly in (0, 1), monotonically decreasing with date.
3. Forward overnight rates: positive for every business day from valuation through last node.
4. Forward rate coverage: one rate per business day from valuation to last node (±2 tolerance).
5. DFs at node dates equal compounding forward overnight rates (relative error < 1e-6).
6. Seasonality: month-end forward rates exceed nearby mid-month business-day rates by 5–30 bps.
7. Each `bucketed_pv01` entry has exactly one value per OIS quote label.
8. Receiver swaps: total PV01 < 0. Payer swaps: total PV01 > 0. Dominant PV01 bucket near the swap's own tenor.
9. Total |PV01| within 20× of notional × (tenor_years / 2) × 1 bp.
10. PV sign positive when fixed rate favors the stated direction vs. market par rate.
11. SQLite tables and views consistent with JSON output.
12. `summary.json` values consistent with `results.json`.
13. Makefile must reference `jq` in the `report` recipe and `sqlite3` in the `views` recipe.
