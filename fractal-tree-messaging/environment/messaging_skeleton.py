"""
Hitchhiker tree messaging layer.

Build the write-optimization and persistence layer on top of the B+ tree core.
"""


from hitchhiker.core import (
    Config, DataNode, IndexNode, Split,
    new_tree, lookup_path, right_successor,
    insert as core_insert,
    delete as core_delete,
)


class InsertOp:
    """A buffered insert operation."""
    __slots__ = ("key", "value")

    def __init__(self, key, value):
        self.key = key
        self.value = value

    def apply_to_coll(self, d):
        result = dict(d)
        result[self.key] = self.value
        return result

    def apply_to_tree(self, tree):
        return core_insert(tree, self.key, self.value)


class DeleteOp:
    """A buffered delete operation."""
    __slots__ = ("key",)

    def __init__(self, key):
        self.key = key

    def apply_to_coll(self, d):
        result = dict(d)
        result.pop(self.key, None)
        return result

    def apply_to_tree(self, tree):
        return core_delete(tree, self.key)
