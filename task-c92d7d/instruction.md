An e-commerce dbt project at `/app/dbt_project/` implements a staging → intermediate → marts pipeline backed by DuckDB. Raw data is pre-loaded in `/app/dbt_project/dev.duckdb`.

The project was left incomplete by a previous engineer. It has configuration errors, architectural flaws in the model DAG, broken Jinja logic, incorrect incremental materialization, and components declared in the marts schema YAML that were never implemented (missing model SQL files and missing custom test macros).

Deliver a fully operational pipeline where:

- `dbt build --full-refresh` and a subsequent `dbt build` both succeed with zero errors
- `dim_customers`: 5 rows, `lifetime_value` in dollars (not cents)
- `fct_orders`: 10 rows, per-payment-method amount columns driven by the `payment_methods` project variable
- `revenue_daily`: 10 rows (one per order date), incrementally materialized with idempotent re-runs
- `customer_lifetime_tiers`: 5 rows, each customer assigned a `tier` (`bronze`/`silver`/`gold`/`platinum`) using thresholds from the `tier_thresholds` project variable, plus a `value_quartile` column (1–4, ranked by descending lifetime value)
- All schema tests in the marts YAML pass — create any missing custom generic test macros required by the schema definitions

No external dbt packages are needed.