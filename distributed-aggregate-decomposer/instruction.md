A distributed SQL execution system at `/app/` decomposes aggregate queries for parallel execution across hash-partitioned data shards. Two candidate implementations at `/app/decomposer_alpha.py` and `/app/decomposer_beta.py` each take a different approach to mapping aggregates to shard-local partial computations and merge-phase recombination. Both contain distinct correctness bugs that cause distributed results to diverge from monolithic execution on various query patterns.

The system uses a DuckDB database at `/app/warehouse.duckdb` (TPC-H SF0.1 schema). `/app/run_pipeline.py` compares distributed vs monolithic execution:

```
python3 /app/run_pipeline.py "SELECT l_returnflag, SUM(l_quantity) AS s FROM lineitem GROUP BY l_returnflag"
```

`decompose_query(sql, num_shards)` returns `{"shard_query": str, "merge_query": str, "final_columns": list}`. The shard query runs on each partition independently; results concatenate into a table called `shard_results`; the merge query runs on `shard_results`.

Analyze both candidates to identify all their correctness bugs. Then implement a correct `/app/decomposer.py` that produces distributed results matching monolithic execution (rtol 1e-4) for queries using:

- SUM, COUNT, MIN, MAX
- AVG over simple columns and compound arithmetic expressions
- VAR_POP, STDDEV_POP
- COVAR_POP (two-argument aggregate)
- HAVING clauses referencing aggregates
- ORDER BY
- Multi-table star-schema join queries with GROUP BY