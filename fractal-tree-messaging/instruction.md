A B+ tree implementation exists at `/app/hitchhiker/core.py`. Each `IndexNode` carries an unused `op_buf` field designed for operation buffering. A conceptual overview of the hitchhiker tree pattern is at `/app/OVERVIEW.md`. The `InsertOp` and `DeleteOp` classes in the messaging module skeleton define the operation types.

Build a write-optimized key-value store on top of this B+ tree by implementing `/app/hitchhiker/messaging.py`. The module must expose the following functions:

## Messaging API

- `insert(tree, key, value)` — Buffer an insert. Returns a new tree root (the tree is persistent/immutable).
- `delete(tree, key)` — Buffer a delete. Returns a new tree root. Deleting a nonexistent key is a no-op.
- `lookup(tree, key, default=None)` — Look up a key, accounting for all buffered operations along the root-to-leaf path. Returns the value if found, otherwise returns `default`.
- `forward_iterator(tree, start_key)` — Yield `(key, value)` tuples in ascending key order for all keys `>= start_key`, reflecting all buffered operations. An empty tree yields nothing.

All operations must be correct for any `Config(index_b, data_b, op_buf_size)`, including edge cases like `op_buf_size=1` (immediate overflow on every buffered write).

## Correctness Requirements

- The store must behave identically to a Python `dict` for any interleaved sequence of inserts, deletes, and lookups (up to thousands of operations). Overwriting the same key multiple times must always yield the latest value.
- `forward_iterator` output must match the dict-equivalent sorted items.
- Standard B+ tree structural invariants must hold after every operation: no `DataNode` overflow, every `IndexNode` has >= 2 children, non-root index nodes do not underflow or overflow, and separator keys remain sorted.

## Redis Persistence

The module must also expose two functions for serializing and deserializing the complete tree state to Redis (including any buffered operations). A `redis-server` is installed and runs on `localhost:6379`.

- `save_tree(tree, redis_client)` — Serialize the tree to Redis. Each tree node must be stored as a **separate** Redis entry (a tree with 50 items must produce at least 5 Redis keys). Returns a non-empty string identifying the root key.
- `load_tree(root_key, redis_client)` — Deserialize a tree from its root key. The returned tree must support all messaging operations (`insert`, `delete`, `lookup`, `forward_iterator`).

Persistence requirements:
- Trees with pending operations in buffers must roundtrip correctly (buffered ops are preserved across serialization).
- Multiple save/load/modify/save cycles must maintain correctness.
- Data written by one Python process must be readable by another process (cross-process durability on the same Redis instance, db=1).