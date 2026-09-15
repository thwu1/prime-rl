A persistent (immutable) sorted map library is provided at `/app/treemap.lua`. It implements a self-balancing binary search tree with structural sharing — every mutation returns a new tree while all previous versions remain intact and accessible.

Working operations: `new`, `assoc` (insert/update), `get`, `contains`, `count`, `pairs` (sorted iterator), `from_table`, `to_table`.

The `dissoc` operation (key removal) is not implemented and currently raises an error. Implement it.

Requirements:

- After any interleaved sequence of `assoc` and `dissoc` operations, the tree must remain correctly balanced. Its height must stay logarithmic in the number of entries.
- All previous versions of the map must remain valid and unchanged after `dissoc` (persistence guarantee through structural sharing).
- `dissoc` of a key not present in the map must return the identical map object (same Lua table reference), enabling O(1) change detection.
- Sorted iteration order must be maintained after deletions.
- The `count` field must accurately reflect the number of entries after every operation.

The module is loaded via `require("treemap")` from `/app/`. Lua 5.4 is installed.