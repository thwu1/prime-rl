Implement a transaction history anomaly checker at `/app/checker.py` that processes Jepsen-style EDN histories, detects isolation-level anomalies per Adya, Liskov & O'Neil's generalized isolation level definitions, and produces Graphviz dependency graph visualizations.

**Data model**: Keys map to integer lists, initially `[]`. `append` atomically adds a globally unique integer (each value appended at most once across all transactions). `r` returns the observed list.

**Input**: EDN files at `/app/histories/*.edn`:

```edn
{:history
 [{:index 0 :type :ok :value [[:append :x 1] [:r :y [3 4]]]}
  {:index 1 :type :fail :value [[:append :y 5]]}]}
```

`:type` is `:ok` (committed) or `:fail` (aborted). Operations: `[:append <keyword-key> <int>]` or `[:r <keyword-key> <int-vector>]`.

**Invocation**: `python3 /app/checker.py <path.edn> --dot <output.dot>`

**JSON output** (stdout):

```json
{"anomalies": ["G1c"], "max_isolation_level": "read-uncommitted"}
```

`anomalies`: sorted list drawn from exactly `{G0, G1a, G1b, G1c, G-single, G2-item}`. Report all that are present. Implication closure is required: if `G0` is reported then `G1c` must also be reported; if `G-single` is reported then `G2-item` must also be reported.

`max_isolation_level`: one of `serializable`, `read-committed`, `read-uncommitted`, `none` — the strongest level the history satisfies given the detected anomalies.

**DOT output** (`--dot <path>`): Graphviz digraph of committed-transaction dependencies:

- Nodes: `T<index>` for each committed transaction with at least one edge.
- Directed edges labeled `<type>:<key>` where type is `ww`, `wr`, or `rw` (e.g. `ww:x`).
- Edge colors: `ww` blue, `wr` green, `rw` red.
- Edges participating in any detected cycle: `style="bold"`.
- Must render via `dot -Tsvg <output.dot>` without error.
- When `--dot` is omitted, only JSON output is produced.

Test histories are at `/app/histories/*.edn`. The checker must handle all of them correctly.
