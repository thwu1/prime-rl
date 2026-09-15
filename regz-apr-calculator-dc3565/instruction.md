Build a Regulation Z APR compliance pipeline at `/app/`.

The environment provides loan specifications in `/app/loans/*.json`, the regulatory APR computation specification in `/app/reference/appendix_j_spec.txt`, APOR rate data in `/app/reference/apor_fixed.dat`, and enrichment rules in `/app/reference/rate_spread_spec.txt`.

**`/app/regz_apr`** — Executable accepting one argument (path to loan JSON). Outputs JSON to stdout, exits 0.

Loan input schema:
```json
{"id": "str", "consummation_date": "YYYY-MM-DD",
 "advances": [{"date": "YYYY-MM-DD", "amount": float}],
 "payment_groups": [{"first_date": "YYYY-MM-DD", "amount": float, "count": int, "period_months": int}],
 "disclosed_apr": float|null, "is_mortgage": bool}
```

Required output schema:
```json
{"id": "str", "computed_apr": float, "transaction_type": "regular"|"irregular",
 "tolerance_pct": float, "disclosed_apr": float|null, "within_tolerance": bool|null}
```

`computed_apr` to 2 decimal places. `within_tolerance` is `null` when `disclosed_apr` is `null`. Must handle dynamically-generated loan files, not just the provided samples.

**`/app/Makefile`** — Phony targets `compute`, `enrich`, `store`, `report`, `all`:
- `compute` → `/app/build/apr_results.ndjson` (one JSON object per line per loan)
- `enrich` → `/app/build/enriched.ndjson`
- `store` → `/app/results.db` (schema loaded via `sqlite3` CLI from `/app/schema.sql`, then data imported)
- `report` → `/app/build/summary.json`
- `all` → full pipeline in dependency order

**`/app/schema.sql`** — Loadable via `sqlite3 /app/results.db < /app/schema.sql`:
```sql
CREATE TABLE loan_results (
  id TEXT PRIMARY KEY, computed_apr REAL NOT NULL,
  transaction_type TEXT NOT NULL CHECK(transaction_type IN ('regular','irregular')),
  tolerance_pct REAL NOT NULL, disclosed_apr REAL, within_tolerance INTEGER,
  term_years INTEGER NOT NULL, apor_rate REAL NOT NULL,
  rate_spread REAL NOT NULL, high_cost INTEGER NOT NULL CHECK(high_cost IN (0,1)));
```

**`/app/compliance_pipeline`** — Executable. Runs the Make pipeline and prints the contents of `/app/build/summary.json` to stdout.

Summary JSON:
```json
{"total_loans": int, "regular_count": int, "irregular_count": int,
 "high_cost_count": int, "tolerance_failures": [str], "avg_rate_spread": float}
```

`avg_rate_spread` rounded to 2 decimal places. `tolerance_failures` is the alphabetically-sorted list of loan IDs where `within_tolerance` is false. `within_tolerance` stored as 1/0/NULL in SQLite.
