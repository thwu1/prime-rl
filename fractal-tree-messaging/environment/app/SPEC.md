# Hitchhiker Tree Messaging Layer Specification

## Overview

The hitchhiker tree is a write-optimized data structure that combines the
query performance of a B+ tree with the write performance of an append-only
log.  It achieves this by adding an **operation buffer** (`op_buf`) to each
index node.  This buffer amortizes writes: most inserts touch only the root
node's buffer instead of traversing to a leaf.

The core B+ tree implementation is provided in `hitchhiker/core.py`.  Your
task is to implement the messaging layer in `hitchhiker/messaging.py`.

## Architecture

### B+ Tree Recap

The underlying B+ tree has two node types:

| Node       | Role     | `children` field              |
|------------|----------|-------------------------------|
| `DataNode` | Leaf     | `dict` of key &rarr; value    |
| `IndexNode`| Internal | `list` of child nodes         |

Each `IndexNode` also carries an `op_buf` field (a list).  Core B+ tree
operations (`core.insert`, `core.delete`) preserve `op_buf` contents but
otherwise ignore them.

### Messaging Layer

The messaging layer uses `op_buf` to buffer write operations (inserts and
deletes) in index nodes rather than immediately modifying leaves.

#### Write Path &mdash; `enqueue(tree, ops)`

1. If the tree root is a **DataNode**, operations cannot be buffered.  They
   must be applied directly to the tree structure using `core.insert` /
   `core.delete`.

2. If the root is an **IndexNode** and its buffer has room (existing +
   new &le; `cfg.op_buf_size`), append the new operations to the buffer
   and return.

3. If the buffer would **overflow**, all operations (existing buffer +
   new operations) must be distributed to children:
   - Combine and **sort by key** (stable sort).
   - For each child (left to right), collect operations whose key &le;
     that child's `last_key`.  The **last child** receives all remaining
     operations regardless of key.
   - **Recursively enqueue** the collected operations into each child
     that received any.
   - Clear the current node's buffer.

4. Recursive enqueue may cascade further.  When it reaches a DataNode,
   the operations are **deferred**: collected into a list and, after the
   entire recursive distribution completes, applied one-by-one to the
   tree from the root using `core.insert` / `core.delete`.

#### Read Path &mdash; `apply_ops_in_path(path)`

When looking up a key, the physical leaf may not reflect recent buffered
operations.  `apply_ops_in_path` fixes this:

1. Collect operations from `op_buf` of every index node along the path.
2. **Order matters**: operations from nodes **deeper** in the tree
   (closer to the leaf) were enqueued earlier.  Concatenate them first,
   then append operations from shallower nodes.  A stable sort by key
   preserves this chronological ordering within each key.
3. **Filter** to keep only operations relevant to the target leaf:
   - **Left boundary**: Walk from the leaf to the root.  At each level,
     if the current node is *not* the leftmost child, record its left
     sibling.  Compute `left_max` = max of all recorded siblings'
     `last_key` values.  *Exclude* operations with key &le; `left_max`.
   - **Right boundary**: If the leaf is the rightmost leaf at every
     level of the tree (`is_last`), include all remaining operations.
     Otherwise, *exclude* operations with key > the leaf's `last_key`.
4. Apply the filtered operations sequentially to the leaf's `children`
   dict, producing the materialized result.

#### Lookup

`lookup(tree, key)` = find the path via `lookup_path`, call
`apply_ops_in_path`, return `result.get(key, default)`.

#### Insert / Delete

`insert(tree, key, value)` = `enqueue(tree, [InsertOp(key, value)])`.
`delete(tree, key)` = `enqueue(tree, [DeleteOp(key)])`.

#### Forward Iterator

`forward_iterator(tree, start_key)` yields `(key, value)` pairs &ge;
`start_key` in sorted order:

1. `lookup_path(tree, start_key)` to find the starting leaf.
2. `apply_ops_in_path(path)` to materialize that leaf's data.
3. Yield entries &ge; `start_key` from the materialized dict (sorted).
4. `right_successor(path)` to advance to the next leaf.
5. Repeat from step 2 (yield *all* entries from subsequent leaves).
6. Stop when `right_successor` returns `None`.

## Provided Utilities

The following are available from `hitchhiker.core`:

| Function / Class   | Purpose                                      |
|--------------------|----------------------------------------------|
| `Config`           | Tree configuration (index_b, data_b, op_buf_size) |
| `DataNode`         | Leaf node                                    |
| `IndexNode`        | Internal node (with `op_buf`)                |
| `new_tree(cfg)`    | Create an empty tree                         |
| `lookup_path(tree, key)` | Path from root to leaf               |
| `right_successor(path)`  | Path to the next leaf (or `None`)     |
| `insert(tree, k, v)` (as `core_insert`) | Core B+ insert        |
| `delete(tree, k)`    (as `core_delete`) | Core B+ delete        |

## Invariants

After any messaging operation:

- No index node's `op_buf` should exceed `cfg.op_buf_size` entries
  (buffers are cleared during overflow distribution).
- The underlying B+ tree structure remains valid.
- `lookup(tree, k)` must return the same value that a plain Python
  `dict` would after the same sequence of inserts and deletes.
