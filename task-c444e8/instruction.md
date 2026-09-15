A PostgreSQL database `benchdb` runs on this host (start with `service postgresql start`; connect as user `postgres` with no password). It contains an e-commerce schema with tables `customers`, `products`, `orders`, `order_items`, and `reviews`, loaded with production-scale data. A view called `product_summary` also exists.

Five benchmark queries are provided in `/app/queries/Q1.sql` through `/app/queries/Q5.sql`. Each suffers from a distinct performance problem caused by database-level misconfigurations or structural deficiencies. Investigate the database state thoroughly — examine query plans, system catalogs, table statistics, and runtime configuration — to identify every root cause and produce a comprehensive remediation.

Produce three output files:

**`/app/diagnosis.json`** — A JSON object mapping each query ID to a short uppercase-underscore string identifying its primary performance bottleneck, using standard DBA terminology:
```json
{"Q1": "CAUSE_STRING", "Q2": "CAUSE_STRING", "Q3": "CAUSE_STRING", "Q4": "CAUSE_STRING", "Q5": "CAUSE_STRING"}
```

**`/app/fix.sql`** — An idempotent SQL script that remediates all identified issues. Use `CREATE INDEX IF NOT EXISTS` for any new indexes. Any view replacement must be semantically equivalent to the original (same row count, aggregate totals, and per-entity values).

**`/app/evaluation.json`** — A before-and-after performance evaluation. Capture the estimated total cost from `EXPLAIN` for each query both before and after applying your remediation. For each query ID (Q1 through Q5), provide:
- `"before_cost"`: estimated total cost from `EXPLAIN` before any fixes (numeric)
- `"after_cost"`: estimated total cost from `EXPLAIN` after all fixes are applied (numeric)
- `"improvement_factor"`: `before_cost / after_cost`, rounded to 1 decimal place (numeric, must be > 1.0)

Example structure:
```json
{
  "Q1": {"before_cost": 12345.67, "after_cost": 123.45, "improvement_factor": 100.0},
  "Q2": {"before_cost": 9000.00, "after_cost": 450.00, "improvement_factor": 20.0}
}
```

## Verification criteria

Your solution will be validated against the following outcomes:

- `diagnosis.json` correctly identifies each query's primary bottleneck category
- A composite index exists on the `orders` table covering `(customer_id, order_date)`
- An index exists on the `order_items` table covering `order_id`
- The `orders` table has a dead tuple ratio below 10%
- `work_mem` is configured to at least 32MB
- If the `product_summary` view is rewritten: its execution plan must contain no `SubPlan` nodes; it must return exactly one row per product; the sum of `review_count` across all rows must equal the total number of rows in `reviews`; the sum of `total_sold` must equal the total `quantity` in `order_items`; and `avg_rating` for any given product must match a direct `AVG(rating)` computed from the `reviews` table
- `evaluation.json` contains valid numeric before/after cost data for all five queries, with every `improvement_factor` greater than 1.0 and consistent with the stated costs