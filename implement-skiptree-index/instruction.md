The tree query pipeline at `/app/` has been failing since a migration to a DuckDB-based production analytics backend. The source tree data resides in SQLite at `/app/tree.db` (10,000 nodes, root node `id=0` with `parent_id=NULL`). The production analytics engine is DuckDB (the `duckdb` Python module is pre-installed).

Fix the pipeline so that all of the following hold:

- `python3 /app/pipeline/api.py build` reads the tree from `/app/tree.db` (SQLite) and constructs query-acceleration index structures in the DuckDB analytics database at `/app/analytics.duckdb`. The build must create at least 3 non-empty auxiliary tables in that DuckDB database.
- `python3 /app/pipeline/api.py ancestors <node_id>` prints to stdout a JSON array of integer node IDs tracing the path from the queried node to the root — inclusive, queried node first, root (0) last.
- `python3 /app/pipeline/api.py lca <node_a> <node_b>` prints the integer ID of the lowest common ancestor to stdout.
- No Python file under `/app/` may contain `WITH RECURSIVE`. All queries must use pre-built index structures via SQL `JOIN` operations — at least one Python file under `/app/` must contain a SQL `JOIN`.
- The original `tree` table in `/app/tree.db` must not be modified (10,000 rows, root at id 0).

Refer to `/app/config/production.yaml` for the full production database constraints and `/app/logs/errors.log` for recent failure details.