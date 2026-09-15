A PostgreSQL 16 database `benchmark` is experiencing severe performance degradation under normal production load. The database serves an e-commerce application with tables for customers (~10K rows), orders (~100K), order_items (~300K), products (~5K), and an audit log. Connect via `psql -U postgres -d benchmark` (trust authentication is configured for local connections).

A workload profile capturing the most frequent production queries and their hourly execution rates is at `/app/workload.sql`.

Perform a comprehensive performance audit of the running database. For every issue you discover, evaluate the appropriate remediation, apply the fix, and produce evidence that your changes are effective. All changes must be active in the running PostgreSQL instance — restart the server if any configuration change requires it.

## Deliverables

**1. `/app/diagnosis.json`** — structured findings report:

```json
{
  "findings": [
    {
      "anomaly_type": "<your category label>",
      "affected_object": "<table, index, view, or setting>",
      "description": "<what was wrong and evidence of impact>",
      "fix_applied": "<SQL or command executed>",
      "justification": "<why this fix over alternatives; tradeoff analysis>"
    }
  ]
}
```

**2. `/app/performance_eval.json`** — before/after performance comparison using EXPLAIN costs for at least 3 workload queries:

```json
{
  "evaluations": [
    {
      "query_id": "<e.g. Q1>",
      "query_sql": "<the SQL statement>",
      "before_total_cost": 0.0,
      "after_total_cost": 0.0,
      "improvement_pct": 0.0
    }
  ]
}
```

Capture EXPLAIN total costs **before** applying fixes, then again **after** all fixes and any required restart. Calculate the percentage cost reduction for each query.

## Acceptance Criteria

- **Index coverage**: Columns appearing in WHERE/JOIN predicates on large tables in the workload must have appropriate index support (single-column or as the leading column of a composite index).
- **Index efficiency**: No single-column index should exist on a table when a composite index on that same table already has that column as its leading prefix. Useful composite indexes must be preserved (at least 2 non-primary-key indexes should remain on the customers table).
- **Storage health**: All tables must have dead tuple counts below 1000.
- **Server tuning**: For this container with 2GB RAM — `shared_buffers` >= 128MB, `work_mem` >= 4MB, `maintenance_work_mem` >= 64MB, `effective_cache_size` >= 512MB, `random_page_cost` <= 2.0.
- **View optimization**: The view `v_customer_order_summary` must be rewritten so its definition contains at most 2 SELECT keywords total, while producing results identical to the original semantics (matching customer IDs, order counts, and total amounts).
- **Performance evidence**: `/app/performance_eval.json` must contain at least 3 query evaluations, with at least 2 showing positive cost improvement.
- **Report completeness**: `/app/diagnosis.json` must contain at least 5 findings, each with all five required fields (`anomaly_type`, `affected_object`, `description`, `fix_applied`, `justification`).