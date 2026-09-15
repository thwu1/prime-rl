# Cluster State Schema

The scheduler manages resource allocation for a distributed ML training cluster.
It reads current cluster state and produces decisions about which pending tasks
to start and which running tasks to preempt.

## Scheduling Modes

- **Fair-share**: Distributes cluster GPU capacity among task groups proportional
  to their weights using progressive filling. Produces `group_offers` mapping each
  group to its allocated GPU slot budget. Tasks are placed on agents considering
  both GPU slots and memory. Supports gang scheduling and anti-affinity.
- **Priority**: Schedules tasks in priority order (lower number = higher priority).
  Supports preemption and backfilling. Tasks placed on agents with multi-resource
  checks and anti-affinity.

## Top-level Fields

| Field | Type | Description |
|-------|------|-------------|
| `scheduler_type` | `"fair_share"` or `"priority"` | Which scheduling algorithm to use |
| `preemption_enabled` | bool | (priority mode only) Whether preemption is allowed |
| `agents` | list of Agent | Available compute agents |
| `groups` | list of Group | Task groups (jobs) |
| `tasks` | list of Task | Individual tasks to schedule |

## Agent

| Field | Type | Description |
|-------|------|-------------|
| `agent_id` | string | Unique agent identifier |
| `gpu_slots` | int | Number of GPU compute slots on this agent |
| `mem_mb` | int | Available memory in megabytes on this agent |

## Group

| Field | Type | Description |
|-------|------|-------------|
| `group_id` | string | Unique group identifier |
| `weight` | float | Relative weight for fair-share (default 1.0) |
| `priority` | int or null | Priority level (lower = higher priority), used in priority mode |
| `max_slots` | int or null | Optional cap on total GPU slot demand for this group |
| `gang` | bool | If true, all pending tasks must be allocated together or none |
| `registered_time` | string | ISO 8601 timestamp when group was created |

## Task

| Field | Type | Description |
|-------|------|-------------|
| `task_id` | string | Unique task identifier |
| `allocation_id` | string or null | Non-null if task is currently allocated (running) |
| `allocated_agent_id` | string or null | Agent where running task is allocated |
| `group_id` | string | Which group this task belongs to |
| `gpu_slots` | int | Number of GPU slots required |
| `mem_mb` | int | Memory required in megabytes |
| `preemptible` | bool | Whether this task can be preempted |
| `position` | int | Queue position within same priority (lower = earlier) |
| `submitted_time` | string | ISO 8601 timestamp when task was submitted |

## Output Format

```json
{
  "to_allocate": {"task_id_1": "agent_id_a", "task_id_2": "agent_id_b"},
  "to_release": ["alloc_id_1"],
  "group_offers": {"group_a": 4, "group_b": 2}
}
```

- `to_allocate`: dict mapping task_id to the agent_id where it should be started
- `to_release`: list of allocation_ids of running tasks that should be preempted
- `group_offers`: (fair-share mode) mapping of group_id to total offered GPU slots.
  In priority mode this is an empty dict `{}`.
