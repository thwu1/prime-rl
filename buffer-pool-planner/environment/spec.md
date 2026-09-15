# Static Memory Pool Planner Specification

## Overview

A static memory pool planner reads a computation graph describing buffer allocations, usages, and deallocations within a directed acyclic graph (DAG) of operations. It produces a memory pool layout that assigns each buffer a byte offset within a per-memory-space pool, minimizing total pool size.

This is analogous to the static memory planning performed in compiler pipelines for GPU/NPU targets where dynamic allocation is unavailable or expensive.

## Input Format: `graph.json`

```json
{
  "buffers": {
    "<buffer_id>": {
      "size": <int>,
      "alignment": <int>,
      "memory_space": "<str>"
    }
  },
  "views": {
    "<view_id>": {
      "parent": "<buffer_id>",
      "offset": <int>,
      "size": <int>
    }
  },
  "operations": [
    {
      "id": "<op_id>",
      "deps": ["<op_id>", ...],
      "allocs": ["<buffer_id>", ...],
      "uses": ["<buffer_or_view_id>", ...],
      "deallocs": ["<buffer_id>", ...]
    }
  ]
}
```

### Input Constraints

- The operations form a DAG (no cycles).
- Each buffer in `buffers` is allocated by exactly one operation and deallocated by exactly one operation.
- `size` is a positive integer (bytes). `alignment` is a positive power of 2.
- Views reference buffers via `parent`. They are sub-ranges of their parent buffer.
- Views may appear in `uses` but never in `allocs` or `deallocs`.
- All inputs are well-formed: views are only used between their parent buffer's alloc and dealloc operations.

## Output Format: `solution.json`

```json
{
  "schedule": ["<op_id>", ...],
  "assignments": {
    "<buffer_id>": <int>
  },
  "pool_sizes": {
    "<memory_space>": <int>
  }
}
```

### Output Requirements

1. **Schedule**: A valid topological ordering of all operations in the DAG. Every operation appears exactly once. For each operation, all its dependencies appear earlier in the schedule.

2. **Assignments**: Maps each buffer (from `buffers`, not `views`) to a non-negative integer byte offset within its memory space's pool.

3. **Pool sizes**: For each memory space, the pool size equals `max(offset + size)` over all buffers assigned to that space.

## Definitions

**Lifetime**: Given a schedule, a buffer's lifetime interval is `[alloc_step, dealloc_step]` where `alloc_step` is the schedule index of the operation that allocates the buffer and `dealloc_step` is the schedule index of the operation that deallocates it.

**Conflict**: Two buffers in the same memory space conflict if their lifetime intervals have non-empty intersection. Intervals `[a1, d1]` and `[a2, d2]` intersect if and only if `a1 <= d2` and `a2 <= d1`.

**Byte range**: A buffer assigned offset `o` with size `s` occupies byte range `[o, o+s)`.

## Correctness Constraints

1. **No memory overlap for conflicting buffers**: If two buffers in the same memory space conflict (overlapping lifetimes under the chosen schedule), their byte ranges must not overlap.

2. **Alignment**: Each buffer's assigned offset must be a multiple of its `alignment` value.

3. **Non-negative offsets**: All offsets must be >= 0.

4. **Tight pool sizes**: Pool size for each memory space must exactly equal the maximum `(offset + size)` over all buffers in that space.

5. **Memory spaces are independent**: Buffers in different memory spaces are assigned offsets independently.

## Objective

Minimize the pool size for each memory space. This requires both:

- **Good scheduling**: The topological order directly determines buffer lifetimes. A memory-aware schedule reduces the number of simultaneously-live buffers, which reduces the pool size.
- **Optimal packing**: Given the conflict graph induced by the schedule, assign offsets to minimize the maximum `(offset + size)` while respecting alignment.

## Example

Input:
```json
{
  "buffers": {
    "A": {"size": 1024, "alignment": 64, "memory_space": "main"},
    "B": {"size": 512, "alignment": 64, "memory_space": "main"}
  },
  "views": {},
  "operations": [
    {"id": "op0", "deps": [], "allocs": ["A"], "uses": [], "deallocs": []},
    {"id": "op1", "deps": ["op0"], "allocs": [], "uses": ["A"], "deallocs": ["A"]},
    {"id": "op2", "deps": ["op1"], "allocs": ["B"], "uses": [], "deallocs": []},
    {"id": "op3", "deps": ["op2"], "allocs": [], "uses": ["B"], "deallocs": ["B"]}
  ]
}
```

Output:
```json
{
  "schedule": ["op0", "op1", "op2", "op3"],
  "assignments": {"A": 0, "B": 0},
  "pool_sizes": {"main": 1024}
}
```

Buffer A lives during steps [0, 1] and buffer B lives during steps [2, 3]. They do not conflict, so B reuses A's memory. Pool size is 1024 instead of 1536.
