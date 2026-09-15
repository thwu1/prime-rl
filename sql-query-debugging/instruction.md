A trading desk analytics database exists at `/app/trading.db` (SQLite) and in PostgreSQL (database `trading`, user `postgres`, local trust authentication). PostgreSQL is installed but the service is not running — start it with `pg_ctlcluster` (check the installed version with `pg_lsclusters`).

The authoritative business rules governing all metric computation are documented in `/app/knowledge_base.md`.

Seven SQL queries in `/app/queries/` are used for end-of-quarter regulatory reporting. Each query file contains a comment header describing the intended computation. The queries were written with SQLite-specific syntax and contain logical bugs — all seven execute without errors on SQLite but produce incorrect results.

The production reporting system runs PostgreSQL. Diagnose and fix all seven queries:

- Each fixed query must execute correctly on PostgreSQL and produce results conforming to the business rules in the knowledge base.
- Write each corrected query to `/app/fixed_queries/query_N.sql` (the directory already exists).
- Generate `/app/audit_report.json` — a valid JSON array of 7 objects, each with: `query_id` (integer 1-7), `bugs` (array of strings describing logical and dialect-specific bugs found), `engine_differences` (string noting SQLite vs PostgreSQL behavioral differences relevant to that query), and `fix_approach` (string summarizing the fix). Validate with `jq`.

The SQLite database is available for exploratory analysis. Compare query results between engines to verify correctness.