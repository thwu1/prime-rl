# Hubris RTOS Scheduling Safety Analysis Reference

## Overview

Hubris is a memory-isolated real-time operating system for ARM Cortex-M
microcontrollers. Each application is defined by an `app.toml` configuration
that specifies tasks with priorities, IPC dependencies (task-slots), peripheral
assignments, notification channels, and interrupt routing.

All tasks are fixed at build time. The kernel enforces strict priority
scheduling: the highest-priority ready task always runs. Priorities are small
integers where **0 is the highest priority** and higher numbers are lower
priority.

## Synchronous IPC Model

Hubris uses **fully synchronous IPC**: when task A sends a message to task B,
task A **blocks** until task B receives, processes, and replies. This has a
critical scheduling consequence: any task that sends an IPC message is
completely blocked until the recipient replies.

This blocking is **transitive**: if task A sends to task B, and task B (while
processing A's message) sends to task C, then A is transitively blocked on C
through B.

## Priority Inversion in Synchronous IPC

A **priority inversion** occurs when a higher-priority task blocks on a
lower-priority task via synchronous IPC. Because Hubris IPC is synchronous, the
higher-priority sender is completely stalled until the lower-priority receiver
finishes. Meanwhile, any medium-priority task can preempt the lower-priority
receiver, causing the high-priority sender to wait indefinitely — violating
real-time deadlines.

Because priorities are numbered with 0 as highest: if a task with priority P
has a task-slot referencing a task with priority Q, and **P < Q**, the sender
has strictly higher scheduling priority than the target. This is a direct
priority inversion.

## Priority Inheritance Protocol (PIP)

The Priority Inheritance Protocol is the standard mitigation for priority
inversion in RTOS scheduling. Under PIP, when a high-priority task blocks on a
lower-priority server via IPC, the server temporarily **inherits** the
client's priority for the duration of the request. This prevents medium-priority
tasks from preempting the server, which would delay the high-priority client.

PIP inheritance is **transitive**: if task A (priority 2) sends to server B
(priority 4), B inherits priority 2. If B then sends to server C (priority 6)
while processing A's request, C also inherits priority 2 through the chain
A → B → C. Each server in the chain runs at the priority of the
highest-priority client whose request it is (transitively) serving.

The **effective priority** of a task under PIP represents the highest
scheduling priority the task could ever be boosted to during execution. For
server tasks that are never called by anyone, the effective priority is simply
their own assigned priority.

## Fault Cascade Propagation

Hubris enforces strict memory isolation between tasks. When a task faults
(memory violation, stack overflow, panic), the kernel catches the fault and
can restart the task. However, IPC-coupled tasks are not fully isolated from
fault effects.

When a task faults and is restarted:

1. **Direct disruption**: Any task currently blocked on an IPC send to the
   faulted task receives a dead-code reply instead of the expected response.
   The blocked caller must handle this unexpected failure.

2. **Transitive disruption**: If task A is blocked on task B (via IPC), and
   B is blocked on task C (via IPC), and C faults — B receives a fault reply
   from C. If B cannot gracefully handle this (which is common, since fault
   handling in IPC chains is complex), B may itself fault. This cascades
   the disruption to A.

3. **Conservative model**: For scheduling safety analysis, we conservatively
   assume complete cascading: any task that is directly or transitively calling
   the faulting task through a chain of IPC sends could be disrupted.

The **danger score** of a task quantifies the scheduling risk posed by its
fault: it counts how many of the potentially disrupted tasks have **strictly
higher** scheduling priority (strictly lower priority number) than the faulting
task. A high danger score indicates that this task's fault could disrupt
critical, high-priority work — exactly the scenario RTOS designers must guard
against.

## IPC Cycles and Deadlock

Because IPC is synchronous and blocking, a **cycle** in the IPC dependency
graph creates a potential for deadlock. If task A calls B and task B calls A,
and both send simultaneously, both block forever waiting for the other to
receive. In production Hubris configurations, cycles are forbidden for this
reason. Detecting them is a critical safety analysis.

## Configuration Format

### Task-Slots

The `task-slots` field declares IPC targets — tasks that this task may send
messages to. Entries take two forms:

- **Simple string**: `"task_name"` — the slot name and target task name are
  identical.
- **Aliased inline table**: `{local_name = "actual_task_name"}` — the slot
  uses a local alias but references the named task.

Example:
```toml
task-slots = ["sys", "i2c_driver", {spi = "spi_driver"}, "jefe"]
```

This declares IPC targets: `sys`, `i2c_driver`, `spi_driver` (aliased as
`spi`), and `jefe`. The resolved target names for graph construction are:
`sys`, `i2c_driver`, `spi_driver`, `jefe`.

### Full Task Definition

```toml
[tasks.my_task]
name = "crate-name"
priority = 3
max-sizes = {flash = 16384, ram = 4096}
stacksize = 1024
start = true
features = ["feature1"]
uses = ["peripheral1"]
task-slots = ["other_task", {alias = "real_task"}]
notifications = ["timer", "irq-name"]
interrupts = {"hw.irq" = "irq-name"}
```

## Analysis Output Schema

The analysis tool must produce `/app/analysis.json` with this structure:

```json
{
  "direct_inversions": [
    {
      "sender": "<task that sends IPC>",
      "sender_priority": "<int>",
      "target": "<task that receives IPC>",
      "target_priority": "<int>"
    }
  ],
  "cycles": [
    ["<task_a>", "<task_b>", "..."]
  ],
  "max_call_depth": {
    "<task_name>": "<int>"
  },
  "pip_effective_priorities": {
    "<task_name>": "<int>"
  },
  "fault_cascade": {
    "<task_name>": {
      "affected_tasks": ["<sorted list of disrupted task names>"],
      "cascade_size": "<int>",
      "danger_score": "<int>"
    }
  },
  "suggested_priorities": {
    "<task_name>": "<int>"
  }
}
```

### Field Definitions

**direct_inversions**: Every IPC edge where the sender has strictly higher
scheduling priority than the target (sender priority number < target priority
number). Each entry identifies the sender task, target task, and both priority
numbers. Entries sorted by sender name, then by target name.

**cycles**: Every maximal group of tasks that form circular IPC dependencies —
tasks that are all mutually reachable through IPC call chains. Each group is a
sorted list of task names; the outer list is sorted by first element.

**max_call_depth**: For each task, the worst-case transitive blocking depth:
the longest acyclic chain of IPC calls originating from that task. A task with
no outgoing IPC edges has depth 0.

**pip_effective_priorities**: For each task, the highest scheduling priority
(lowest priority number) at which it could ever execute under PIP. Under PIP,
a server task handling an IPC request temporarily executes at the caller's
priority if the caller has higher scheduling priority, and this elevation
propagates transitively through nested IPC chains. Tasks that no other task
calls retain their own assigned priority.

**fault_cascade**: For each task, the scheduling safety impact if that task
faults. `affected_tasks` is a sorted list of every task that could be disrupted
(all tasks that directly or transitively depend on the faulting task through
IPC call chains — i.e., the faulting task's transitive callers). `cascade_size`
is the count. `danger_score` is the count of affected tasks whose scheduling
priority is strictly higher (priority number strictly less) than the faulting
task's.

**suggested_priorities**: A reassignment of priority numbers for all tasks
that eliminates every direct priority inversion. Constraints:

- `jefe` must remain at priority 0 (supervisor).
- `idle` must have the highest (numerically largest) priority number.
- For every IPC edge A → B: `suggested_priorities[A] >= suggested_priorities[B]`
  (callers must have equal or lower scheduling priority than callees).
- Tasks that are in a mutual IPC dependency cycle must share the same priority
  (since they mutually call each other, no assignment can make one strictly
  higher than the other without creating an inversion).

## Graph Output

The tool must also produce:

- `/app/ipc_graph.dot` — A Graphviz DOT-format directed graph. Each task is a
  node. Each IPC dependency (task-slot reference) is a directed edge from
  caller to callee. Edges that represent direct priority inversions must be
  visually distinguished (e.g., colored red, styled differently, or labeled).

- `/app/ipc_graph.svg` — The DOT file rendered to SVG using the `dot` command
  from the Graphviz package (e.g., `dot -Tsvg ipc_graph.dot -o ipc_graph.svg`).
