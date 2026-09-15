At `/app/` is a pipeline analysis workspace with a 27-node dbt project manifest and a buggy orchestrator CLI. Build a complete multi-tool analysis system using `jq`, `sqlite3`, `graphviz`, and Python.

## Reference

- `/app/manifest.json` — dbt project DAG (nodes, sources, exposures)
- `/app/cosmos_ref/` — Astronomer Cosmos selector engine source: authoritative reference for graph operators (`+`, `N+`, `@`), base selectors (`tag:`, `config.`, `fqn:`, `source:`, bare name), comma intersection, multi-select union, exclude subtraction, and test-node tag inheritance semantics

## Deliverables

### jq filter programs (`/app/jq_filters/`)

Write three jq programs, each invoked as `jq -r -f /app/jq_filters/<filter>.jq /app/manifest.json`:

**`dep_edges.jq`** — All dependency edges as sorted TSV: `child_id<TAB>parent_id`. Must cover all manifest sections.

**`node_attrs.jq`** — Node attributes as sorted TSV: `unique_id<TAB>resource_type<TAB>name<TAB>execution_time<TAB>effective_tags`. Name is last fqn element. Effective tags implement Cosmos-compatible first-parent-only inheritance for test nodes. Tags within each entry: comma-separated, alphabetically sorted.

**`fanout_analysis.jq`** — Fanout risk analysis as TSV sorted by risk_score DESC then id ASC: `unique_id<TAB>in_degree<TAB>out_degree<TAB>execution_time<TAB>risk_score`. In-degree = parent count; out-degree = child count across full graph; risk_score = out_degree * execution_time.

### SQLite database (`/app/pipeline.db`)

Create a SQLite database at `/app/pipeline.db` with schema:

- `nodes(id TEXT PK, resource_type TEXT, name TEXT, execution_time INT)` — all 27 manifest entries
- `edges(child_id TEXT, parent_id TEXT, PK(child_id, parent_id))` — all dependency edges
- `tags(node_id TEXT, tag TEXT, PK(node_id, tag))` — effective (inherited) tags
- View `v_bottlenecks`: columns `id, resource_type, execution_time, fanout, risk_score` ordered by risk_score DESC, id ASC
- View `v_test_coverage`: columns `id, name, resource_type, test_count` for model/seed nodes only, ordered by test_count ASC, id ASC

### Fixed orchestrator (`/app/orchestrator.py`)

The CLI has several subtle bugs in its algorithm functions. Fix them so all subcommands produce correct output. The CLI framework, argument parsing, and data loading are correct. Subcommands: `select`, `schedule`, `critical-path`, `impact`.

### DAG visualization (`/app/output/dag.dot`)

Generate a valid Graphviz DOT digraph named `pipeline` with all 27 nodes and 32 edges (child to parent direction). Node shapes by resource type: `box`=model, `hexagon`=seed, `ellipse`=test, `invhouse`=source, `house`=exposure.