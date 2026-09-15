A PostgreSQL 16 database `analytics` contains tables `nums` (column `a`, values 0-3) and `inventory` (columns `id`, `item`, `category`, `price`, `stock`; 8 rows of hardware items). The file `/app/queries.sql` contains 10 tagged SQL queries (`-- @name: <name>`) for a reporting dashboard. Each query has a bug related to PostgreSQL's SQL identifier resolution in ORDER BY, GROUP BY, WINDOW, or DISTINCT ON clauses — some queries error outright, others silently produce wrong orderings or groupings.

Create `/app/query_doctor.py`, a Python diagnostic and repair tool that:

1. Parses tagged queries from `/app/queries.sql`
2. Connects to the `analytics` database and executes each query
3. Compares results against the specifications in `/app/expected_results.json`
4. Classifies each bug using the taxonomy defined in `/app/bug_taxonomy.md`
5. Determines the failure mode: `"error"` (query raises an exception) or `"wrong_results"` (executes but produces incorrect output)
6. Assesses risk: queries that silently produce wrong results are `"high"` risk; queries that error are `"low"` risk
7. Generates corrected SQL for each broken query
8. Writes `/app/queries_fixed.sql` with all corrected queries, preserving `-- @name:` tags and original table references
9. Writes `/app/audit_report.json` following this schema:

```json
{
  "queries": {
    "<name>": {
      "status": "fixed",
      "bug_type": "<taxonomy category>",
      "failure_mode": "error" | "wrong_results",
      "risk_level": "high" | "low",
      "fix_description": "<brief explanation of the fix>"
    }
  },
  "summary": {
    "total_queries": 10,
    "bugs_found": <int>,
    "by_type": { "<category>": <count> },
    "by_failure_mode": { "error": <count>, "wrong_results": <count> },
    "high_risk_count": <int>
  }
}
```

Run your tool to generate both output files. Do not modify `/app/queries.sql` — an unmodified copy is preserved at `/app/.queries_original.sql`.

PostgreSQL is installed but not running. Start it with `pg_ctlcluster 16 main start`. Connect to the `analytics` database as user `postgres` (trust authentication is configured). The query intent descriptions are in `/app/report_spec.md`.