# Queue Configuration Reference

## SYNOPSIS

Queue policies are defined in TOML format. Each named queue can specify
resource eligibility constraints and admission limits.

## FORMAT

```toml
[queues.<name>]
requires = ["<property>", ...]

[queues.<name>.policy.limits]
duration = <integer_seconds>

[queues.<name>.policy.limits.range.nnodes]
min = <integer>
max = <integer>

[policy.jobspec.defaults.system]
queue = "<default_queue_name>"
```

## DIRECTIVES

### requires

Optional. Array of property name strings. Only nodes possessing **all**
listed properties are eligible for jobs in this queue. If absent or empty,
the queue imposes no property constraint.

Multiple properties combine conjunctively: a node must have every listed
property.

### policy.limits.duration

Optional. Maximum permitted job duration in integer seconds. Jobs requesting
a longer duration are rejected at submission. A request exactly equal to
the limit is accepted.

### policy.limits.range.nnodes

Optional. Node count bounds:

- **min**: Minimum nodes a job must request (default: 1).
- **max**: Maximum nodes a job may request.

Jobs outside these bounds are rejected at submission.

### policy.jobspec.defaults.system.queue

Names the default queue for jobs submitted without an explicit queue.

## RESOURCE POOL OVERLAP

Queues may have overlapping resource pools when their property requirements
intersect. For example, if queue A requires `["gpu"]` and queue B requires
`["highmem"]`, nodes possessing both properties are eligible for either
queue. Overlapping resources are allocated on a first-come basis with no
inter-queue coordination.

## SEE ALSO

`scheduling_semantics.md`, `rfc20_resource_format.md`
