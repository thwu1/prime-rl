The "BigSpender" e-commerce platform's architecture has drifted from its original design. Three independent views of its 30-component dependency structure exist but have diverged over time.

Perform a comprehensive architecture health audit by reconciling these views against the governance framework and produce all analysis artifacts in `/app/results/`.

## Data Sources

- `/app/architecture/intended.dot` — Graphviz DOT digraph of the intended dependencies. Contains layout annotations and a visual legend cluster that are not part of the architecture specification.
- `/app/architecture/source_deps/` — One `.imports` file per component listing static code dependencies (one per line, `#` lines are comments).
- `/app/architecture/traces/` — Runtime call data from two different monitoring systems in different formats. Both must be processed and combined with duplicates removed.
- `/app/architecture/governance.db` — SQLite database containing component metadata, conformance classification rules, quality metric definitions, violation scoring parameters, and remediation configuration.

## Required Outputs (all JSON files in `/app/results/`)

### `dependency_graphs.json`
`{"intended": [[src, tgt], ...], "static": [[src, tgt], ...], "runtime": [[src, tgt], ...]}` — sorted, deduplicated edge lists from each view.

### `conformance.json`
Every unique edge across all three views classified per the rules in `governance.db`. Schema: `[{"source": str, "target": str, "in_intended": bool, "in_static": bool, "in_runtime": bool, "classification": str}, ...]`. Sorted by `(source, target)`.

### `metrics.json`
Per-component quality metrics on the **static** dependency graph, computed according to the metric definitions in `governance.db`. Object keyed by component name.

### `cycles.json`
Non-trivial strongly connected components (size > 1) in the **static** graph. Each SCC as a sorted list; outer list sorted by descending size, then first element alphabetically.

### `erosion_scores.json`
Per-component architecture erosion scores computed per `governance.db` scoring rules. Object keyed by component name; only non-zero entries.

### `remediation_plan.json`
`{"actions": [{"edge": [src, tgt], "action": str, "cost": int, "reduction": float}, ...], "total_cost": int, "total_reduction": float}`. Optimal remediation action selection maximizing erosion reduction within the configured budget. Actions sorted by edge.