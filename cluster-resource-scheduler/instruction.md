A distributed ML training platform needs a resource scheduler that handles multi-resource allocation, gang scheduling, and anti-affinity constraints. The scheduler skeleton at `/app/scheduler.py` provides I/O handling — implement the core scheduling logic per the behavioral specification at `/app/spec.md`.

The scheduler reads cluster state from `/app/cluster_state.json` and writes allocation decisions to `/app/schedule_output.json`. The input/output format is documented in `/app/schema.md`.

Anti-affinity constraints between task groups are stored in the SQLite database at `/app/cluster_config.db` and must be queried at runtime. Scheduling policy parameters are also in this database.

The scheduler must support two modes:

- **Fair-share**: Weighted max-min fairness via progressive filling with deadlock prevention. Tasks are placed on specific agents considering both GPU slots and memory capacity. Gang groups require all-or-nothing allocation. Anti-affinity pairs from the database must not share agents.

- **Priority**: Priority-ordered scheduling with optional preemption of lower-priority preemptible tasks, backfilling of preemptible tasks into unused capacity, and multi-resource agent placement with anti-affinity.

All implementation goes in `/app/scheduler.py`. The `schedule(state)` function is the entry point — it must return a dict with `to_allocate` (mapping task_id to agent_id), `to_release` (list of allocation_ids), and `group_offers` (mapping group_id to offered GPU slots, fair-share only).