Deliver a quantile-sketch management toolkit at `/app/` that is binary-compatible with the `datasketches` Python library's `kll_doubles_sketch`.

**Required files:**
- `/app/kll_sketch.py` — `KllDoublesSketch` class (must not import `datasketches` at runtime).
- `/app/kll_tool.py` — Multi-subcommand CLI tool using SQLite at `/app/sketch_store.db`.

**`KllDoublesSketch` class interface:**

Constructor `__init__(k=200)` with `k` in `[8, 65535]`. Methods: `update(value)` inserts a float64, silently ignoring NaN; `get_quantile(rank)` returns the approximate value at normalized rank in `[0,1]`; `get_rank(value)` returns the fraction of items strictly less than `value`; `merge(other)` merges another sketch into self; `serialize()` returns `bytes` readable by `datasketches.kll_doubles_sketch.deserialize()`; classmethod `deserialize(data)` accepts bytes produced by `datasketches.kll_doubles_sketch().serialize()`. Properties: `n`, `min_value`, `max_value`, `is_empty`, `k`, `is_estimation_mode`, `num_retained`.

For `k=200`, normalized rank error must be ≤ 0.0175.

**CLI subcommands** (`python3 /app/kll_tool.py <cmd> [args]`):

- `ingest --name NAME [--k K]` — Read newline-delimited floats from stdin; store sketch; print JSON. Empty stdin stores an empty sketch.
- `inspect --name NAME` — Load sketch from DB; print JSON.
- `merge --output NAME --inputs NAME [NAME …]` — Merge source sketches into target; store; print JSON.
- `export --name NAME` — Write raw binary sketch bytes to stdout (no JSON, no trailing newline).
- `import --name NAME` — Read raw binary sketch bytes from stdin; store; print JSON.

Duplicate names overwrite. Missing sketches or invalid input: exit 1 with `{"error": "<msg>"}` on stdout.

The CLI must support shell-pipeline workflows:
```
seq 1 100000 | python3 /app/kll_tool.py ingest --name demo
python3 /app/kll_tool.py export --name s1 | python3 /app/kll_tool.py import --name s1_copy
python3 /app/kll_tool.py inspect --name demo | jq '.quantiles'
sqlite3 /app/sketch_store.db "SELECT name, n FROM sketches;"
```

**JSON output** (all commands except `export`): object with exactly these keys — `name` (str), `k` (int), `n` (int), `min_value` (number|null), `max_value` (number|null), `is_empty` (bool), `is_estimation_mode` (bool), `num_retained` (int), `quantiles` (object|null with keys `"0.0"`,`"0.25"`,`"0.5"`,`"0.75"`,`"1.0"` mapping to numbers), `created_at` (ISO-8601 UTC str). Null values for `min_value`, `max_value`, `quantiles` when sketch is empty.

**SQLite schema** (`/app/sketch_store.db`): table `sketches` — columns `name TEXT PRIMARY KEY`, `k INTEGER NOT NULL`, `n INTEGER NOT NULL`, `created_at TEXT NOT NULL`, `sketch_blob BLOB NOT NULL`.

**Success criteria:** All tests pass.
