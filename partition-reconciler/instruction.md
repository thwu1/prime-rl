A partition reconciliation system at `/app/` manages data assets across a three-stage pipeline (`raw` -> `summary` -> `report`). It uses SQLite (`/app/warehouse.db`) for materialization tracking, YAML config (`/app/pipeline.yaml`) for pipeline definition, and Python modules for the reconciliation engine. The `summary` asset uses an "all" staleness mode (stale only when all upstream partitions have been re-materialized); `report` uses the default "any" mode. Materialization costs per asset are defined in `/app/costs.yaml`.

The system has interacting bugs across source code, database queries, and configuration that produce incorrect reconciliation results. The event log at `/app/events.jsonl` from a recent run falsely reports zero stale partitions.

Fix all bugs across the stack, then design and implement three additional capabilities:

**SQLite analytical views** must be created directly in `/app/warehouse.db`:
- `v_latest_materializations`: one row per (asset_key, partition_key) showing the latest timestamp normalized to seconds and the corresponding run_id. Column names: `asset_key`, `partition_key`, `run_id`, `normalized_ts`.
- `v_materialization_history`: every record with its normalized timestamp in seconds, a `recency_rank` column (1 = most recent per asset/partition) and a `total_records` count per asset/partition group. Column names: `asset_key`, `partition_key`, `run_id`, `normalized_ts`, `recency_rank`, `total_records`.

**Event log audit**: produce `/app/event_audit.json` from `/app/events.jsonl`. The output JSON must contain: `total_events` (integer), `events_by_level` (object mapping level string to count), `staleness_checks` (array of objects each with `asset`, `partition`, `upstream_resolved`, `result` fields extracted from STALENESS_CHECK events), `reported_total_stale` (integer from the RECONCILIATION_COMPLETE event), and `reported_total_unmaterialized` (integer from the RECONCILIATION_COMPLETE event).

**Cost-aware reconciliation planner**: create `/app/planner.py` that reads the corrected pipeline state and `/app/costs.yaml`, then writes `/app/recon_plan.json`. The planner must identify all stale partitions after bug fixes, compute total re-materialization cost, and determine whether it exceeds the budget. When over budget, it must select a feasible subset that fits within the budget while respecting pipeline dependencies — a partition should only be selected if all of its stale upstream dependencies are also selected. The output JSON must contain: `stale_partitions` (list of `{"asset": ..., "partition": ...}`), `total_cost` (float), `budget` (float), `budget_exceeded` (boolean), `selected` (list of `{"asset": ..., "partition": ..., "cost": ...}` ordered for correct execution), and `total_selected_cost` (float).

```
cd /app && PYTHONPATH=/app pytest /tests/test_state.py -v
```