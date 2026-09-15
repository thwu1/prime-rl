Implement `decompose_query()` in `/app/dist_agg.py` to decompose SQL aggregate queries for correct distributed execution across sharded DuckDB tables.

The function receives a SQL `SELECT` query targeting the `sales` table and a list of shard table names. It must return a dict with:
- `shard_query_template`: a SQL string with a `{shard_table}` placeholder that computes partial aggregates on each shard
- `merge_query`: a SQL string that combines partial results from a table called `shard_results` (the UNION ALL of all shard query outputs) into the final answer

The decomposed pipeline (run shard query on each shard, UNION ALL results into `shard_results`, run merge query) must produce results numerically equivalent to running the original query on the complete dataset.

Supported aggregates: `COUNT` (including `COUNT(DISTINCT col)`), `SUM`, `MIN`, `MAX`, `AVG`, `VAR_POP`, `VAR_SAMP`, `STDDEV_POP`, `STDDEV_SAMP`, `COVAR_POP(x, y)`, `CORR(x, y)`. Queries may use `WHERE`, `GROUP BY`, `HAVING`, `ORDER BY`, `LIMIT`, expressions inside aggregates (e.g., `AVG(price * quantity)`), and queries mixing multiple aggregate types — including combinations of distinct counting, single-column statistics, and two-column statistical aggregates within a single query.

The DuckDB database at `/app/warehouse.duckdb` contains a `sales` table (10,000 rows: `id`, `region`, `product`, `quantity`, `price`, `discount`, `sale_date`, `shard_id`) and shard tables `shard_0`..`shard_3` (subsets without `shard_id`). See `/app/config.json` and `/app/dist_agg.py` for the function interface.