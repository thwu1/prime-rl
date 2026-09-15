
"""
Key-value store module. Implement all functions below.
Do not modify bplustree.py or ops.py.
"""

from bplustree import (
    Config, DataNode, IndexNode, new_tree, lookup_path,
    right_successor_path, _insert_into_tree, _delete_from_tree, _compare,
)
from ops import InsertOp, DeleteOp


def enqueue(tree, ops: list):
    """Apply a batch of operations to the tree. Returns the new tree root."""
    raise NotImplementedError("You must implement enqueue")


def lookup(tree, key, default=None):
    """Look up a key in the tree. Returns the value or default if absent."""
    raise NotImplementedError("You must implement lookup")


def insert(tree, key, value):
    """Insert a key-value pair. Returns the new tree root."""
    raise NotImplementedError("You must implement insert")


def delete(tree, key):
    """Delete a key. Returns the new tree root."""
    raise NotImplementedError("You must implement delete")


def forward_iter(tree, start_key):
    """Return a list of (key, value) pairs with key >= start_key, in sorted order."""
    raise NotImplementedError("You must implement forward_iter")


def save_tree(tree, name, host="localhost", port=6379):
    """Persist the tree to Redis under the given name."""
    raise NotImplementedError("You must implement save_tree")


def load_tree(name, host="localhost", port=6379):
    """Load a previously saved tree from Redis. Raise if not found."""
    raise NotImplementedError("You must implement load_tree")
