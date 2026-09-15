An analytics event database at `/app/analytics.db` (~500K rows, single `events` table) will be deployed read-only via sql.js-httpvfs. In this architecture, every SQLite page the query engine touches becomes a separate HTTP Range request — a network round trip. The file `/app/queries.sql` defines seven analytical queries (Q1-Q7) that the frontend must serve.

The database currently has no indexes beyond the implicit rowid primary key. Every query triggers a full table scan, fetching the entire database over the wire.

Create `/app/optimize.sql` — a SQL script executable via `sqlite3 /app/analytics.db < /app/optimize.sql` — that transforms the database so that all seven queries execute with minimal page fetches over HTTP. The optimized database must satisfy **all** of the following acceptance criteria:

- Every query in `/app/queries.sql` must execute using **only index structures** — the query engine must never fall back to reading rows from the main table. Additionally, each query must use efficient tree-based index lookup, not sequential traversal of the index.

- At most **6 user-created indexes** across the entire database. Seven queries with distinct access patterns exist, so the indexing strategy must be carefully designed.

- At least one index must be **scoped to a subset of rows** rather than covering the full table.

- The query planner must have access to **table statistics** for cost-based index selection decisions.

- The SQLite **page size must be reduced below the default 4096 bytes**, and this change must take physical effect on the database file (not just be a runtime setting).

- All query results must remain **correct** and no data may be lost.

- Total database file size must stay **under 200 MB** after optimization.