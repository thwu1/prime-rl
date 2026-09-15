A compiled oracle at `/app/poly_server` simulates hidden polyomino fields on N x N grids. Each field has M polyominoes (connected shapes) placed at unknown positions; cells may be covered by multiple polyominoes. The oracle communicates via a custom TCP line protocol documented in `/app/PROTOCOL.txt`.

PostgreSQL is installed but not running and no database has been created. The required database schema is at `/app/schema.sql`. gnuplot is installed.

**Produce the following:**

1. **PostgreSQL database `polyfield`** populated with all sessions, queries, and submissions following `/app/schema.sql`.

2. **`/app/vis/heatmap_<case_id>.svg`** for each of the 5 cases (case_id 0-4) — gnuplot-generated SVG heatmaps showing the spatial distribution of queries made per cell.

3. **`/app/report.json`** — JSON object with:
   - `"cases"`: array of 5 objects, each with `"case_id"`, `"session_id"`, `"total_cost"`, `"num_queries"`, `"num_active_cells"`, `"correct"` (boolean)
   - `"total_cost"`: sum across all cases
   - Values must be consistent with the PostgreSQL database.

**Constraints:**
- 100% precision and recall on all 5 cases.
- Total query cost across all 5 cases < 1200.
- All query data must be persisted in PostgreSQL.
- Visualizations must be generated using gnuplot (not matplotlib or other tools).