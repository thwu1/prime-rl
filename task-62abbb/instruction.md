Build a dbt node selector engine at `/app/selector_engine.py` and a manifest analysis script at `/app/analyze_manifest.jq`.

**Inputs:**
- `/app/manifest.json` — current dbt manifest v9 (seeds, staging, intermediate, mart, reporting models, and schema tests including multi-parent relationship tests). Use `jq` (`/usr/bin/jq`) for structural inspection.
- `/app/manifest_previous.json` — previous-state manifest for state comparison selectors
- `/app/queries.json` — selector queries (string selectors, YAML references, or state selectors)
- `/app/selectors.yml` — named YAML selector definitions

**Outputs (from `python3 /app/selector_engine.py`):**
- `/app/results.json` — JSON array of `{"id": N, "nodes": [sorted unique_ids...]}` per query
- `/app/lineage.dot` — Graphviz DOT digraph of the full manifest DAG; nodes shaped by resource_type (`box`=model, `cylinder`=seed, `diamond`=test), edges from parent to child

**Outputs (from `jq -f /app/analyze_manifest.jq /app/manifest.json`):**
JSON object with: `node_count` (int), `by_resource_type` (object mapping resource type to count), `root_nodes` (sorted array — nodes with no parent dependencies), `leaf_nodes` (sorted array — nodes with empty child_map entries), `max_fan_out` (int — largest child_map entry length), `max_fan_out_nodes` (sorted array — all nodes achieving max fan-out), `edge_count` (int — total depends_on.nodes edges across all nodes)

**Selector syntax:** Method selectors (`tag:`, `path:`, `config.materialized:`, `resource_type:`, `fqn:`), name match, graph operators (`+model`=ancestors, `model+`=descendants, `N+model`/`model+N`=depth-limited, `@model`=ancestors then all descendants of those ancestors), set operations (space=union, comma=intersection), and `exclude`. `path:X` matches nodes whose `path` starts with `X`. `fqn:X.Y` matches `fqn` arrays beginning with `["X","Y"]`. Graph traversal uses `depends_on.nodes` upward and `child_map` downward.

**State selectors:** `state:new` matches nodes in current manifest absent from previous. `state:modified` matches nodes present in both manifests where `checksum.checksum`, `depends_on.nodes` (sorted comparison), or `config` (deep equality) differs. State selectors compose with all graph operators and set operations like any other selector (e.g. `state:modified+`, `+state:modified`, `state:modified,tag:X`).

**YAML selectors:** Parse `/app/selectors.yml` for `union`, `intersection`, and `method`/`value` definitions with graph operator properties (`parents`, `children`, `parents_depth`, `children_depth`), inline `exclude`, and cross-selector references (`method: selector`). Selectors resolve in definition order.

After engine execution, `dot -Tsvg /app/lineage.dot -o /app/lineage.svg` must produce a valid SVG rendering.