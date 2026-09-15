# Fork-Join Parallel Program Analyzer with Phaser Synchronization

## Computation Model

Programs use the **async-finish** fork-join parallelism model extended with **phaser-based point-to-point synchronization**, as found in frameworks such as Habanero-Java (HJ).

### Base Operations

- **compute(cost)**: A computation step taking `cost` time units.
- **read(var)**: A read access to shared variable `var` (takes 1 time unit).
- **write(var)**: A write access to shared variable `var` (takes 1 time unit).
- **async(task, body)**: Spawns a new parallel task to execute `body`. The parent task continues immediately after spawning; the child executes concurrently.
- **finish(id, body)**: Executes `body` and then waits for **all** async tasks transitively spawned within the scope to complete before continuing.

### Phaser Operations

Phasers provide point-to-point synchronization between tasks through a split-phase signal/wait protocol. Each task maintains per-phaser phase counters (signal counter and wait counter, both starting at 0).

- **signal(phaser_id)**: The current task signals the phaser, creating a cost-0 DAG node. Records a signal event at the task's current signal phase for this phaser, then increments the signal phase counter. Non-blocking.
- **wait(phaser_id)**: The current task waits on the phaser, creating a cost-0 DAG node. Records a wait event at the task's current wait phase for this phaser, then increments the wait phase counter. Blocks until all tasks registered in SIG or SIG_WAIT mode have signaled the corresponding phase.
- **next(phaser_id)**: Shorthand for `signal` immediately followed by `wait` on the same phaser. Creates two cost-0 nodes (one for signal, one for wait) connected by a continuation edge.

#### Registration Modes

Tasks register on phasers before execution begins. The `phasers` field in the program JSON declares registrations. Each task is registered with one of three modes:

- **SIG**: Task will only signal (contributes to unblocking waiters but never blocks itself).
- **WAIT**: Task will only wait (blocks until all SIG/SIG_WAIT registrants have signaled the current phase).
- **SIG_WAIT**: Task both signals and waits.

#### Phase Matching and Happens-Before

The phaser happens-before rule: for phaser P and phase number n, **every** signal(P) at phase n **happens-before every** wait(P) at phase n. This translates to a DAG edge from each signal node at phase n to each wait node at phase n.

A task performing multiple signal operations on the same phaser increments its signal counter each time (phases 0, 1, 2, ...). Likewise for wait. The k-th signal by any task matches with the k-th wait by any other task on the same phaser.

The main program body executes in a task called "MAIN".

## JSON Program Format

```json
{
    "name": "program_name",
    "phasers": [
        {"id": "P1", "registered": {"T1": "SIG_WAIT", "T2": "WAIT"}},
        ...
    ],
    "body": [ ...operations... ]
}
```

The `phasers` field is optional (absent or empty for programs without phaser synchronization).

Each operation is one of:

| Operation | Format |
|-----------|--------|
| compute   | `{"op": "compute", "cost": <int>, "id": "<unique_id>"}` |
| read      | `{"op": "read", "var": "<var_name>", "id": "<unique_id>"}` |
| write     | `{"op": "write", "var": "<var_name>", "id": "<unique_id>"}` |
| async     | `{"op": "async", "task": "<task_name>", "body": [...]}` |
| finish    | `{"op": "finish", "id": "<finish_id>", "body": [...]}` |
| signal    | `{"op": "signal", "phaser": "<phaser_id>", "id": "<unique_id>"}` |
| wait      | `{"op": "wait", "phaser": "<phaser_id>", "id": "<unique_id>"}` |
| next      | `{"op": "next", "phaser": "<phaser_id>", "id": "<unique_id>"}` |

## Computation DAG Construction

Each `compute`, `read`, `write`, `signal`, and `wait` operation creates a **node** in the computation DAG. The cost of `read` and `write` nodes is 1 time unit; `compute` nodes have the specified cost; `signal` and `wait` nodes have cost 0. For `next`, two nodes are created (signal node then wait node), both with cost 0, connected by a continuation edge.

Edges encode execution ordering:

- **Continuation**: Sequential operations within a task are connected by directed edges (each operation's node points to the next one in the same task's body).
- **Spawn**: When an `async` is encountered, an edge connects the parent task's current node to the first node of the child async's body. The parent's "current node" does NOT advance past an `async` — the parent only advances on `compute`, `read`, `write`, `signal`, `wait`, `next`, or at `finish` boundaries. Multiple asyncs spawned consecutively all have spawn edges from the same parent node.
- **Join**: At the end of a `finish` scope, the last node of each enclosed async task and the parent's last node within the finish body all have edges leading to a common join point. Execution after the finish continues from this join point.
- **Phaser**: For each phaser P and phase number n, directed edges connect every signal(P, n) node to every wait(P, n) node.

## Analysis Requirements

Create `/app/analyzer.py` that accepts one or more program JSON file paths as command-line arguments:

```
python3 /app/analyzer.py /app/programs/prog1.json /app/programs/prog2.json ...
```

For each program, write:
1. A result JSON file to `/app/results/<program_name>.json`
2. A Graphviz DOT file to `/app/graphs/<program_name>.dot`

### Metrics

**Work (T_1):** Sum of all node costs in the DAG.

**Span (T_inf):** Length of the longest weighted path through the DAG (the critical path). Path length is the sum of node costs along the path.

**Ideal Parallelism:** `Work / Span`, rounded to 4 decimal places.

### Data Race Detection

Two memory access nodes (read or write) constitute a **data race** if all three conditions hold:

1. They access the **same variable**.
2. At least one is a **write**.
3. They are **not ordered** by the happens-before relation — i.e., neither node is reachable from the other via directed paths in the DAG.

### DOT Output

Each DOT file must represent the program's computation DAG as a Graphviz digraph. Edge types (continuation, spawn, join, phaser) must be visually distinguished (e.g., via different styles or colors).

### Result JSON Format

```json
{
    "name": "<program_name>",
    "work": <int>,
    "span": <int>,
    "ideal_parallelism": <float>,
    "data_races": [
        {"access1": "<id>", "access2": "<id>", "variable": "<var>"},
        ...
    ]
}
```

Within each race entry, `access1 < access2` lexicographically. The `data_races` list is sorted by `(variable, access1, access2)`.
