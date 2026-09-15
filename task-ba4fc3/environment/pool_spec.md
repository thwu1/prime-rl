# Radix Balanced Tree Pool Format Specification

## Overview

This document specifies the JSON pool format for serializing collections of
persistent (immutable) vectors that share internal tree nodes. The format
captures a set of named vectors as a single pool of deduplicated nodes.

## Persistent Vector Structure

A persistent vector is a tree-based data structure parameterized by:

- **B**: Branching bits for inner nodes. Each inner node has at most **M = 2^B** children.
- **BL**: Branching bits for leaf nodes. Each leaf node holds at most **ML = 2^BL** elements.

A vector consists of:
- A **root** inner node (or `null` for vectors whose elements all fit in a single leaf)
- A **tail** leaf node holding the rightmost elements that have not been
  incorporated into the tree

Inner nodes form the upper levels of the tree and fan out to children (which
may be other inner nodes or, at the lowest level, leaf nodes). Leaf nodes at
the bottom of the tree hold the actual data elements. Elements are ordered
left-to-right across the tree followed by the tail.

When the tail is full (ML elements) and a new element is appended, the full
tail is pushed into the tree and a fresh single-element tail is created.
The tree grows in depth when all existing levels are at capacity.

When a vector is modified (push_back, set), the resulting version shares all
unchanged subtrees with the original — only nodes along the modified path are
newly allocated. This is how multiple vectors in a pool share nodes.

## Pool JSON Format

```json
{
  "named_vectors": {
    "<name>": <vector_index>,
    ...
  },
  "pool": {
    "B": <int>,
    "BL": <int>,
    "leaves": [
      [<node_id>, [<element>, ...]],
      ...
    ],
    "inners": [
      [<node_id>, {"children": [<child_node_id>, ...], "relaxed": false}],
      ...
    ],
    "vectors": [
      {"root": <inner_node_id_or_null>, "tail": <leaf_node_id>},
      ...
    ]
  }
}
```

### Fields

- **named_vectors**: Maps user-defined names to indices in the `vectors` array.
  Multiple names may map to the same index (aliases / copies).
- **pool.B**, **pool.BL**: Branching parameters (positive integers).
- **pool.leaves**: Array of `[id, elements]` pairs. `id` is a non-negative
  integer. `elements` is a list of 1 to ML values.
- **pool.inners**: Array of `[id, descriptor]` pairs. `descriptor` has:
  - `children`: list of 1 to M child node IDs
  - `relaxed`: boolean (always `false` for standard RBTs)
- **pool.vectors**: Array of vector descriptors with `root` (inner node ID or
  `null`) and `tail` (leaf node ID).

### Constraints

- Node IDs are **globally unique** across both leaves and inners (no ID appears
  in both tables).
- `root` is `null` for vectors whose elements fit entirely in the tail (size <= ML).
- `root`, when present, must reference an inner node.
- `tail` must reference a leaf node.
- When vectors share subtrees, shared nodes appear **once** in the pool.
  Identity-based deduplication during serialization ensures this.
- No cycles in the node graph.

## CLI Interface

The tool at `/app/rbt_pool.py` must support:

### build

```
python3 /app/rbt_pool.py build <operations.json> -o <output.json>
```

Operations JSON:
```json
{
  "B": <int>, "BL": <int>,
  "operations": [
    {"op": "create", "name": "<name>", "elements": [...]},
    {"op": "push_back", "name": "<name>", "source": "<src_name>", "value": <val>},
    {"op": "set", "name": "<name>", "source": "<src_name>", "index": <idx>, "value": <val>},
    {"op": "copy", "name": "<name>", "source": "<src_name>"}
  ]
}
```

Vectors created from the same source must share unchanged tree nodes.

### reconstruct

```
python3 /app/rbt_pool.py reconstruct <pool.json>
```

Outputs JSON mapping each named vector to its element list.

### transform

```
python3 /app/rbt_pool.py transform <pool.json> <spec.json> -o <output.json>
```

Applies an element-wise transformation to all leaf elements while preserving
tree structure (inner nodes and vector descriptors unchanged). Supported
transform specs:
- `{"type": "multiply", "factor": <number>}`
- `{"type": "add", "value": <number>}`
- `{"type": "uppercase"}`
- `{"type": "negate"}`

### validate

```
python3 /app/rbt_pool.py validate <pool.json>
```

Prints `VALID` (exit 0) or `INVALID` with error details (exit 1). Checks:
unique IDs, no leaf/inner ID overlap, no dangling references, no cycles,
leaf size <= ML, inner child count <= M, valid root/tail references.

### analyze

```
python3 /app/rbt_pool.py analyze <pool.json>
```

Outputs JSON with sharing statistics:
- `total_nodes`, `leaf_nodes`, `inner_nodes`
- `shared_nodes`: count of nodes referenced by more than one pool vector
- `shared_node_ids`: sorted list of shared node IDs
- `elements_per_vector`: map of name to element count
- `naive_total_elements`: sum of all named vectors' element counts
- `actual_stored_elements`: sum of leaf element counts in the pool
- `sharing_ratio`: `1 - actual / naive` (0.0 if naive is 0)

### visualize

```
python3 /app/rbt_pool.py visualize <pool.json> -o <output.svg>
```

Generates a GraphViz DOT directed graph of the pool's node structure and renders
it to SVG by piping through `dot -Tsvg`.

Graph elements:
- **Leaf nodes**: record-shaped vertices labeled `L{id}|elem1,elem2,...`
  with `style=filled`.
  Fill color: `#90ee90` (unique) or `#ffd700` (shared — referenced by
  more than one vector's reachable node set).
- **Inner nodes**: record-shaped vertices labeled `I{id}` with `style=filled`.
  Fill color: `#add8e6` (unique) or `#ffd700` (shared).
- **Vector descriptors**: ellipse-shaped vertices labeled `V{idx}: name1,name2`
  with `style=filled fillcolor="#ffc0cb"`.
- **Edges**: directed edges from each inner node to its children, and from
  each vector descriptor to its root (labeled `root`) and tail (labeled `tail`).

A node is "shared" if it is reachable from the root or tail of more than one
entry in the `vectors` array.

### store

```
python3 /app/rbt_pool.py store <pool.json> -o <database.db>
```

Decomposes the pool into a normalized SQLite database with the following tables:

```sql
CREATE TABLE metadata (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
-- Stores "B" and "BL" as key-value pairs.

CREATE TABLE leaf_nodes (
    node_id  INTEGER PRIMARY KEY,
    elements TEXT NOT NULL  -- JSON-encoded array of element values
);

CREATE TABLE inner_nodes (
    node_id INTEGER PRIMARY KEY,
    relaxed INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE inner_children (
    inner_id  INTEGER NOT NULL,
    position  INTEGER NOT NULL,
    child_id  INTEGER NOT NULL,
    PRIMARY KEY (inner_id, position),
    FOREIGN KEY (inner_id) REFERENCES inner_nodes(node_id)
);

CREATE TABLE vectors (
    vector_index INTEGER PRIMARY KEY,
    root_id      INTEGER,      -- NULL when vector has no tree
    tail_id      INTEGER,
    FOREIGN KEY (tail_id) REFERENCES leaf_nodes(node_id)
);

CREATE TABLE named_vectors (
    name         TEXT PRIMARY KEY,
    vector_index INTEGER NOT NULL,
    FOREIGN KEY (vector_index) REFERENCES vectors(vector_index)
);
```

Foreign key constraints must be defined as shown above.

### load

```
python3 /app/rbt_pool.py load <database.db>
```

Reconstructs pool JSON from a SQLite database created by `store`. The output
(printed to stdout) must be a valid pool JSON that, when fed to `reconstruct`,
produces the same element lists as the original pool.
