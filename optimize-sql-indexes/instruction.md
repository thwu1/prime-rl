A PostgreSQL 16 database (`benchdb`, user `bench`, trust auth) powers a sales analytics platform. It contains four tables — `subsidiaries` (30 rows), `employees` (10K rows, composite PK `(employee_id, subsidiary_id)`), `sales` (500K rows), and `messages` (200K rows, ~2% unprocessed). Start PostgreSQL with `pg_ctlcluster 16 main start`.

Six queries at `/app/queries/q1.sql` through `/app/queries/q6.sql` exhibit poor performance due to missing indexes, suboptimal existing indexes, and query anti-patterns that prevent index usage. Three existing non-primary-key indexes (`idx_sales_date`, `idx_messages_processed`, `idx_sales_value`) may be redundant or harmful.

Diagnose every query's performance problems using `EXPLAIN ANALYZE`, then produce:

- `/app/migration.sql` — all DDL changes (CREATE INDEX, DROP INDEX, etc.). Must contain at least one index DDL statement.
- `/app/optimized/q1.sql` through `/app/optimized/q6.sql` — optimized query versions

## Per-query requirements

**Q1** (employee lookup with date arithmetic): The original applies `date_of_birth + INTERVAL '30 years'` which prevents index usage. The optimized query must move the arithmetic off the column — it must not contain `date_of_birth + INTERVAL` or `date_of_birth +INTERVAL`. No sequential scan on `employees`.

**Q2** (quarterly sales report): The original uses `EXTRACT(YEAR FROM sale_date)` and `EXTRACT(QUARTER FROM sale_date)` which wraps the indexed column in a function. The optimized query must not use `EXTRACT` at all — replace with explicit date range conditions. No sequential scan on `sales`.

**Q3** (revenue aggregation by subsidiary): The aggregation must achieve an **Index Only Scan** via a covering index. No sequential scan on `sales`.

**Q4** (employee-sales join): No sequential scan on `employees` or `sales`. The join must be supported by proper indexes on both tables.

**Q5** (paginated sales listing — seek method): The original uses `OFFSET 50000` which is slow. The optimized query must implement seek-method pagination:
- Must **not** use the `OFFSET` keyword
- Must use a **row-value comparison** of the form `(sale_date, sale_id) < (...)` to seek to the correct position
- Must return between 1 and 10 rows
- A supporting index containing both `sale_date` and `sale_id` must exist on the `sales` table after migration
- No sequential scan on `sales`

**Q6** (unprocessed message queue): A **partial index** with a `WHERE` clause must exist on the `messages` table after migration (to index only the ~2% unprocessed rows). No sequential scan on `messages`.

## Index constraints

- Total non-primary-key indexes across all four tables must not exceed **8** after migration
- `idx_sales_value` (indexes `eur_value` alone) is useless and **must be dropped**
- `idx_messages_processed` (only 2 distinct values, terrible selectivity) is useless and **must be dropped**
- Design indexes that serve multiple queries where possible to stay within budget
- All optimized queries must return results equivalent to their originals