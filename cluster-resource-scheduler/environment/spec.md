# Scheduling Algorithm Specification

This document specifies the behavioral requirements for the cluster resource
scheduler. The scheduler must implement two modes: **fair-share** and **priority**.

## External Configuration

### Anti-Affinity Constraints

The SQLite database at `/app/cluster_config.db` contains an `anti_affinity` table:

```sql
SELECT group_a, group_b FROM anti_affinity;
```

Each row defines a bidirectional constraint: if `(A, B)` exists, tasks from group A
and tasks from group B must **never** be placed on the same agent. This applies in
both scheduling modes.

### Scheduling Policy

The `scheduling_policy` table contains key-value configuration:

```sql
SELECT key, value FROM scheduling_policy;
```

When `placement_mode` is `multi_resource`, the scheduler must check **both**
`gpu_slots` and `mem_mb` when placing tasks on agents. A task can only be placed on
an agent if the agent has sufficient GPU slots **and** sufficient memory remaining
after accounting for all tasks already allocated or being allocated on that agent.

---

## Fair-Share Mode

Fair-share scheduling distributes cluster GPU capacity among groups proportional
to their weights using a progressive filling algorithm (an implementation of
weighted max-min fairness).

### Phase 1: Compute Group State

For each group present in the task list:

- **slot_demand**: Sum of `gpu_slots` across **all** tasks (pending + allocated).
  If the group has `max_slots` set, cap the demand at that value.
- **active_slots**: Sum of `gpu_slots` across currently allocated (running) tasks.
- **presubscribed_slots**: Sum of `gpu_slots` across allocated tasks that are
  **not** preemptible. These slots cannot be reclaimed.

Sort each group's pending tasks by `(position ascending, submitted_time ascending)`.

### Phase 2: Progressive Filling

Determine each group's **offered** GPU slot count:

1. **Pre-offer initialization**: For each group with `presubscribed_slots > 0`,
   set `offered = presubscribed_slots` and reduce remaining capacity accordingly.

2. **Sort** groups by `(slot_demand ascending, registered_time ascending)`.

3. **Fill loop**: While unsatisfied groups remain (offered < slot_demand, not disabled):
   - Record `start_capacity = remaining_capacity`.
   - For each unsatisfied, non-disabled group:
     - Compute `fair_share = max(1, floor(start_capacity * weight / total_unsatisfied_weight))`.
     - Compute `offer = min(fair_share, remaining_capacity, slot_demand - offered)`.
     - Apply pre-offer accounting: if the group had presubscribed slots, subtract
       already-counted pre-offers from the new offer to avoid double-counting.
     - Add `offer` to the group's `offered` and subtract from `remaining_capacity`.
     - If the group is now satisfied (offered == slot_demand), remove it from the
       unsatisfied set and recompute total weight.
   - **If remaining_capacity == 0**: Perform **deadlock prevention**.
     - Among non-disabled, unsatisfied groups (sorted by registered_time descending),
       find the first group whose **smallest pending task's `gpu_slots`** exceeds
       its current `offered`.
     - Disable that group: reclaim its offered slots (set `offered = 0`, return
       slots to remaining capacity).
     - If no such group exists, stop.
   - **If no progress was made** (no group received any offer), stop.

### Phase 3: Gang Scheduling Check

For each group with `gang = true` that was not disabled in Phase 2:

- Compute `pending_demand`: sum of `gpu_slots` across all **pending** tasks.
- Compute `available_in_offer = offered - active_slots`.
- If `pending_demand > 0` and `available_in_offer < pending_demand`:
  the gang group cannot schedule all its tasks simultaneously. **Disable** it.
  Reclaim `offered - presubscribed_slots` (keep presubscribed allocation).
  Set `offered = presubscribed_slots`.

**Redistribute** reclaimed slots to remaining non-disabled groups that are
unsatisfied (offered < slot_demand), ordered by `slot_demand ascending`. Each
beneficiary receives `min(slot_demand - offered, remaining_reclaimed)`.

### Phase 4: Task Release and Allocation

Releases must be processed **before** allocations so that freed resources are
available for new placements in the same scheduling round.

**Phase 4a — Releases**: For each group where `active_slots > offered`, release
preemptible allocated tasks in order of **descending position** until
`active_slots <= offered`. Free the released tasks' resources on their agents.

**Phase 4b — Allocations**: For each group where `active_slots < offered` and
the group is not disabled:
  - **Gang groups**: Attempt to place **all** pending tasks (in position order).
    For each task, find an agent with sufficient `gpu_slots` and `mem_mb`,
    and no anti-affinity violation. If **any** task cannot be placed, **roll back
    all placements** for this group — allocate nothing.
  - **Non-gang groups**: Greedily place pending tasks in position order. For each
    task, find a valid agent. If no agent has sufficient resources or placement
    would violate anti-affinity, skip that task and continue.

### Agent Selection

When placing a task from group G on an agent:
1. The agent must have `gpu_slots >= task.gpu_slots` and `mem_mb >= task.mem_mb`
   (after subtracting resources used by all currently allocated + newly placed tasks).
2. No task from any group in an anti-affinity pair with G may already be placed on
   that agent. Iterate agents in the order they appear in the input.

---

## Priority Mode

Priority scheduling allocates tasks in priority order, with optional preemption
and backfilling.

### Task Ordering

Sort all pending tasks by:
1. Group priority ascending (lower number = higher priority; null defaults to 50)
2. Position ascending
3. Submitted time ascending

Group by priority level.

### Main Allocation Loop

Process each priority level in ascending order:

1. For each pending task at this level (in position/time order):
   - Find a valid agent (sufficient resources + anti-affinity compliance).
   - If found, tentatively place the task on the agent (consume resources).

2. **Commit decision**: If no preemption releases are pending (`to_release` is empty):
   - If **not backfilling**: commit all successfully placed tasks.
   - If **backfilling** and preemption is enabled: commit only **preemptible** placed
     tasks. Roll back (unplace) non-preemptible placed tasks.
   - Otherwise: roll back all placements.
   - If preemption releases **are** pending: roll back all placements at this level.

3. If any tasks at this level could not be placed, enter **backfilling mode** for
   all subsequent priority levels.

### Preemption

When a task at priority P cannot be placed and preemption is enabled:

1. Identify **preemption candidates**: running preemptible tasks where:
   - The candidate's group priority is strictly lower (higher number) than P, **or**
   - The candidate's group priority equals P but its position is strictly higher.

2. Sort candidates: lowest priority first (highest number), then highest position first.

3. Simulate preemptions one at a time:
   - Free the candidate's resources on its agent.
   - After each preemption, check if the pending task can now be placed on any agent.
   - If placement succeeds: commit all simulated preemptions and the placement.
   - If all candidates exhausted without success: roll back all simulated preemptions.

### Backfilling

After the main loop, attempt to place **skipped preemptible** tasks on agents
with remaining resources (respecting anti-affinity). This allows low-priority
preemptible work to fill gaps left by higher-priority tasks that couldn't fit.

### Output

- `to_allocate`: dict mapping task_id → agent_id
- `to_release`: list of allocation_ids of preempted tasks
- `group_offers`: empty dict `{}`
