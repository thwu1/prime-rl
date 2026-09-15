A parallel program's execution is modeled as a computation graph in `/app/program.cg` using Habanero-style async/finish task-parallel constructs (format specification at `/app/format_spec.md`).

Produce the following output artifacts representing a complete concurrency analysis of the computation graph.

### `/app/analysis.db` — SQLite3 Database

Tables with exact schemas:

- `nodes(id INTEGER PRIMARY KEY, weight INTEGER)` — all computation nodes
- `happens_before(src INTEGER, dst INTEGER, PRIMARY KEY(src, dst))` — full transitive closure of the happens-before partial order
- `mhp_pairs(node1 INTEGER, node2 INTEGER, PRIMARY KEY(node1, node2))` — May-Happen-in-Parallel pairs (node1 < node2): distinct pairs where neither happens-before the other
- `data_races(node1 INTEGER, node2 INTEGER, variable TEXT)` — one row per conflicting variable per MHP pair accessing the same variable with at least one write (node1 < node2)
- `metrics(key TEXT PRIMARY KEY, value REAL)` — keys: `work` (sum of all node weights), `span` (critical path length), `ideal_parallelism` (work/span, rounded to 4 decimal places)
- `isolated_nodes(node_id INTEGER PRIMARY KEY)` — minimum-cardinality vertex set whose isolation eliminates every data race

### `/app/graph.dot` and `/app/graph.svg` — Graphviz Visualization

DOT source file and its SVG rendering (via Graphviz `dot -Tsvg`):

- Nodes labeled `N<id>\nw=<weight>`; `shape=doublecircle` for isolated nodes, `shape=circle` otherwise
- Edge colors: continue=black, spawn=blue, future_get=green, finish-join=red (omit a finish-join edge when it duplicates a direct edge)
- Data race pairs: `dir=none, style=dashed, color=orange`

### `/app/results.json` — JSON Report

Object with keys: `happens_before_pairs` (list of `[u, v]`), `mhp_pairs` (sorted `[u, v]`), `data_races` (list of `{"nodes": [u, v], "variables": [...]}`), `work`, `span`, `ideal_parallelism`, `isolated_nodes`.