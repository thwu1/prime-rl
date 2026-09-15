A DuckDB database at `/app/insurance.duckdb` contains a fully normalized insurance schema with 7 tables (`policy`, `party`, `policy_party`, `catastrophe`, `claim`, `claim_amount`, `premium`).

A semantic layer definition at `/app/semantic_model.yaml` describes entities, directed relationships with cardinality, metrics (including filtered aggregations and derived formulas), and dimensions.

Ten metric-query specifications at `/app/query_requests.json` each request one or more metrics, optional group-by dimensions, and optional filters.

Create `/app/compiler.py` that uses the semantic model to compile each query request into SQL, execute it against the database, and write per-query results to `/app/results/{query_id}.json`. Each result file must contain:

```json
{"query_id": "...", "sql": "...", "columns": ["..."], "rows": [[...], ...]}
```

All 10 result files must produce numerically correct aggregate values. Results are validated against expected values derived from the database.

Run: `python3 /app/compiler.py`