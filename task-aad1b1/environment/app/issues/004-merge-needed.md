# Issue 004: Need efficient merge operation for replica reconciliation

## Requested by: replication-team
## Priority: High
## Component: store/persistent_map.py

## Description

Our distributed caching layer maintains multiple PersistentMap replicas that
diverge during network partitions. After a partition heals, we need to
reconcile the divergent versions by merging them efficiently.

Currently we iterate both maps and build a new one from scratch with
`from_dict()` — this is O(n) even when 95%+ of the entries are identical
across replicas. Since both replicas typically descend from a common
ancestor map, the CHAMP trie's structural sharing means most of their
internal subtrees are the **same object in memory**. A merge algorithm
that detects this and skips shared subtrees could reconcile in O(diff)
instead of O(n).

## Required API

```python
merged = map_a.merge(map_b, conflict_fn=None)
```

### Semantics

- Returns a new `PersistentMap` containing the union of all keys from
  both maps.
- When a key exists in both maps with the **same** value, that value is
  preserved.
- When a key exists in both maps with **different** values,
  `conflict_fn(key, self_value, other_value)` determines the result.
- When `conflict_fn` is `None`, the **other** map's value wins by default.
- Keys present in only one map are always included in the result.

### Structural sharing requirement

The merge algorithm **must** exploit CHAMP structural sharing:

- When two child subtrees at the same trie position are the **same
  object** (`a is b`), reuse one of them without traversal.
- Must correctly handle all node-type combinations at each 5-bit trie
  slot:
  - `SubNode + SubNode` → recursive merge
  - `data + data` (same key) → value comparison / conflict resolution
  - `data + data` (different keys) → push both down into a sub-node
  - `data + SubNode` / `SubNode + data` → insert data entry into
    the opposing subtree
  - `CollisionNode + CollisionNode` → merge collision buckets
  - Only-in-one-side entries → include directly

### Performance target

Merging two maps of 5000 entries that share a common ancestor and differ
in ~10 entries should complete measurably faster than building the merged
result via `from_dict()`. Use `make profile-merge` to validate with
`cProfile`.

## Acceptance criteria

1. Correct union semantics with pluggable conflict resolution
2. `conflict_fn(key, self_value, other_value)` argument ordering
3. Identity-based structural sharing (shared subtrees skipped in O(1))
4. Handles all CHAMP node-type combinations
5. `len()` on merged result is correct
6. Original maps remain unchanged (persistence)
