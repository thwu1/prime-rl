# Orchestration Engine Requirements

## Overview

Build a Python CLI tool at `/app/scp.py` that orchestrates database cluster operations.
The engine reads YAML workflow definitions and executes task sequences across a
simulated cluster of database nodes. The node simulator is provided at
`/app/node_simulator.py`; the cluster topology is in `/app/cluster.json`. A webhook
receiver is available at `/app/webhook_server.py`.

## CLI Interface

### `run` command

```
python3 /app/scp.py run <workflow.yaml> --cluster <cluster.json> [options]
```

Options:
- `--target-zone ZONE` — only process nodes in this availability zone
- `--target-nodes NODE1,NODE2,...` — only process these specific nodes
- `--vars KEY=VALUE,KEY=VALUE,...` — override workflow template variables
- `--db PATH` — SQLite database path (default: `/app/scp_jobs.db`)
- `--interrupt-after N` — stop after N task completions (testing support)
- `--webhook-url URL` — send lifecycle notifications via curl to this URL

Exit codes:
- `0` — completed successfully
- `1` — failed (unrecoverable error or retries exhausted)
- `2` — interrupted (via `--interrupt-after`)
- `3` — lock conflict (another instance holds the cluster lock)

### `resume` command

```
python3 /app/scp.py resume <job_id> [--db PATH] [--webhook-url URL]
```

Resumes an interrupted or failed job. Completed tasks must not be re-executed.
Job metadata (workflow path, cluster path, targeting, variables) is loaded from SQLite.

Exit codes: same as `run`.

### `diagnose` command

```
python3 /app/scp.py diagnose --db <path> [--log <path>]
```

Generates a JSON diagnostic report to stdout. Must use external CLI tools:
- `sqlite3` CLI for database integrity checks and analytical queries
- `jq` for execution log analysis

See Diagnostic Report Format section for output structure.

## Workflow YAML Format

```yaml
name: "Workflow display name"

variables:                          # Optional runtime-configurable variables
  - name: var_name
    type: integer
    default: 30

concurrency_unit: zonal             # "zonal" (one zone at a time) or "global"
concurrency_limit: 1                # Max nodes processed concurrently in a batch

node_tasks:                         # Ordered list of tasks to run on each node
  - name: task_name                 # Identifier for this task
    action: action_name             # NodeSimulator method to call
    retries: 3                      # Max retry count (0 = single attempt)
    on_error: retry                 # "retry" = retry on recoverable error
                                    # "halt"  = halt job immediately
    preconditions:                  # Optional: conditions checked before execution
      - quorum_safe
      - cluster_normal

  - name: wait_task
    action: wait_condition          # Special: poll a condition instead of running an action
    condition: compactions_nominal  # Condition to poll
    timeout_seconds: "+var_name+"   # Template variable syntax: +varname+
    poll_interval_seconds: 0.2
```

## Template Variables

Values matching the pattern `+variable_name+` (with surrounding plus signs)
are replaced at runtime with the variable's resolved value. Variables are
resolved from `--vars` CLI overrides first, then workflow `default` values.

## Node Simulator API (`/app/node_simulator.py`)

Construct with: `NodeSimulator(cluster_config_path)`.

The simulator persists node state to `cluster_state.json` and logs all
operations to `execution_log.jsonl` (JSONL format). Read the simulator source
to understand the state model and operation semantics.

### Actions — return `{"status": ..., "message": ...}`

| Method                         | Returns                                |
|-------------------------------|----------------------------------------|
| `drain(node_name)`            | `success`, `recoverable_error`         |
| `stop_service(node_name)`     | `success`                              |
| `start_service(node_name)`    | `success`                              |
| `run_cleanup(node_name)`      | `success`                              |
| `trigger_unrecoverable(node)` | always `unrecoverable_error`           |

### Conditions

| Method                           | Returns         |
|----------------------------------|-----------------|
| `is_quorum_safe(node_name)`      | `bool`          |
| `is_cluster_normal()`            | `bool`          |
| `get_compaction_level(node_name)`| `int` (0 = nominal) |

### Precondition Mapping

- `quorum_safe` → `simulator.is_quorum_safe(node_name)`
- `cluster_normal` → `simulator.is_cluster_normal()`

### wait_condition Tasks

When `action` is `wait_condition`, poll the named condition until met or timed out:
- `compactions_nominal` → `simulator.get_compaction_level(node_name) == 0`

Poll at the interval specified by `poll_interval_seconds`. If the condition is
not met within `timeout_seconds`, treat as a `recoverable_error`.

## Error Classification

- **`unrecoverable_error`**: halt the job immediately, no retries.
- **`recoverable_error`** with `on_error: retry`: retry up to `retries` times.
  If all retries exhausted, halt the job.
- **`recoverable_error`** with `on_error: halt`: halt immediately, no retries.

When the job halts, set job status to `failed`, exit with code 1. Nodes in other
threads should stop gracefully (finish current operation, then exit).

## Behavioral Requirements

### Zone Scheduling

When `concurrency_unit` is `zonal`, all tasks for all nodes in one zone must
complete before any task in the next zone begins. Zones must not overlap
temporally. When `concurrency_unit` is `global`, all nodes form a single batch.

### Concurrency Control

Within a zone (or global batch), at most `concurrency_limit` nodes may be
processed concurrently. Each node runs its task list sequentially in the
order listed in `node_tasks`.

### Preconditions

Tasks with `preconditions` require all listed conditions to be satisfied
before the task executes. If conditions are not met, poll until they are.
On timeout, treat as a task failure.

### Targeting

`--target-zone` and `--target-nodes` filter which nodes from the cluster
topology are processed.

### Job Resumability

Interrupted or failed jobs can be resumed via the `resume` command. Previously
completed tasks are skipped — they must not be re-executed or re-trigger the
simulator.

### Crash Recovery

When resuming a job, tasks stuck in `in_progress` state represent operations
that were running when the process crashed. Before re-entering the workflow,
the orchestrator must determine whether each orphaned task actually completed
by examining the actual state of the cluster. Tasks whose effects can be
confirmed should be marked completed; tasks whose outcome cannot be determined
should be safely re-executed.

### Cluster Mutual Exclusion

Only one orchestrator instance may operate on a given cluster at a time.
Use `fcntl.flock` with `LOCK_EX | LOCK_NB` on the lock file
`/tmp/scp_<cluster_name>.lock` (where `<cluster_name>` is from `cluster.json`'s
`name` field). Exit with code 3 if the lock cannot be acquired within a
reasonable timeout. The lock must be held for the entire duration of the job.

### Interruption

The `--interrupt-after N` flag stops execution after N successfully completed
task executions (across all nodes). Set job status to `interrupted` and exit
with code 2. Only count tasks that complete with status `success`, not retries
that fail.

## SQLite Schema (at `--db` path)

### `jobs` table

| Column         | Type  | Notes                                       |
|---------------|-------|---------------------------------------------|
| job_id        | TEXT  | Primary key                                 |
| workflow_name | TEXT  | From workflow YAML `name` field             |
| workflow_path | TEXT  | Absolute path to workflow file              |
| cluster_path  | TEXT  | Absolute path to cluster config             |
| status        | TEXT  | running / completed / failed / interrupted  |
| target_zone   | TEXT  | Nullable                                    |
| target_nodes  | TEXT  | Nullable, comma-separated                   |
| variables     | TEXT  | JSON-encoded variable overrides             |
| created_at    | REAL  | Unix timestamp                              |
| updated_at    | REAL  | Unix timestamp                              |

### `task_executions` table

| Column        | Type    | Notes                                       |
|--------------|---------|---------------------------------------------|
| job_id       | TEXT    | Foreign key to jobs                         |
| node_name    | TEXT    | Node this execution targets                 |
| task_name    | TEXT    | From workflow task `name` field             |
| task_index   | INTEGER | Position in node_tasks list (0-based)       |
| status       | TEXT    | pending / in_progress / completed / failed  |
| attempts     | INTEGER | Number of attempts made                     |
| error_message| TEXT    | Nullable, last error message                |

Unique constraint on `(job_id, node_name, task_name, task_index)`.

## Webhook Notifications

When `--webhook-url` is provided, the engine sends JSON event notifications via
the `curl` command (subprocess call, not Python HTTP libraries) at lifecycle events:

| Event            | When                                              |
|------------------|---------------------------------------------------|
| `job_started`    | When a new job begins execution                   |
| `zone_started`   | When processing of a zone batch begins            |
| `zone_completed` | When all tasks in a zone batch have completed     |
| `task_error`     | When a task encounters any error (before retry)   |
| `job_completed`  | When a job completes successfully                 |
| `job_failed`     | When a job fails due to unrecoverable error       |

Each notification is a JSON POST with at minimum:
```json
{
  "event": "<event_type>",
  "job_id": "<job_id>",
  "timestamp": <unix_timestamp>
}
```

The `task_error` event should include a `details` object with `node` and `task` keys.

Webhook delivery is best-effort: failures do not affect job execution.
Use: `curl -s -X POST -H 'Content-Type: application/json' -d '<payload>' --connect-timeout 2 <url>`

## Diagnostic Report Format

The `diagnose` command outputs JSON with these fields:

### `integrity_check` (string)
Result of `PRAGMA integrity_check` run via the `sqlite3` CLI binary.
Expected value for a healthy database: `"ok"`.

### `job_summary` (array)
Job records queried via `sqlite3` CLI with `-json` output flag.
Each entry: `job_id`, `workflow_name`, `status`, `created_at`, `updated_at`.

### `task_summary` (array)
Task execution statistics queried via `sqlite3` CLI with `-json` output flag.
Each entry: `task_name`, `status`, `count`, `avg_attempts`.
Grouped by task_name and status.

### `latency_analysis` (array)
Execution log analysis performed via `jq` with `-s` (slurp) flag on the JSONL log.
Group events by action and compute per-action: `action`, `operation_count`
(number of "end" events), `error_count` (number of "error" events).
