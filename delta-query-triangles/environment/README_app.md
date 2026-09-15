# Delta Queries for Incremental Triangle Maintenance

## The Problem

Given a directed graph and a stream of edge updates (insertions and deletions), maintain an accurate count of **directed triangles** — ordered triples `(a, b, c)` of distinct nodes where edges `a→b`, `b→c`, and `a→c` all exist.

Recomputing the triangle count from scratch after each batch of updates is too slow for large graphs. Instead, we can compute just the **change** in triangle count caused by each batch.

## Delta Query Decomposition

The triangle query can be written as:

    Q(a,b,c) := E1(a,b), E2(b,c), E3(a,c)

where `E1`, `E2`, `E3` are all the same edge relation. By differentiating with respect to each copy, we get three **delta rules**:

    dQ/dE1:  dE(a,b) × E(b,c) × E(a,c)
    dQ/dE2:  dE(b,c) × E(a,b) × E(a,c)
    dQ/dE3:  dE(a,c) × E(a,b) × E(b,c)

Each changed edge is processed through **all three rules**, playing a different role in each. Rule 1 treats a changed edge `(x,y)` as `E1(a=x, b=y)` and looks for `c`. Rule 2 treats it as `E2(b=x, c=y)` and looks for `a`. Rule 3 treats it as `E3(a=x, c=y)` and looks for `b`.

## The Alt/Neu Ordering

If multiple edges of the same triangle change in a single batch, naively applying all three rules would count that triangle's change multiple times. The solution is the **alt/neu** (old/new) ordering convention from differential dataflow:

- **Rule 1**: Joined relations `E2` and `E3` use the **new** graph state (after applying the batch)
- **Rule 2**: `E1` uses the **old** graph state (before the batch); `E3` uses the **new** state
- **Rule 3**: Both `E1` and `E2` use the **old** graph state

Concretely, for each changed edge `(x, y)` with diff `d` (+1 or -1):

| Rule | Role | Find | Source for lookup | Validate | Source for check |
|------|------|------|-------------------|----------|-----------------|
| 1 | E1(a=x, b=y) | c via b→c | **new** fwd[b] | a→c exists? | **new** fwd[a] |
| 2 | E2(b=x, c=y) | a via →b | **old** rev[b] | a→c exists? | **new** fwd[a] |
| 3 | E3(a=x, c=y) | b via a→b | **old** fwd[a] | b→c exists? | **old** fwd[b] |

Each discovered triple contributes `d` (the edge's diff) to the total triangle count change for the batch.

### Why This Works

Consider a batch that inserts all three edges of a new triangle `(a,b,c)` simultaneously:
- Rule 1 processing change `(a,b)`: looks up `b→c` in **new** graph (found!) and checks `a→c` in **new** graph (found!) → triangle counted once
- Rule 2 processing change `(b,c)`: looks up `→b` in **old** graph — edge `a→b` didn't exist before this batch → not found → no count
- Rule 3 processing change `(a,c)`: looks up `a→b` in **old** graph — didn't exist → no count

Result: the triangle is counted exactly once. The ordering guarantees this property for any combination of simultaneous changes.

## Consolidation

Before applying delta rules, changes within a batch must be **consolidated**: if the same edge appears multiple times, sum the diffs and discard entries with net-zero diff. For example, if edge `(3,7)` is inserted (+1) and then deleted (-1) in the same batch, the net change is 0 and should be ignored.

## Data Format

- `initial_edges.txt`: one `src dst` pair per line (space-separated integers)
- `updates.jsonl`: one JSON array per line; each element is `[src, dst, diff]`
- `results.json` (output): JSON array of integers — triangle count at each step
