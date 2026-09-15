
"""
B+ Tree implementation with op_buf fields on index nodes for hitchhiker tree extension.

The tree is functional/persistent — mutations return new tree roots.
IndexNode.op_buf is present but NOT used by this module. The hitchhiker
messaging layer (/app/hitchhiker.py) must implement the buffering logic.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Optional
import bisect


@dataclass
class Config:
    """Tree configuration.

    index_b: branching factor for index nodes. Index nodes hold between
             index_b and 2*index_b - 1 children.
    data_b:  capacity factor for data (leaf) nodes. Data nodes hold between
             data_b and 2*data_b - 1 key-value pairs.
    op_buf_size: maximum number of pending operations in each index node's buffer.
    """
    index_b: int
    data_b: int
    op_buf_size: int


def _compare(a, b) -> int:
    """Standard three-way comparison."""
    if a < b:
        return -1
    elif a > b:
        return 1
    return 0


@dataclass
class DataNode:
    """Leaf node of the B+ tree. Stores sorted key-value pairs in `children` (a dict)."""
    children: dict = field(default_factory=dict)
    cfg: Config = field(default=None)

    def is_index(self) -> bool:
        return False

    def last_key(self) -> Any:
        if not self.children:
            return None
        return max(self.children.keys())

    def overflow(self) -> bool:
        return len(self.children) >= 2 * self.cfg.data_b

    def underflow(self) -> bool:
        return len(self.children) < self.cfg.data_b

    def split(self) -> tuple["DataNode", "DataNode", Any]:
        """Split into two data nodes. Returns (left, right, median_key)."""
        sorted_items = sorted(self.children.items())
        mid = self.cfg.data_b
        left_items = dict(sorted_items[:mid])
        right_items = dict(sorted_items[mid:])
        median = sorted_items[mid - 1][0]
        return (
            DataNode(children=left_items, cfg=self.cfg),
            DataNode(children=right_items, cfg=self.cfg),
            median,
        )

    def merge_node(self, other: "DataNode") -> "DataNode":
        merged = dict(self.children)
        merged.update(other.children)
        return DataNode(children=merged, cfg=self.cfg)

    def lookup(self, key) -> int:
        """Return the index where key would be in the sorted keys list."""
        keys = sorted(self.children.keys())
        return bisect.bisect_left(keys, key)

    def __repr__(self):
        return f"DataNode(keys={sorted(self.children.keys())})"


@dataclass
class IndexNode:
    """Internal node of the B+ tree.

    children: list of child nodes (DataNode or IndexNode).
    op_buf: list of pending operations (used by the hitchhiker messaging layer).
    cfg: tree configuration.
    """
    children: list = field(default_factory=list)
    op_buf: list = field(default_factory=list)
    cfg: Config = field(default=None)

    def is_index(self) -> bool:
        return True

    def last_key(self) -> Any:
        if not self.children:
            return None
        return self.children[-1].last_key()

    def keys(self) -> list:
        """Return the separating keys (last key of each child except the last one)."""
        return [child.last_key() for child in self.children[:-1]]

    def overflow(self) -> bool:
        return len(self.children) >= 2 * self.cfg.index_b

    def underflow(self) -> bool:
        return len(self.children) < self.cfg.index_b

    def split(self) -> tuple["IndexNode", "IndexNode", Any]:
        """Split into two index nodes. Returns (left, right, median_key).
        Op_buf entries are partitioned by key to the appropriate side."""
        b = self.cfg.index_b
        sep_keys = self.keys()
        median = sep_keys[b - 1]

        left_children = self.children[:b]
        right_children = self.children[b:]

        left_buf = [op for op in self.op_buf if _compare(op.affects_key(), median) <= 0]
        right_buf = [op for op in self.op_buf if _compare(op.affects_key(), median) > 0]

        return (
            IndexNode(children=left_children, op_buf=left_buf, cfg=self.cfg),
            IndexNode(children=right_children, op_buf=right_buf, cfg=self.cfg),
            median,
        )

    def merge_node(self, other: "IndexNode") -> "IndexNode":
        return IndexNode(
            children=self.children + other.children,
            op_buf=self.op_buf + other.op_buf,
            cfg=self.cfg,
        )

    def lookup(self, key) -> int:
        """Return the index of the child that should contain the given key.

        Uses bisect_left so that a key equal to a separating key (which is
        the last_key of the left child) is directed to that left child.
        """
        sep = self.keys()
        idx = bisect.bisect_left(sep, key)
        if idx < len(sep) and sep[idx] == key:
            return idx
        return min(idx, len(self.children) - 1)

    def __repr__(self):
        return f"IndexNode(keys={self.keys()}, buf_len={len(self.op_buf)})"


def new_tree(cfg: Config) -> DataNode:
    """Create a new empty B+ tree."""
    return DataNode(children={}, cfg=cfg)


def lookup_path(tree, key) -> list:
    """Return the root-to-leaf path as [node, child_index, node, child_index, ..., leaf].

    The path alternates between nodes and the child index taken at each level.
    """
    path = [tree]
    cur = tree
    while isinstance(cur, IndexNode):
        idx = cur.lookup(key)
        child = cur.children[idx]
        path.append(idx)
        path.append(child)
        cur = child
    return path


def lookup_key(tree, key, default=None):
    """Direct B+ tree lookup (ignores op_buf — for base tree only)."""
    path = lookup_path(tree, key)
    leaf = path[-1]
    return leaf.children.get(key, default)


def _insert_into_tree(tree, key, value):
    """Insert a key-value pair directly into the B+ tree (no buffering)."""
    path = lookup_path(tree, key)
    leaf = path[-1]
    new_children = dict(leaf.children)
    new_children[key] = value
    node = DataNode(children=new_children, cfg=leaf.cfg)

    # Walk back up the path
    i = len(path) - 2  # index of the child_index
    while i >= 1:
        child_idx = path[i]
        parent = path[i - 1]
        if node.overflow() if not isinstance(node, IndexNode) else node.overflow():
            left, right, median = node.split() if not isinstance(node, IndexNode) else node.split()
            new_ch = list(parent.children)
            new_ch[child_idx:child_idx + 1] = [left, right]
            node = IndexNode(children=new_ch, op_buf=list(parent.op_buf), cfg=parent.cfg)
        else:
            new_ch = list(parent.children)
            new_ch[child_idx] = node
            node = IndexNode(children=new_ch, op_buf=list(parent.op_buf), cfg=parent.cfg)
        i -= 2

    # Handle root overflow
    if node.overflow() if not isinstance(node, IndexNode) else node.overflow():
        left, right, median = node.split()
        node = IndexNode(children=[left, right], op_buf=[], cfg=tree.cfg if isinstance(tree, IndexNode) else tree.cfg)

    return node


def _delete_from_tree(tree, key):
    """Delete a key from the B+ tree directly (no buffering)."""
    path = lookup_path(tree, key)
    leaf = path[-1]
    new_children = dict(leaf.children)
    new_children.pop(key, None)
    node = DataNode(children=new_children, cfg=leaf.cfg)

    i = len(path) - 2
    while i >= 1:
        child_idx = path[i]
        parent = path[i - 1]
        if node.underflow() and len(parent.children) > 1:
            # Find a sibling to merge with
            if child_idx == len(parent.children) - 1:
                sib_idx = child_idx - 1
            elif child_idx == 0:
                sib_idx = 1
            else:
                left_sib = parent.children[child_idx - 1]
                right_sib = parent.children[child_idx + 1]
                lcount = len(left_sib.children)
                rcount = len(right_sib.children)
                sib_idx = child_idx - 1 if lcount >= rcount else child_idx + 1

            node_first = sib_idx > child_idx
            sibling = parent.children[sib_idx]
            if node_first:
                merged = node.merge_node(sibling)
            else:
                merged = sibling.merge_node(node)

            lo = min(child_idx, sib_idx)
            hi = max(child_idx, sib_idx)
            old_left = parent.children[:lo]
            old_right = parent.children[hi + 1:]

            if merged.overflow():
                left, right, median = merged.split()
                new_ch = list(old_left) + [left, right] + list(old_right)
            else:
                new_ch = list(old_left) + [merged] + list(old_right)

            node = IndexNode(children=new_ch, op_buf=list(parent.op_buf), cfg=parent.cfg)
        else:
            new_ch = list(parent.children)
            new_ch[child_idx] = node
            node = IndexNode(children=new_ch, op_buf=list(parent.op_buf), cfg=parent.cfg)
        i -= 2

    # Root with single index child collapses
    if isinstance(node, IndexNode) and len(node.children) == 1:
        node = node.children[0]

    return node


def right_successor_path(path) -> Optional[list]:
    """Given a root-to-leaf path, return the path to the next leaf to the right.

    Returns None if the current leaf is the rightmost.
    Path format: [node, idx, node, idx, ..., leaf]
    """
    # Walk back up to find a parent where we can go right
    p = list(path)
    while len(p) >= 3:
        leaf_or_node = p[-1]
        idx = p[-2]
        parent = p[-3]
        if idx + 1 < len(parent.children):
            # Can go right
            next_idx = idx + 1
            base = p[:-2]
            base.append(next_idx)
            child = parent.children[next_idx]
            base.append(child)
            # Now descend to leftmost leaf
            cur = child
            while isinstance(cur, IndexNode):
                base.append(0)
                cur = cur.children[0]
                base.append(cur)
            return base
        else:
            p = p[:-2]  # Go up one level
    return None
