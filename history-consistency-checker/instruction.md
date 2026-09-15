Operation histories from a distributed database test suite are stored as JSON files in `/app/histories/`. Each records concurrent operations against shared state — some exhibit correct behavior, others contain concurrency anomalies.

Two history types exist:
- **Register** (`"type": "register"`): read/write/CAS operations on a single shared register from multiple processes. Operations are invoke/response pairs matched by `process`, with `time` fields defining each operation's temporal interval.
- **Transactional** (`"type": "transactional"`): multi-key read/write transactions with commit statuses and temporal bounds (`start_time`/`end_time`).

Examine the files to understand their exact schemas.

Build two artifacts:

**`/app/checker.py`** — CLI tool taking a history file path as argument, printing a JSON classification to stdout:
- Register: `{"linearizable": <bool>}`
- Transactional: `{"serializable": <bool>, "strict_serializable": <bool>, "anomalies": [<sorted strings>]}`
  Possible anomaly labels: `G1a`, `G1c`, `G2`, `causal_reverse`.

**`/app/audit.sh`** — shell pipeline that processes every file in `/app/histories/` and produces:
- For each transactional history: a DOT-format graph at `/app/output/graphs/<name>.dot` showing transaction operations and data flow, and a rendered SVG at `/app/output/graphs/<name>.svg` (`<name>` = filename without `.json`). Construct DOT content using `jq` to transform the history data into graph notation, then render to SVG with the `dot` command (graphviz).
- A SQLite database at `/app/output/audit.db` with table `results(history_name TEXT PRIMARY KEY, history_type TEXT, result_json TEXT, pass INTEGER)`. Linearizable registers and anomaly-free transactions pass (1); others fail (0). Populate via the `sqlite3` CLI.