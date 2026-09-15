"""
B+ tree core implementation.

Provides the fundamental B+ tree data structure with configurable branching
factors. Supports insert, delete, lookup, and forward iteration.

Node types:
  - DataNode: Leaf node storing key-value pairs in a dict.
  - IndexNode: Internal node storing child pointers in a list,
               plus an op_buf list used by the messaging layer.

The op_buf on IndexNode is ignored by all core operations. It is used
exclusively by the messaging layer (messaging.py).
"""


import bisect


class Config:
    """Tree configuration.

    Attributes:
        index_b: Branching factor for index nodes.
                 Index nodes hold between index_b and 2*index_b - 1 children.
        data_b:  Branching factor for data (leaf) nodes.
                 Data nodes hold between data_b and 2*data_b - 1 entries.
        op_buf_size: Maximum operations in an index node's buffer.
    """

    def __init__(self, index_b, data_b, op_buf_size):
        self.index_b = index_b
        self.data_b = data_b
        self.op_buf_size = op_buf_size

    def __repr__(self):
        return (f"Config(index_b={self.index_b}, data_b={self.data_b}, "
                f"op_buf_size={self.op_buf_size})")


class Split:
    """Result of splitting an overflowed node."""
    __slots__ = ("left", "right", "median")

    def __init__(self, left, right, median):
        self.left = left
        self.right = right
        self.median = median


class DataNode:
    """Leaf node storing sorted key-value pairs.

    Attributes:
        cfg:      Tree configuration.
        children: Dict mapping keys to values.
    """

    def __init__(self, cfg, children=None):
        self.cfg = cfg
        self.children = dict(children) if children else {}

    def is_index(self):
        return False

    def is_data(self):
        return True

    def last_key(self):
        """Largest key in this node, or None if empty."""
        return max(self.children.keys()) if self.children else None

    def overflow(self):
        return len(self.children) >= 2 * self.cfg.data_b

    def underflow(self):
        return len(self.children) < self.cfg.data_b

    def split_node(self):
        """Split into two DataNodes around the median."""
        keys = sorted(self.children.keys())
        b = self.cfg.data_b
        left = {k: self.children[k] for k in keys[:b]}
        right = {k: self.children[k] for k in keys[b:]}
        return Split(DataNode(self.cfg, left),
                     DataNode(self.cfg, right),
                     keys[b - 1])

    def merge_node(self, other):
        """Merge with a sibling DataNode."""
        merged = dict(self.children)
        merged.update(other.children)
        return DataNode(self.cfg, merged)

    def __repr__(self):
        return f"DataNode({sorted(self.children.keys())})"


class IndexNode:
    """Internal node with child pointers and an operation buffer.

    Attributes:
        cfg:      Tree configuration.
        children: List of child nodes (DataNode or IndexNode).
        op_buf:   List of pending operations (used by messaging layer).
    """

    def __init__(self, cfg, children, op_buf=None):
        self.cfg = cfg
        self.children = list(children)
        self.op_buf = list(op_buf) if op_buf else []

    def is_index(self):
        return True

    def is_data(self):
        return False

    def last_key(self):
        """Largest key in this subtree."""
        return self.children[-1].last_key() if self.children else None

    def separator_keys(self):
        """Separator keys between children.

        separator_keys()[i] == last_key(children[i]) for i in 0..N-2.
        A lookup key K routes to children[j] where j is the smallest index
        such that K <= separator_keys()[j], or the last child if K exceeds
        all separators.
        """
        return [c.last_key() for c in self.children[:-1]]

    def overflow(self):
        return len(self.children) >= 2 * self.cfg.index_b

    def underflow(self):
        return len(self.children) < self.cfg.index_b

    def split_node(self):
        """Split into two IndexNodes, partitioning op_buf by the median."""
        b = self.cfg.index_b
        sep = self.separator_keys()
        median = sep[b - 1]
        sorted_ops = sorted(self.op_buf, key=lambda o: o.key)
        left_buf = [o for o in sorted_ops if o.key <= median]
        right_buf = [o for o in sorted_ops if o.key > median]
        return Split(
            IndexNode(self.cfg, self.children[:b], left_buf),
            IndexNode(self.cfg, self.children[b:], right_buf),
            median,
        )

    def merge_node(self, other):
        """Merge with a sibling IndexNode."""
        return IndexNode(
            self.cfg,
            self.children + other.children,
            self.op_buf + other.op_buf,
        )

    def lookup_child_index(self, key):
        """Index of the child whose key range contains *key*.

        Uses binary search over separator keys.
        """
        sep = self.separator_keys()
        idx = bisect.bisect_left(sep, key)
        return min(idx, len(self.children) - 1)

    def __repr__(self):
        return (f"IndexNode(sep={self.separator_keys()}, "
                f"buf={len(self.op_buf)})")


# ------------------------------------------------------------------
# Tree construction and path utilities
# ------------------------------------------------------------------

def new_tree(cfg):
    """Create a new empty tree."""
    return DataNode(cfg)


def lookup_path(tree, key):
    """Path from root to the leaf that would contain *key*.

    Returns a list  [node0, idx0, node1, idx1, ..., leaf]
    where  node_i.children[idx_i] == node_{i+1}.
    Length is always odd (starts and ends with a node).
    """
    path = [tree]
    cur = tree
    while cur.is_index():
        idx = cur.lookup_child_index(key)
        child = cur.children[idx]
        path.append(idx)
        path.append(child)
        cur = child
    return path


def right_successor(path):
    """Path to the next leaf to the right, or None.

    *path* must end with a DataNode (as returned by lookup_path).
    """
    path = list(path)
    path.pop()  # remove leaf
    while len(path) >= 2:
        idx = path[-1]
        parent = path[-2]
        if idx + 1 < len(parent.children):
            path[-1] = idx + 1
            cur = parent.children[idx + 1]
            path.append(cur)
            while cur.is_index():
                path.append(0)
                cur = cur.children[0]
                path.append(cur)
            return path
        path.pop()
        path.pop()
    return None


# ------------------------------------------------------------------
# Core B+ tree operations (no messaging / buffering)
# ------------------------------------------------------------------

def lookup_key(tree, key, default=None):
    """Look up *key* in the B+ tree (ignoring op_buf)."""
    path = lookup_path(tree, key)
    leaf = path[-1]
    return leaf.children.get(key, default)


def insert(tree, key, value):
    """Insert key-value into the tree.  Returns a new root.

    Pure B+ tree insert: walks to the leaf, inserts, and handles
    splits on the way back up.  Preserves existing op_buf contents.
    """
    cfg = tree.cfg
    path = lookup_path(tree, key)
    leaf = path[-1]

    new_children = dict(leaf.children)
    new_children[key] = value
    node = DataNode(cfg, new_children)

    i = len(path) - 2  # walk back up (indices are at even positions)
    while i >= 1:
        idx = path[i]
        parent = path[i - 1]
        if node.overflow():
            split = node.split_node()
            new_ch = (list(parent.children[:idx])
                      + [split.left, split.right]
                      + list(parent.children[idx + 1:]))
            node = IndexNode(cfg, new_ch, list(parent.op_buf))
        else:
            new_ch = list(parent.children)
            new_ch[idx] = node
            node = IndexNode(cfg, new_ch, list(parent.op_buf))
        i -= 2

    if node.overflow():
        split = node.split_node()
        return IndexNode(cfg, [split.left, split.right])
    return node


def delete(tree, key):
    """Delete *key* from the tree.  Returns a new root.

    Pure B+ tree delete: walks to the leaf, removes the key, and
    handles underflows (merge / re-split) on the way back up.
    Preserves existing op_buf contents.
    """
    cfg = tree.cfg
    path = lookup_path(tree, key)
    leaf = path[-1]

    if key not in leaf.children:
        return tree  # nothing to delete

    new_children = dict(leaf.children)
    del new_children[key]
    node = DataNode(cfg, new_children)

    i = len(path) - 2
    while i >= 1:
        idx = path[i]
        parent = path[i - 1]

        if node.underflow() and len(parent.children) > 1:
            # pick best sibling to merge with
            if idx == len(parent.children) - 1:
                sib_idx = idx - 1
            elif idx == 0:
                sib_idx = 1
            else:
                lc = _child_count(parent.children[idx - 1])
                rc = _child_count(parent.children[idx + 1])
                sib_idx = (idx - 1) if lc >= rc else (idx + 1)

            sib = parent.children[sib_idx]
            merged = (sib.merge_node(node) if sib_idx < idx
                      else node.merge_node(sib))

            lo, hi = min(idx, sib_idx), max(idx, sib_idx)
            if merged.overflow():
                split = merged.split_node()
                new_ch = (list(parent.children[:lo])
                          + [split.left, split.right]
                          + list(parent.children[hi + 1:]))
            else:
                new_ch = (list(parent.children[:lo])
                          + [merged]
                          + list(parent.children[hi + 1:]))
            node = IndexNode(cfg, new_ch, list(parent.op_buf))
        else:
            new_ch = list(parent.children)
            new_ch[idx] = node
            node = IndexNode(cfg, new_ch, list(parent.op_buf))
        i -= 2

    if node.is_index() and len(node.children) == 1:
        return node.children[0]
    return node


def forward_iterator(tree, start_key):
    """Iterate (key, value) pairs >= *start_key* (core B+ tree only)."""
    path = lookup_path(tree, start_key)
    is_first = True
    while path:
        leaf = path[-1]
        for k, v in sorted(leaf.children.items()):
            if is_first and k < start_key:
                continue
            yield (k, v)
        is_first = False
        path = right_successor(path)


def _child_count(node):
    if node.is_data():
        return len(node.children)
    return len(node.children)
