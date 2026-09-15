A Jepsen/Elle-style consistency test suite ran against a database, producing test artifacts in `/app/jepsen-results/`. Each test run directory (`test-001` through `test-009`) contains:

- `history.edn`: Transaction history in Jepsen's native EDN format
- `results.edn`: Output from an initial checker run (known to be incorrect or incomplete for some histories)

An initial checker is at `/app/checker.py`. It processes EDN histories and detects consistency anomalies using Adya, Liskov & O'Neil's dependency-graph formalism over Elle's list-append model. However, it produces wrong results on several test histories and crashes on others. The specific bugs have not been identified.

Histories use the Jepsen invoke/completion protocol: each logical transaction appears as an `:invoke` operation paired with a completion (`:ok` for committed, `:fail` for aborted, `:info` for indeterminate). The `:value` field contains micro-operations in Elle's list-append model: `[:append key val]` appends a globally unique integer to a key's list, and `[:r key observed-list]` reads the current list (reads carry `nil` in the `:invoke` and the observed value in the completion).

Your task: produce a working auditor at `/app/auditor` (executable, takes a single test directory path argument) that outputs correct JSON to stdout:

```json
{"anomalies": [...], "isolation_level": "...", "cycle_dot": "..."}
```

- `anomalies`: sorted list of detected Adya-formalism anomaly type identifiers
- `isolation_level`: strongest standard isolation level the history satisfies (`"serializable"`, `"read-committed"`, `"read-uncommitted"`, or `"none"`)
- `cycle_dot`: Graphviz DOT representation of the transaction dependency graph restricted to nodes participating in anomalous cycles, with edges labeled by dependency type (`ww`, `wr`, `rw`). Empty string if no cycles found.

The auditor must produce correct results for all nine test histories in `/app/jepsen-results/`.