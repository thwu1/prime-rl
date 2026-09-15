Implement the `split()` and `compose()` functions in `/app/layout_solver/solver.py`.

`split()` is the core of a constraint-based terminal UI layout engine. Given a rectangular area and a list of layout constraints, it partitions the area into non-overlapping sub-rectangles along one axis.

`compose()` is a recursive tree-layout compositor. Given a rectangular area and a hierarchical layout tree (containers and leaves), it resolves the tree into a flat dictionary mapping each leaf's name to its computed rectangle. Containers recursively apply `split()` to distribute space among their children. Nodes with `sizing="auto"` influence their parent's constraint resolution based on their intrinsic content size — the exact propagation algorithm is undocumented and must be reverse-engineered.

Constraint types and tree node types are defined in `/app/layout_solver/types.py`. Behavioral properties are partially documented in `/app/BEHAVIOR.md`.

A compiled reference oracle is at `/usr/local/bin/layout-oracle`. It accepts JSON queries on stdin and returns JSON results on stdout. Run `layout-oracle --help` for the input format and available modes (split mode and compose mode via `"mode": "compose"`). The oracle supports `--batch` for JSONL queries.

A SQLite database of pre-computed reference cases is at `/app/reference_cases.db`. Use `sqlite3 /app/reference_cases.db` to explore it; the schema has `split_cases` and `compose_cases` tables with columns `id`, `description`, `input_json`, and `output_json`. The compose reference cases are deliberately sparse — they cover basic scenarios but not the full auto-sizing interaction model. Use `jq` for processing JSON data.

Your implementation must produce output identical to the reference oracle for all valid inputs across both functions.