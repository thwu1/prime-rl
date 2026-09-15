A dbt-duckdb project at `/app/dbt_project/` contains seed CSVs for a multi-currency e-commerce data warehouse, a pre-configured dbt profile (`DBT_PROFILES_DIR`), and a broken starting pipeline with staging models, an intermediate model, a mart model, a pricing macro, and a source configuration — all containing bugs or missing critical features.

Consult `/app/dbt_project/requirements.md` for the complete data specification and expected output schema. The pipeline must produce a `mart_reconciled_revenue` model that correctly handles event deduplication for replayed order-item events, multi-currency conversion using date-effective exchange rates, order adjustment netting (refunds and price corrections), status-based filtering, and cents-to-dollars conversion.

Create a custom generic dbt test named `test_reconciliation` that validates cross-layer revenue reconciliation between the mart and the underlying models. Apply it via schema YAML. Ensure all models have appropriate schema tests.

`dbt build` from `/app/dbt_project/` must complete with exit code 0 — all seeds, models, and tests passing.