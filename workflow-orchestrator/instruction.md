Build a Python workflow orchestration engine at `/app/orchestrator/` for managing rolling operations across distributed database cluster nodes. The engine parses YAML workflow definitions, executes tasks on cluster nodes with zone-aware concurrency constraints, persists execution state in SQLite for crash recovery and job resumption, classifies errors as recoverable or unrecoverable with configurable retries, polls preconditions with success windows, and supports template variable substitution.

The engine must be importable as:
```python
from orchestrator import WorkflowEngine, TaskRegistry, TaskResult, ErrorKind
```

## API

**ErrorKind**: Enum with `RECOVERABLE` and `UNRECOVERABLE`.

**TaskResult**:
- `TaskResult.ok(data=None)` — successful result
- `TaskResult.fail(error_kind, message="")` — failure result
- `.success` (bool), `.error_kind`, `.message`, `.data` properties

**TaskRegistry**:
- `register(task_type: str)` — decorator for async handlers: `async def(node: dict, params: dict, context: dict) -> TaskResult`
- `node` is `{"name": str, "zone": str}`, `context` includes `{"attempt": int}` (0-indexed)
- Condition handlers use prefix `condition:`, e.g. `registry.register("condition:node_healthy")`

**WorkflowEngine**:
- `__init__(db_path: str, registry: TaskRegistry)` — initializes SQLite
- `load_workflow(path: str) -> dict` — parses YAML
- `create_job(workflow: dict, cluster: dict, variables: dict = None, target_nodes: list[str] = None) -> str` — returns job_id; `cluster` is `{"name": str, "nodes": [{"name": str, "zone": str}, ...]}`
- `async run_job(job_id: str) -> dict` — returns `{"status": "completed"|"failed", "completed_tasks": int, "failed_tasks": int}`
- `async resume_job(job_id: str) -> dict` — resumes from checkpoint, skips completed tasks, re-attempts failed/in-progress/pending
- `get_job_status(job_id: str) -> dict` — returns `{"job_status": str, "tasks": [{"node": str, "task_index": int, "cluster_task_index": int, "status": str, "attempts": int}, ...]}`

## Workflow YAML Format

```yaml
name: "workflow name"
variables:
  - name: var_name
    default: value
cluster_tasks:
  - type: node_workflow
    name: "step name"
    concurrency_unit: zone|all    # zone = sequential zone batches; all = one batch
    concurrency_limit: N          # max concurrent nodes within each batch
    node_tasks:
      - type: task_type_name
        retries: N                # optional, default 3
        params:
          key: "{{var_name}}"     # template substitution
      - type: wait_for_condition
        condition: condition_name
        params:
          timeout_seconds: N
          poll_interval_seconds: N
          success_window_seconds: N  # must pass continuously for this duration
```

## Execution Rules

- `concurrency_unit: zone` groups nodes by zone; zone batches run sequentially. `concurrency_unit: all` puts all nodes in one batch.
- `concurrency_limit` caps concurrent node processing within each batch.
- Node tasks run sequentially per node. Multiple `cluster_tasks` run sequentially.
- `{{var_name}}` is substituted from the `variables` argument or workflow defaults.
- `wait_for_condition` polls at `poll_interval_seconds`. The condition must return `TaskResult.ok()` continuously for `success_window_seconds` (resets on any failure poll). Times out with job failure if `timeout_seconds` is exceeded.
- Recoverable errors trigger retries (initial attempt + `retries` count). Unrecoverable errors halt the entire job immediately. Handler exceptions are treated as recoverable.
- SQLite persists task states (`pending` → `in_progress` → `completed`|`failed`). `resume_job` skips `completed` tasks, re-attempts everything else.

Cluster topology: `/app/cluster.json`. Example workflows: `/app/workflows/`.