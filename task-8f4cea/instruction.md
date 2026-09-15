A PostgreSQL database (`eventdb`) contains table `app.events` with ~500K rows of monitoring event data across 10 tenants. The schema is at `/app/schema.sql`. No secondary indexes exist yet.

Five critical queries are defined in `/app/queries.sql` (Q1-Q4 plus a retention delete operation). Your indexes must satisfy all of the following execution plan constraints simultaneously.

Start PostgreSQL: `pg_ctlcluster $(ls /etc/postgresql/ | head -1) main start`
Connect: `psql -U postgres -d eventdb`

## Requirements

Create **at most 4 secondary indexes** on `app.events` that satisfy these per-query constraints (verified via `EXPLAIN (FORMAT JSON)` and `EXPLAIN (ANALYZE, FORMAT JSON)`):

**Q1 — Dashboard Pagination** (tenant filtered, status/type filtered, ORDER BY created_at DESC LIMIT 50):
- The execution plan must contain **no Sort node** — ordering must come from the index.
- The plan must use an **Index Scan or Index Only Scan** (not a sequential or bitmap scan).
- The total rows touched across all scan nodes (actual rows + rows removed by filter) must be **at most 600**.

**Q2 — Time-Range Severity Report** (tenant filtered, created_at range, severity >= 4, ORDER BY created_at ASC):
- The execution plan must contain **no Sort node**.
- `created_at` must appear in the scan node's **Index Cond** (not as a post-scan Filter).

**Q3 — Resolution Metrics** (tenant filtered, status = 'RESOLVED', resolved_at range, GROUP BY source_system):
- Neither `status` nor `resolved_at` may appear in any scan node's **Filter** field — both must be pushed into index conditions.

**Q4 — Critical Unresolved Events** (tenant filtered, severity >= 4, status exclusion, ORDER BY created_at ASC LIMIT 20):
- The execution plan must contain **no Sort node**.
- The total rows touched across all scan nodes must be **at most 500**.

**Retention Delete Function:**
- Create a PL/pgSQL function `app.delete_old_events(p_cutoff TIMESTAMPTZ, p_batch_size INT DEFAULT 1000) RETURNS BIGINT` that deletes events with `created_at < p_cutoff` in batches and returns the total number of deleted rows.
- An index with **`created_at` as the leading (first) column** must exist to support efficient retention deletes.
- The function must delete all qualifying rows (zero remaining after completion) and return the exact count of rows deleted.

Run `ANALYZE app.events;` after creating indexes. Apply all changes directly to the running database.