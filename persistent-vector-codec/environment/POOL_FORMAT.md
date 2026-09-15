# Pool Serialization Format for Persistent Vectors

## Overview

This format serializes persistent (immutable) vectors using a pool-based
representation that preserves structural sharing. Multiple vectors can share
internal tree nodes, so related vector versions are stored compactly.

## Radix Balanced Tree Background

Each persistent vector is internally a radix balanced tree with a **tail
optimization**:

- **Inner nodes** branch with up to `M = 2^B` children.
- **Leaf nodes** store up to `L = 2^BL` elements.
- **Tail**: a special leaf buffer holding the rightmost elements of the vector.
  The tail is stored outside the tree body.

All body leaves (those inside the tree, not the tail) are fully packed with
exactly `L` elements. Only the tail may hold fewer than `L` elements
(between 1 and `L` inclusive).

The tree body is balanced: only the rightmost spine may have partially-filled
inner nodes (fewer than `M` children). All other inner nodes have exactly `M`
children.

## JSON Schema

```json
{
  "B": <int>,
  "BL": <int>,
  "leaves": [ [<id>, [<values...>]], ... ],
  "inners": [ [<id>, {"children": [<child_ids...>], "relaxed": false}], ... ],
  "vectors": [
    {"root": <inner_id | null>, "tail": <leaf_id | null>, "size": <int>},
    ...
  ]
}
```

### Fields

- **B**: Log2 of inner node branching factor. `M = 2^B`.
- **BL**: Log2 of leaf node capacity. `L = 2^BL`.
- **leaves**: Array of `[id, values]` pairs. Each leaf is identified by a
  numeric ID and stores a list of element values.
- **inners**: Array of `[id, node_data]` pairs. Each inner node has a
  `children` array listing child IDs and a `relaxed` flag (always `false`
  for standard balanced trees).
- **vectors**: Array of vector descriptors:
  - `root`: ID of the root inner node, or `null` when the entire vector fits
    in the tail alone (size <= L).
  - `tail`: ID of the tail leaf, or `null` for empty vectors.
  - `size`: total number of logical elements.

### Node ID Namespaces

Leaf IDs and inner node IDs occupy **separate namespaces**. A leaf with ID 5
and an inner node with ID 5 are distinct nodes. When resolving inner node
children, you must determine whether each child ID refers to an inner node or
a leaf node based on the tree depth at that level.

### Tree Depth and Node Type Resolution

The tree depth is **not stored explicitly**. It must be derived from the
vector's element count and the branching parameters:

1. Compute the tail count: how many elements are in the tail leaf.
   - If `size <= L`: all elements are in the tail; `root` is `null`.
   - If `size > L`: `tail_count = size mod L` when nonzero, else `L`.
2. `body_count = size - tail_count`
3. `num_body_leaves = body_count / L` (exact division; all body leaves are full)
4. The tree depth `d` is the smallest integer `>= 1` such that `M^d >= num_body_leaves`.

At the root (depth `d`):
- If `d = 1`: children are **leaf IDs**.
- If `d > 1`: children are **inner node IDs**. Each level down decreases
  the effective depth by 1 until depth 1, where children become leaf IDs.

### Structural Sharing

Two vectors share a node when they reference the same node ID (within the
same namespace). Because the tree is persistent and immutable, shared nodes
are guaranteed to hold the same data. When traversing two vectors
simultaneously, matching node IDs at the same position indicate identical
subtrees that can be skipped entirely.

### Reconstruction Order

To reconstruct a vector's elements in order:
1. Traverse the tree body left-to-right (following inner node children arrays
   in order, recursing into subtrees).
2. Append the tail leaf's elements.
