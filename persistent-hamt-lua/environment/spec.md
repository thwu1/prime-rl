# HAMT Specification

## Overview

A Hash Array Mapped Trie (HAMT) is a persistent (immutable) hash map that uses
structural sharing for efficient copy-on-write semantics. Each modification
returns a new map while preserving all previous versions.

## Configuration

| Parameter    | Value |
|-------------|-------|
| BITS        | 5     |
| WIDTH       | 32 (2^BITS) |
| MASK        | 31 (WIDTH-1) |
| HASH\_BITS  | 30    |
| Max depth   | 6 levels (shifts 0, 5, 10, 15, 20, 25) |

## Node Types

### LEAF (type = 1)

Terminal node storing a single key-value pair.

Fields: `type`, `hash`, `key`, `value`

### BITMAP (type = 2)

Interior node using bitmap-indexed compression. A 32-bit bitmap indicates which
of the 32 possible child slots are occupied. The children are stored in a
compact array whose length equals `popcount(bitmap)`. The position of a child
in this array is determined by counting set bits below its slot's bit position.

Fields: `type`, `bitmap`, `children`

Given a hash `h` at shift level `s`:
- The 5-bit fragment is `(h >> s) & 31`
- The bit mask is `1 << fragment`
- The child's position in the compact array is `popcount(bitmap & (bit - 1)) + 1`

### COLLISION (type = 3)

A bucket of entries that share the same full hash value but have different keys.

Fields: `type`, `hash`, `entries`

`entries` is a Lua array of `{key = k, value = v}` tables.

## Core Algorithms

### get\_node(node, shift, hash, key) → (value, found)

- **nil**: `(nil, false)`
- **LEAF**: if `key == node.key`, return `(node.value, true)`; else `(nil, false)`
- **COLLISION**: if `hash == node.hash`, scan entries for matching key
- **BITMAP**: compute `bit = bitpos(hash, shift)`. If `bitmap & bit ~= 0`,
  recurse into `children[index(bitmap, bit)]` at `shift + 5`; else absent

### assoc\_node(node, shift, hash, key, value) → (new\_node, added)

`added` is `true` when a genuinely new key was inserted (affects count).

- **nil**: return `(make_leaf(hash, key, value), true)`
- **LEAF**:
  - Same hash, same key, same value → return `(node, false)` (no change)
  - Same hash, same key, different value → return `(make_leaf(...), false)`
  - Same hash, different key → return `(make_collision(hash, [old, new]), true)`
  - Different hash → return `(create_node(shift, old_leaf, new_leaf), true)`
- **COLLISION**:
  - Same hash: scan entries. If key found, update that entry. If not found,
    append a new entry.
  - Different hash: the collision node and a new leaf must be separated.
    Compare hash fragments at the current shift. If fragments differ, create a
    BITMAP containing both. If fragments match, recurse at `shift + 5` and
    wrap the result in a single-child BITMAP.
- **BITMAP**:
  - Bit set: recurse into the child. If child reference is unchanged, return
    same node.
  - Bit not set: insert a new LEAF into the children array and set the bit.

### create\_node(shift, leaf1, leaf2)

Build a BITMAP node from two leaves whose hashes are known to differ.

Compare hash fragments at `shift`:
- If different: create a BITMAP with both leaves placed at their respective
  positions (ordered by popcount-based indexing).
- If same: recurse at `shift + 5` and wrap the child in a single-child
  BITMAP at the shared fragment position.

Since the hashes differ within 30 bits, this recursion always terminates
within 6 levels.

### dissoc\_node(node, shift, hash, key) → new\_node

Returns `nil` if the node becomes empty. Returns the **same node reference**
if the key was not found (no-op).

- **nil**: `nil`
- **LEAF**: if key matches, `nil`; else return same node
- **COLLISION**: remove matching entry. If only 1 entry remains, collapse to
  LEAF. If key not found, return same node.
- **BITMAP**:
  - Bit not set: return same node
  - Recurse into child. If child unchanged, return same node.
  - If child becomes nil: clear the bit. If `bitmap == 0`, return nil. If
    exactly 1 child remains and it is a LEAF or COLLISION, promote it
    (return it directly — this collapses unnecessary single-child bitmap
    chains). Otherwise return a new BITMAP without the removed child.
  - If child is modified but non-nil: return new BITMAP with updated child.

## Structural Sharing Contract

Every mutation creates new nodes **only along the path** from root to the
affected leaf. Unmodified subtrees are shared by reference between old and new
versions.

When an operation produces no actual change:
- `assoc` with the same key and identical value
- `dissoc` of an absent key
- `dissoc` on an empty map

the implementation **must** return the identical input object (same Lua table
reference). This enables O(1) change detection.

## Public API

A map is represented as `{root = node_or_nil, count = integer}`.

| Function | Signature | Description |
|----------|-----------|-------------|
| `new`      | `() → map` | Empty map |
| `assoc`    | `(map, key, value) → map` | Insert or update |
| `dissoc`   | `(map, key) → map` | Remove key |
| `get`      | `(map, key [, not_found]) → value` | Lookup |
| `contains` | `(map, key) → bool` | Membership test |
| `count`    | `(map) → int` | Entry count |
| `pairs`    | `(map) → iterator` | Key-value iterator |
| `from_table` | `(table) → map` | Build from Lua table |
| `to_table` | `(map) → table` | Convert to Lua table |
