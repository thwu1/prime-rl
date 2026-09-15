A functional B+ tree implementation exists at `/app/bplustree.py` with an operations module at `/app/ops.py`. A Redis server is available at `localhost:6379`.

The B+ tree's `IndexNode` has an `op_buf` field and the tree configuration includes an `op_buf_size` parameter. The stub at `/app/hitchhiker.py` defines seven functions you must implement to create a write-optimized key-value store built on top of this B+ tree.

## Required Functions

- `insert(tree, key, value) → tree`
- `delete(tree, key) → tree`
- `lookup(tree, key, default=None) → value`
- `forward_iter(tree, start_key) → list[(key, value)]`
- `enqueue(tree, ops) → tree` — batch-apply `InsertOp`/`DeleteOp` objects from `/app/ops.py`; later operations in the list take precedence for same-key conflicts
- `save_tree(tree, name, host="localhost", port=6379)` — persist to Redis
- `load_tree(name, host="localhost", port=6379) → tree` — restore from Redis; raise an exception if no tree exists under that name

## Requirements

**Correctness**: For any sequence of `insert`/`delete` calls, `lookup` and `forward_iter` must produce results identical to a plain Python `dict` receiving the same operations.

**Write optimization**: The store must use `IndexNode.op_buf` to defer work during writes. The `op_buf_size` configuration parameter controls the maximum buffer capacity per node. Trees configured with larger `op_buf_size` must retain more pending operations in their buffers than trees with smaller values — a tree with `op_buf_size=100` must have nonzero buffered ops after 50 inserts. `insert` and `delete` must route through `enqueue`.

**Balance**: The underlying B+ tree must remain balanced after every mutation.

**Persistence**: `save_tree`/`load_tree` must round-trip the complete tree state including any deferred operations. Loaded trees must support further mutations. Multiple named trees must coexist independently.

The test suite at `/tests/test_state.py` is the definitive specification.