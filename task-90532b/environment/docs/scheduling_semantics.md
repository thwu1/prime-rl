# sched-simple(7) -- Scheduling System Reference

## SYNOPSIS

This document describes the allocation policy, queue management semantics, and
event processing model of the sched-simple scheduling module.

## RESOURCE ALLOCATION

### Exclusive Allocation

Node allocation is exclusive: once a node is assigned to a running job, no
other job may use any resources on that node until the allocating job completes
and the resources are freed.

### Selection Policy

The allocator uses a deterministic selection strategy. Eligible nodes are
considered in ascending rank order, and the first N nodes satisfying all
requirements are selected, where N equals the requested node count. If fewer
than N eligible nodes exist, the allocation attempt fails.

### Eligibility Criteria

A node (identified by its integer rank) is eligible for a given job if and
only if ALL of the following conditions hold simultaneously:

1. The node possesses every property in the queue's `requires` set.
2. The node possesses every property in the job's per-submission constraint set.
3. The node's core count >= the job's `ncores_per_node` request.
4. The node's GPU count >= the job's `ngpus_per_node` request.
5. The node is not in the **drained** state.
6. The node is not currently **allocated** to another running job.

Queue-level and job-level property constraints are combined conjunctively:
the node must satisfy both sets simultaneously.

## QUEUE MANAGEMENT

### Overview

Each named queue maintains its own independent FIFO pending list. Queues do
not interfere with each other -- a job pending in one queue has no effect on
scheduling decisions in any other queue.

### Admission Control

At submission time, the following queue limits are validated **before** any
allocation attempt:

- **Duration**: If the job's requested duration exceeds the queue's configured
  duration limit, the job is immediately rejected. The comparison is strict
  greater-than: a request exactly equal to the limit is permitted.

- **Node count (max)**: If the job's requested node count exceeds the queue's
  maximum node limit, the job is rejected.

- **Node count (min)**: If the job's requested node count is below the queue's
  minimum node limit, the job is rejected.

Jobs failing admission control never enter the pending list.

### Pending List Behavior

When a job passes admission control:

- If the queue's pending list is **non-empty**, the new job is appended to
  the end of the list without attempting allocation. This preserves FIFO
  ordering.

- If the queue's pending list is **empty**, allocation is attempted
  immediately. On success the job enters the running state. On failure it
  is placed at the end of the pending list.

A blocked head-of-queue job prevents allocation attempts for all jobs behind
it in the same queue. This enforces strict first-come-first-served ordering:
later jobs cannot skip ahead of an earlier job that is waiting for resources.

## STATE TRANSITIONS

### Drain

A drain event removes the specified nodes from the schedulable pool. Drained
nodes are ineligible for new allocations. **Drain does not trigger
rescheduling** of pending jobs -- removing resources from the available pool
cannot help any waiting job.

### Undrain

An undrain event restores previously drained nodes to the schedulable pool.
**Undrain triggers rescheduling**: the system re-evaluates pending jobs
across all queues since newly available resources may satisfy pending requests.

### Job Completion

A completion event frees all nodes allocated to the completing job and
**triggers rescheduling** across all queues.

### Rescheduling Procedure

When rescheduling is triggered (by completion or undrain), the system
processes all queues that have pending jobs. For each such queue:

- Attempt allocation for the head (oldest) pending job.
- On success: remove it from the list, transition to running, then repeat
  with the new head of the list.
- On failure: stop processing that queue entirely. The blocked head prevents
  consideration of any subsequent jobs (FIFO constraint).

## EVENT FORMAT

Events are recorded in JSONL format, one event per line:

```json
{"sequence": <int>, "name": "<event_type>", "context": {<payload>}}
```

### Event Types

**job.submit** -- Job submission request.
Context fields: `job_id` (string), `queue` (string), `nnodes` (int),
`ncores_per_node` (int), `ngpus_per_node` (int), `duration` (int, seconds),
`constraints` (array of property name strings).

**job.complete** -- Job completion notification.
Context fields: `job_id` (string).

**resource.drain** -- Node drain operation.
Context fields: `targets` (idset string of ranks), `reason` (string).

**resource.undrain** -- Node undrain operation.
Context fields: `targets` (idset string of ranks).

Events are processed strictly in `sequence` order. Each event is fully
resolved (including any triggered rescheduling) before processing the next.
The `sequence` value is the event identifier referenced in output timing
fields.

## IDSET NOTATION

Rank sets use compact range notation:

    "5"       -> {5}
    "0-3"     -> {0, 1, 2, 3}
    "8-11"    -> {8, 9, 10, 11}
    "4-7,12-15" -> {4, 5, 6, 7, 12, 13, 14, 15}

Ranges are inclusive on both ends. Multiple ranges or singletons are
separated by commas with no spaces.

## SEE ALSO

`rfc20_resource_format.md`, `queue_configuration.md`
