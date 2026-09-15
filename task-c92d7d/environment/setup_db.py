"""Pre-load seed data into DuckDB so raw tables exist before any dbt commands."""
import duckdb

conn = duckdb.connect('/app/dbt_project/dev.duckdb')

conn.execute("""
    CREATE TABLE IF NOT EXISTS main.raw_customers AS
    SELECT * FROM read_csv_auto('/app/dbt_project/seeds/raw_customers.csv')
""")

conn.execute("""
    CREATE TABLE IF NOT EXISTS main.raw_orders AS
    SELECT * FROM read_csv_auto('/app/dbt_project/seeds/raw_orders.csv')
""")

conn.execute("""
    CREATE TABLE IF NOT EXISTS main.raw_payments AS
    SELECT * FROM read_csv_auto('/app/dbt_project/seeds/raw_payments.csv')
""")

conn.close()
print("Database setup complete: /app/dbt_project/dev.duckdb")
