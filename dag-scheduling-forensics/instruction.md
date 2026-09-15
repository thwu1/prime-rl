A production data platform running an Airflow-compatible orchestrator is experiencing cascading scheduling failures: tasks are running in duplicate on separate workers, some jobs are stuck indefinitely with no worker processing them, and others reference nonexistent scheduler processes. The platform operates with high-availability scheduling where at most one scheduler should be active at any time, but recent instability suggests this invariant has been violated.

Operational data is at `/app/`:

- `/app/dags/*.json` — DAG definitions with task operators, dependency structures, and cross-DAG references
- `/app/execution_log.jsonl` — Task instance execution records including scheduler assignments
- `/app/scheduler_events.jsonl` — Scheduler process lifecycle events (starts, heartbeats, terminations)
- `/app/config.json` — Platform configuration including health thresholds and HA constraints
- `/app/expected_schema.json` — Output schema specification for results

Create `/app/analyzer.py` that, when run with `python3 /app/analyzer.py`, produces:

1. **`/app/airflow_forensics.db`** — SQLite database with the operational data in a normalized relational schema: `dags`, `tasks`, `executions`, and `scheduler_events` tables. All source records must be faithfully imported.

2. **`/app/dependency_graph.dot`** and **`/app/dependency_graph.svg`** — Graphviz DOT file modeling the cross-DAG dependency graph with cycle-participating edges visually distinguished, plus the rendered SVG. Only operators that create true blocking scheduling dependencies should produce edges — understand the scheduling semantics of each operator type present in the DAG definitions to determine which create dependencies and which do not.

3. **`/app/results.json`** — Complete diagnostic analysis conforming to `/app/expected_schema.json`, including: the dependency graph, cycle enumeration, scheduling anomaly detection (concurrent executions, zombie tasks, orphaned tasks), scheduler health timeline reconstruction with per-job status classification, HA split-brain window detection, and root cause analysis correlating each anomaly to its causal scheduler event with downstream dependency impact assessment.