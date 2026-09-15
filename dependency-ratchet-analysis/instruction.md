A monolith at `/app/` uses a Sorbet-style package system with layered architecture enforcement. Each package lives under `/app/packages/<name>/` with a `package.rb` manifest declaring its architectural layer, `strict_dependencies` enforcement level, and imports. Layer definitions are in `/app/layers.yml` and ratchet semantics are documented in `/app/README.md`.

Build a comprehensive dependency analysis pipeline that produces three artifacts:

## `/app/analysis_report.json`

JSON with:

- `packages` (dict keyed by package name): each entry has `layer` (name string), `layer_index` (integer), `strict_dependencies` (level string), `violations` (list of `{type, description}` objects; empty if compliant), `can_upgrade` (boolean — whether the package qualifies for promotion to the next ratchet level; `false` if already at `dag`), `transitive_dep_count` (distinct transitively reachable packages, excluding self), `afferent_coupling` (number of other packages that directly import this one), `efferent_coupling` (number of other packages this one directly imports), and `instability` (efferent / (afferent + efferent), rounded to 4 decimal places; 0.0 if denominator is zero).

- `summary`: `total_packages`, `violations_count` (packages with ≥1 violation), `upgradeable_count`, `by_level` (dict mapping each ratchet level to its package count), `scc_count` (strongly connected components with size > 1 in the full dependency graph), `largest_scc_size`.

- `feedback_arc_sets`: list of objects, one per SCC with size > 1, sorted by first member name alphabetically. Each object has `members` (sorted list of package names in the SCC) and `edges_to_remove` (a minimum-cardinality set of directed edges `[source, target]` whose removal makes the subgraph induced by `members` acyclic). The solution must be an exact minimum for all SCCs present.

## `/app/deps.db`

SQLite database with schema:

```
packages(name TEXT PRIMARY KEY, layer TEXT NOT NULL, layer_index INTEGER NOT NULL, strict_dependencies TEXT NOT NULL)
dependencies(source TEXT NOT NULL, target TEXT NOT NULL, PRIMARY KEY(source, target))
transitive_deps(source TEXT NOT NULL, target TEXT NOT NULL, distance INTEGER NOT NULL, PRIMARY KEY(source, target))
violations(package TEXT NOT NULL, violation_type TEXT NOT NULL, description TEXT NOT NULL)
coupling_metrics(name TEXT PRIMARY KEY, afferent_coupling INTEGER NOT NULL, efferent_coupling INTEGER NOT NULL, instability REAL NOT NULL)
```

`transitive_deps` holds the full transitive closure. `distance` is shortest-path hop count from source to target. Self-edges excluded.

## `/app/graph.svg`

SVG rendered via Graphviz `dot`:
- Subgraph clusters grouping packages by layer, labeled with layer name
- Node fill by ratchet level: `false`=#FFFFFF, `layered`=#ADD8E6, `layered_dag`=#FFFACD, `dag`=#90EE90
- Edges representing layering violations colored red
- All declared import edges present as directed edges