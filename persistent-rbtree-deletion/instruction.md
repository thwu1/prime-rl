The file `/app/rbtree.lua` implements a persistent (immutable) red-black tree in Lua. Insertion, search, traversal, and invariant validation are fully working. Deletion is not implemented — several internal functions are stubbed with `error()` calls.

Implement deletion so that `rbtree.delete(tree, key)` returns a new tree with the key removed. The implementation must satisfy:

- `rbtree.validate(tree)` passes after every deletion.
- Persistence is preserved: previous tree references must remain unchanged after deletion.
- Deleting a key not present in the tree returns the same tree object (identity check via `rawequal`).
- Correct behavior under sequences of hundreds of interleaved insertions and deletions.

Keys are numeric and ordered by `<`/`>`.