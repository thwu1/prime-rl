A SQLite analytics database at `/app/analytics.db` will be served to browsers via HTTP Range requests — each SQLite page read is one network round trip. It contains `events` (~160K rows), `users` (5K rows), and `pages` (50 rows), with only naive single-column indexes.

Eight analytical queries in `/app/queries.sql` must all achieve covering-index access on every table lookup. In the HTTP VFS cost model, even a scan on the 50-row `pages` table means 20+ unnecessary network requests, so join lookups on small tables must use covering indexes too.

Requirements for the final database state:

- Every query plan shows `USING COVERING INDEX` for all table accesses (including join lookups on the `pages` table)
- At most **7 user-defined indexes** on `events` (pre-existing indexes count toward this limit if retained); at least one must be a **partial index**
- Page size is **1024 bytes** (rebuild with VACUUM)
- Journal mode is `delete` and auto-vacuum is disabled (both are incompatible with static HTTP file serving where page offsets must remain stable)
- An FTS5 external-content virtual table named `pages_fts` indexes `title` and `category` from `pages` (`content=pages, content_rowid=id`), supporting `bm25()` ranking and `snippet()` extraction
- All eight queries return correct, non-empty results

Do not alter existing tables, columns, or query definitions.