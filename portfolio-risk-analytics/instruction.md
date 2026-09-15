A DuckDB database at `/app/warehouse.duckdb` contains financial market data for a multi-asset portfolio management platform. The data spans equities in multiple currencies with daily closing prices, portfolio positions, and associated reference data across several interrelated tables.

Explore the database schema and data model, then build a risk analytics pipeline that computes per-portfolio risk metrics according to the specification at `/app/risk_spec.md`.

Write the output to `/app/output/risk_report.csv`.