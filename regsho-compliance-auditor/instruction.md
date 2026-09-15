A FINRA Reg SHO compliance analysis system must exist at `/app/`.

Input data is at `/app/data/`: `consolidated_si.csv` (14-field quoted CSV), `fnsq_volume.txt` and `fnyx_volume.txt` (pipe-delimited venue files), `threshold_list.csv` (8-field quoted CSV spanning multiple trade dates). File schemas and regulatory references are at `/app/docs/`.

**Required files:**

`/app/pipeline.sh` — Executable shell script. When run, it must produce `/app/regsho.db`, invoke `/app/regsho_auditor.py` for all three report types, and produce `/app/output/pipeline_summary.json`. Constraints: must use sqlite3 `.import` for data loading and `jq` for summary generation.

`/app/regsho.db` (SQLite) must contain:

- Table `short_interest` — 200 rows
- Table `venue_volume` — all venue records combined; must include a `venue` column identifying each record's source facility
- Table `threshold_list` — 52 rows
- View `venue_symbol_agg` — columns: `symbol`, `short_volume`, `short_exempt_volume`, `total_volume`, `short_ratio`, `venue_count`
- View `threshold_streaks` — columns: `symbol`, `max_consecutive_days`, `closeout_eligible` (1 or 0)

`/app/regsho_auditor.py` — Python CLI writing pretty-printed JSON (2-space indent) to `/app/output/`.

Subcommand `verify-si <csv_path>` → `si_verification.json`:
`{"total_records": int, "pass_count": int, "fail_count": int, "dtc_cap_symbols": [str], "dtc_floor_symbols": [str], "records": [{"symbol": str, "changePreviousNumber": {"reported": int, "computed": int, "pass": bool}, "changePercent": {"reported": float|null, "computed": float|null, "pass": bool}, "daysToCoverQuantity": {"reported": float, "computed": float, "pass": bool}}]}`

Subcommand `reconcile-venues <file1> <file2> [...]` → `venue_reconciliation.json`:
`{"total_symbols": int, "venues": [str], "multi_venue_count": int, "single_venue_count": int, "symbols": [{"symbol": str, "short_volume": int, "total_volume": int, "short_exempt_volume": int, "short_ratio": float, "venues": [str], "venue_breakdown": {venue: {"short_volume": float, "total_volume": float}}}]}`

Subcommand `threshold-monitor <csv_path>` → `threshold_report.json`:
`{"date_range": [str, str], "settlement_days": int, "securities_tracked": int, "closeout_triggered": [{"symbol": str, "trigger_date": str, "consecutive_days_at_trigger": int}], "rule4320_only": [str], "per_symbol": {symbol: {"dates_on_list": [str], "max_consecutive_days": int, "closeout_required": bool, "trigger_date": str|null}}}`

`/app/output/pipeline_summary.json`:
`{"si_pass_rate": float, "si_total": int, "venue_total_symbols": int, "venue_multi_pct": float, "threshold_securities": int, "threshold_closeout_count": int, "closeout_symbols": [str]}`

**Success**: `bash /app/pipeline.sh` exits 0; all database objects and JSON outputs pass automated verification.
