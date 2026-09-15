A data warehouse team built an analytical star schema (`fact_sales`, `dim_customer`, `dim_supplier`, `dim_part`, `dim_date`) on top of TPC-H operational data. Five business reports query this model, but stakeholders report that some produce numbers that do not match the operational source of truth.

Evaluate the dimensional model design, identify which reports produce incorrect results, diagnose the root causes, fix the schema, and produce corrected reports that all return accurate results.

## Environment

- **Database**: `/app/warehouse.duckdb` (DuckDB, accessible via `import duckdb` or the `duckdb` CLI)
- **Staging tables** (raw TPC-H SF=0.1 data): `stg_lineitem`, `stg_orders`, `stg_customer`, `stg_supplier`, `stg_part`, `stg_partsupp`, `stg_nation`, `stg_region`
- **Star schema**: `fact_sales`, `dim_customer`, `dim_supplier`, `dim_part`, `dim_date`
- **Reports**: `/app/reports/report_1.sql` through `report_5.sql`
- **Business requirements**: `/app/requirements.md`

## Deliverables

- `/app/diagnosis.json` — JSON object with keys `report_1` through `report_5`. Each must include `"status"` (`"correct"` or `"incorrect"`), `"explanation"`, and for incorrect reports a `"root_cause"` label.
- `/app/fix.sql` — Idempotent SQL script that corrects the dimensional model by creating or modifying schema objects. Must be executable against the database as pure SQL.
- `/app/corrected_reports/report_1.sql` through `report_5.sql` — SQL queries that each produce results matching the operational source of truth. Reports must query the analytical layer (fact/dim tables), not the staging tables directly.