A production TiDB distributed database cluster has been experiencing intermittent performance degradation across several query patterns. The operations team has captured desensitized `EXPLAIN ANALYZE` outputs from five problematic queries. The raw plan files are in `/app/plans/`, system configuration variables in `/app/config.json`, an analysis manifest in `/app/manifest.json`, and the required output schema in `/app/spec.json`.

Build a diagnostic engine that produces three outputs:

## `/app/output/diagnostics.json`

Structured diagnostics conforming exactly to the schema in `/app/spec.json`. For each plan listed in the manifest:

- Compute total execution time in milliseconds from the root operator
- Identify the bottleneck operator (the one contributing the most self-execution time)
- Reconstruct the full operator tree with per-operator metrics including self-time for root-tier operators
- Detect any of the four performance anti-pattern issue types defined in `issue_detail_schemas` of the spec — the engine must correctly distinguish genuine anti-patterns from normal behavior (no false positives, no missed detections)

Populate the `concurrency_analysis` section for each operator listed in the manifest's `concurrency_targets`, reporting how index tasks, table tasks, and DistSQL concurrency compose at runtime for `IndexLookUp` operators. Populate the `comparative_analysis` section for each entry in `paired_comparisons`, identifying the performance ratio and attributing the root cause to a detected issue type from the slower plan.

## `/app/output/operators.db`

A SQLite database persisting all parsed operator data. Required tables:

- `operators` — columns: `plan_file TEXT, operator_id TEXT, depth INTEGER, task_type TEXT, est_rows REAL, act_rows INTEGER, time_ms REAL, self_time_ms REAL, parent_operator_id TEXT`
- `issues` — columns: `plan_file TEXT, issue_type TEXT, operator_id TEXT, details_json TEXT`

Each row in `operators` corresponds to one operator from the parsed plans. The `issues` table has one row per detected anti-pattern with `details_json` containing the JSON-serialized detail object matching the spec's `issue_detail_schemas`. Data must be consistent with `diagnostics.json`.

## `/app/output/trees/`

Graphviz operator tree visualizations for each plan. Generate:

- A DOT file named `<plan_filename>.dot` (e.g., `lock_contention.plan.dot`)
- An SVG rendered from that DOT file (e.g., `lock_contention.plan.svg`) using the `dot` command

Each graph node must display the operator id and its task type. Edges represent the parent-child operator hierarchy.

## Input format

The plan files use TiDB's standard tabular `EXPLAIN ANALYZE` output with pipe-delimited columns, Unicode box-drawing characters (`├─`, `└─`, `│`) encoding tree depth in the operator id column, and deeply nested key-value execution info strings containing brace-delimited sub-objects, keys with spaces, and mixed time/size units (`s`, `ms`, `us`/`µs`, `ns`, composites like `2m52s`; `Bytes`, `KB`, `MB`, `GB`, `N/A`). Each file begins with a `QUERY:` line followed by the tabular output.