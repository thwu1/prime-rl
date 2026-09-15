# Hitchhiker Tree

A hitchhiker tree (fractal tree index) is a write-optimized B+ tree variant.

## Concept

Standard B+ trees propagate every write from root to leaf. A hitchhiker tree amortizes writes by buffering operations in internal nodes. Each `IndexNode` carries an `op_buf` — a list of pending operations limited by `Config.op_buf_size`.

When a buffer is full, its contents must cascade downward. When reading, any operations pending above the target leaf must be taken into account.

## Requirements

- The store must behave identically to a Python `dict` for any sequence of inserts, deletes, and lookups.
- No buffer may exceed `Config.op_buf_size` entries after any operation.
- The underlying B+ tree structural invariants must be maintained.

## Provided Code

The B+ tree core in `hitchhiker/core.py` provides node types, tree construction, path utilities, and direct (unbuffered) insert/delete. Read the source for the full API.

The `InsertOp` and `DeleteOp` classes in `hitchhiker/messaging.py` represent buffered operations.
