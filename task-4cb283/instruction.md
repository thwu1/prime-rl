The `/app/` directory contains a C99 Hash Array Mapped Trie (HAMT) implementation with ephemeral and persistent key-value operations, iterators, and a custom memory allocator. The data structure uses bitmap-indexed 32-way branching with pointer tagging to distinguish leaf nodes from internal nodes, and supports structural sharing for persistent (immutable) operations.

The header `/app/include/hamt.h` declares three persistent set operations that are not yet implemented:

- `hamt_punion(t1, t2, on_conflict)` — returns a new HAMT containing all keys from both `t1` and `t2`. When a key exists in both, `on_conflict(key, value_from_t1, value_from_t2)` determines the result value.
- `hamt_pintersection(t1, t2, on_conflict)` — returns a new HAMT containing only keys present in both `t1` and `t2`, with values resolved by `on_conflict`.
- `hamt_pdifference(t1, t2)` — returns a new HAMT containing keys in `t1` that are not in `t2`.

Implement these three functions. The implementations must:

1. Use structural sharing — the result HAMT should share subtree nodes with the inputs where possible, following the same pattern as the existing `hamt_pset` and `hamt_premove` operations.
2. Correctly handle all combinations of node types at each trie level (both leaves, one leaf and one internal, both internal).
3. Handle hash collisions through the existing multi-generation hash exhaustion mechanism.
4. Maintain accurate `size` tracking in the returned HAMT.
5. Not modify either input HAMT (persistent semantics).

The implementations must go in `/app/src/hamt.c` where they have access to internal types and helper functions.