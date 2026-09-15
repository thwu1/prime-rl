`/app/bptree_zset.py` implements a B+ tree backed sorted set (like Redis ZSET) that replaces skip-list indexing with a B+ tree for lower per-entry memory overhead. It supports `zadd`, `zscore`, `zrem`, `zrank`, `zrange`, `zrangebyscore`, and JSON serialization. The implementation has correctness bugs and missing features:

- Leaf node splits promote the wrong separator key to the parent, causing certain entries to become unreachable via tree navigation. Point deletions for affected keys fail silently, leaving orphan entries that corrupt range scans.
- Leaf node merges during deletion do not update the doubly-linked leaf chain: the merged-away node remains linked, producing duplicate entries in sequential scans.
- `zrangebyscore` skips the first matching entry at the lower score boundary due to an off-by-one after binary-searching for the start position.
- `zrank` is unimplemented (returns -1). It should compute the 0-based rank in O(log n) using augmented subtree sizes stored at each node.
- Subtree sizes (`subtree_size` field on each `BPNode`) are never maintained — they stay at zero. These must be correctly incremented/decremented during insertions, deletions, splits, merges, and borrow operations for rank queries to work.

Fix all bugs and implement the missing rank infrastructure. Preserve the public API signatures and the `BPNode.subtree_size` field.