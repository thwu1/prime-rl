"""
Hitchhiker tree messaging layer.

This module implements the operation buffer overlay on top of the B+ tree
core provided in hitchhiker.core.  Your task is to implement the functions
below according to the specification in /app/SPEC.md.

The messaging layer buffers write operations (inserts and deletes) in the
op_buf of IndexNodes, dramatically improving write performance.  Reads
resolve buffered operations on-the-fly by collecting and applying them
along the lookup path.

You must implement:
  - enqueue(tree, ops)            : Buffer operations with overflow cascading
  - apply_ops_in_path(path)       : Resolve buffered ops for a lookup path
  - lookup(tree, key, default)    : Read a key with buffer resolution
  - insert(tree, key, value)      : Buffer an insert operation
  - delete(tree, key)             : Buffer a delete operation
  - forward_iterator(tree, start) : Iterate with buffer resolution
"""


from hitchhiker.core import (
    Config, DataNode, IndexNode, Split,
    new_tree, lookup_path, right_successor,
    insert as core_insert,
    delete as core_delete,
)


# ---- Operation types (provided) -------------------------------------------

class InsertOp:
    """Represents a buffered insert operation."""
    __slots__ = ("key", "value")

    def __init__(self, key, value):
        self.key = key
        self.value = value

    def apply_to_coll(self, d):
        """Apply this insert to a dict, returning a new dict."""
        result = dict(d)
        result[self.key] = self.value
        return result

    def apply_to_tree(self, tree):
        """Apply this insert directly to the tree via core insert."""
        return core_insert(tree, self.key, self.value)

    def __repr__(self):
        return f"InsertOp({self.key!r}, {self.value!r})"


class DeleteOp:
    """Represents a buffered delete operation."""
    __slots__ = ("key",)

    def __init__(self, key):
        self.key = key

    def apply_to_coll(self, d):
        """Apply this delete to a dict, returning a new dict."""
        result = dict(d)
        result.pop(self.key, None)
        return result

    def apply_to_tree(self, tree):
        """Apply this delete directly to the tree via core delete."""
        return core_delete(tree, self.key)

    def __repr__(self):
        return f"DeleteOp({self.key!r})"


# ---- Functions to implement ------------------------------------------------

def enqueue(tree, ops):
    """Add operations to the tree's message buffers.

    This is the core write operation.  Operations are buffered in index
    nodes.  When a buffer overflows (exceeds cfg.op_buf_size), its
    contents are distributed to child nodes based on key ranges.  When
    operations reach a data (leaf) node they must be applied directly to
    the tree structure using core operations.

    Args:
        tree: Root node of the tree.
        ops:  List of InsertOp / DeleteOp operations.

    Returns:
        New tree root with operations applied / buffered.
    """
    raise NotImplementedError("Implement enqueue")


def apply_ops_in_path(path):
    """Materialize the data at a leaf by applying buffered operations.

    Given a lookup path from root to a leaf node, collects all buffered
    operations from index nodes along the path, filters them to only
    those relevant to the target leaf, and applies them to produce the
    correct key-value mapping.

    Filtering is critical: use the *left boundary* (max last_key of left
    siblings along the path) and the *right boundary* (last_key of the
    target leaf, unless it is the rightmost leaf) to include only
    operations that belong to this specific leaf.

    Operation application order matters: operations from deeper index
    nodes were enqueued earlier and must be applied before operations
    from nodes closer to the root.

    Args:
        path: [root, idx, node, idx, ..., leaf] as from lookup_path.

    Returns:
        Dict of key-value pairs representing the materialized leaf data.
    """
    raise NotImplementedError("Implement apply_ops_in_path")


def lookup(tree, key, default=None):
    """Look up a key in the hitchhiker tree.

    Uses lookup_path to find the relevant leaf, then apply_ops_in_path
    to resolve any buffered operations.

    Args:
        tree:    Root node.
        key:     Key to look up.
        default: Value to return if not found.

    Returns:
        Value for the key, or *default*.
    """
    raise NotImplementedError("Implement lookup")


def insert(tree, key, value):
    """Insert a key-value pair using the messaging layer.

    Creates an InsertOp and enqueues it.
    """
    raise NotImplementedError("Implement insert")


def delete(tree, key):
    """Delete a key using the messaging layer.

    Creates a DeleteOp and enqueues it.
    """
    raise NotImplementedError("Implement delete")


def forward_iterator(tree, start_key):
    """Iterate forward through the tree from *start_key*.

    Yields (key, value) pairs in sorted order, starting from the first
    key >= start_key.  Must correctly apply buffered operations for each
    leaf along the iteration path.

    Args:
        tree:      Root node.
        start_key: Starting key for iteration.

    Yields:
        (key, value) tuples in sorted key order.
    """
    raise NotImplementedError("Implement forward_iterator")
