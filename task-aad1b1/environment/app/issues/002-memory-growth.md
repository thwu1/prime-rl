# Issue 002: Excessive memory consumption in long-running service

## Reported by: platform-team
## Severity: Medium
## Component: store/persistent_map.py

## Description

The versioned store service shows steadily increasing memory usage over
time. Profiling with `tracemalloc` (run `make profile` from `/app/`)
indicates far more node allocations than expected.

### Sub-issue 2a: No-op updates allocate new nodes

Updating a key with its existing value should be a no-op that returns the
identical map object, but instead it creates a full copy of the modified
path. This defeats structural sharing — our snapshot system relies on
object identity (`is` checks) to skip unchanged subtrees.

Run `make bench` from `/app/` to see the "No-op identity" diagnostic
check.

### Sub-issue 2b: Deleted regions remain over-structured

After deleting entries that caused trie branching, the internal nodes
are not simplified. Sub-nodes that shrink to contain a single entry
should be folded back into the parent as an inline data entry, reducing
both depth and memory. The same applies to hash-collision buckets that
shrink to a single entry.

Run `make bench` to see the "Delete compaction" diagnostic check.

## Expected behavior

- `m.insert(k, v)` where `m[k] == v` returns `m` (same object)
- After deletion, singleton child nodes are compacted into the parent
