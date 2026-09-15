# Async-Finish Computation Graph Model

This document describes the parallel computation model used in the trace files.

## Program Representation

Programs are represented as JSON ASTs. Each node has a `type` field and type-specific fields:

| Type | Fields | Description |
|------|--------|-------------|
| `seq` | `body`: array of nodes | Sequential composition; execute children in order |
| `compute` | `cost`: integer | Computation with given time cost |
| `read` | `var`: string, `id`: string | Read a shared variable (cost 0) |
| `write` | `var`: string, `id`: string | Write a shared variable (cost 0) |
| `async` | `child`: node | Spawn a new parallel task to execute `child` |
| `finish` | `body`: node | Execute `body` and wait for all async tasks spawned (transitively) within `body` to complete |

## Computation Graph Construction

A **computation graph** is a directed acyclic graph (DAG) where:
- **Nodes** are called **steps** — maximal sequential segments of computation within a single task
- **Edges** represent ordering constraints (happens-before relations)

### Step Boundaries

Steps are delimited by `async` spawn points. When an `async` node is encountered during execution:

1. The **current step ends** (everything accumulated so far in this task becomes one step)
2. A **new step begins** for the async task's body (the `child`)
3. A **new step begins** for the continuation of the parent task (the next items in the enclosing `seq` after the `async`)

A **finish** node does NOT split the current step at entry. However, when a `finish` completes (at exit), a new step begins for the continuation after the finish.

### Edge Types

Three types of directed edges connect steps:

1. **Spawn edge**: From the step before an `async` to the first step of the async's body. Represents the ordering: parent executes before child starts.

2. **Continue edge**: From the step before an `async` to the continuation step (next step in the parent task after the spawn). Also from the last step of a `finish` body to the step after the finish.

3. **Join edge**: From the last step of each async task spawned within a `finish` scope to the step immediately after the `finish`. Represents the ordering: async must complete before the finish's continuation begins.

### Finish Scope Rules

Each `async` task is associated with its **innermost enclosing `finish`** scope:

- When a `finish` completes, join edges connect the last step of every async task spawned within that finish (at any nesting depth, unless enclosed by a deeper nested finish) to the step after the finish.
- If an async task spawns another async without an intervening nested finish, both asyncs belong to the same enclosing finish scope.
- If an async contains its own `finish`, asyncs spawned within that inner finish join to the inner finish's continuation, not the outer finish.

### Step Cost

A step's cost is the sum of the `cost` fields of all `compute` nodes within that step. `read` and `write` nodes have cost 0 — they are markers for data race detection.

## Analysis Metrics

### Work
Total work = sum of all step costs in the computation graph.

### Span (Critical Path Length)
Span = the weight of the longest path from any source node to any sink node, where path weight = sum of node costs along the path.

### Ideal Parallelism
Ideal parallelism = work / span.

### Data Races
Two memory accesses constitute a **data race** if ALL of the following hold:
1. They access the **same variable**
2. At least one is a **write**
3. They are **not ordered** by the happens-before relation (i.e., neither step is reachable from the other in the computation graph)

Each race is reported as a sorted pair of access IDs (the `id` fields from `read`/`write` nodes).
