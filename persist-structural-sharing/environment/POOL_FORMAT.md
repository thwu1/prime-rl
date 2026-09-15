# Pool Serialization Format

The pool captures the internal tree structure of one or more `PersistentVector`
instances, deduplicating shared subtrees so that each unique node appears exactly
once.

## Top-level structure

```json
{
  "B": 2,
  "nodes": {
    "<id>": { ... },
    ...
  },
  "vectors": {
    "<name>": { ... },
    ...
  }
}
```

| Field     | Description |
|-----------|-------------|
| `B`       | Branching parameter (always `2` for this implementation; `M = 2^B = 4`). |
| `nodes`   | Dictionary mapping **string** node IDs to node descriptors. |
| `vectors` | Dictionary mapping vector names to tree-shape descriptors. |

## Node descriptors

Node IDs are non-negative integers.  Dictionary keys are their **string**
representations (`"0"`, `"1"`, …).  All cross-references (inner-node children,
vector root/tail) use **integer** IDs.

### Leaf node

```json
{ "type": "leaf", "data": [<value>, ...] }
```

`data` contains the leaf's values in order.  May be empty (for an empty tail).

### Inner node

```json
{ "type": "inner", "children": [<child_id>, ...] }
```

`children` is a list of integer node IDs.  Each child may be a leaf **or**
another inner node, depending on tree depth.  At the lowest inner level
(shift = B), children are leaves; at higher levels, children are inner nodes.
The list may be empty (for the root of a tail-only vector).

## Vector descriptors

```json
{
  "root": <inner_node_id>,
  "tail": <leaf_node_id>,
  "size": <int>,
  "shift": <int>
}
```

| Field   | Description |
|---------|-------------|
| `root`  | Integer ID of the root **inner** node in `nodes`. |
| `tail`  | Integer ID of the tail **leaf** node in `nodes`. |
| `size`  | Total number of elements in the vector. |
| `shift` | Tree depth parameter (`B` for 1-level, `2*B` for 2-level, etc.). |

## Invariants

1. Every ID referenced by a vector's `root`/`tail` or an inner node's
   `children` **must** exist in `nodes`.
2. A vector's `root` must point to an inner node; its `tail` must point to a
   leaf node.
3. **Content-based deduplication**: if two subtrees are structurally identical
   (same node type, same data or recursively identical children), they **must**
   share a single `nodes` entry.  This applies transitively — inner nodes whose
   children all resolve to the same pool IDs must themselves be merged.
4. The pool must be **minimal**: no two entries in `nodes` have identical
   structural content.
