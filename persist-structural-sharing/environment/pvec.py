"""
Persistent Vector -- Radix Balanced Tree with structural sharing.

Branching: B=2, M=2^B=4.  Each inner node has up to 4 children.
Leaf nodes hold up to M=4 values.  A "tail" leaf holds the rightmost
values not yet merged into the tree, enabling amortised O(1) append.

All mutation operations (push_back, set) return a **new** vector.
The old version remains valid.  Unmodified subtrees are shared
between old and new versions (structural sharing).

Tree layout
-----------
- ``shift`` encodes depth: shift=B  => 1 level of inner nodes above leaves,
  shift=2B => 2 levels, etc.
- At shift=B the inner node's children are LeafNodes.
  At shift>B the children are other InnerNodes.
- The *tail* is a separate LeafNode that buffers the rightmost elements.
  It is only flushed into the tree when it reaches capacity M.

"""

B = 2
M = 1 << B    # 4
MASK = M - 1  # 3


class LeafNode:
    """Leaf node storing up to M values."""
    __slots__ = ('data',)

    def __init__(self, data=()):
        self.data = tuple(data)

    def __repr__(self):
        return f"Leaf({list(self.data)})"


class InnerNode:
    """Inner node storing up to M children (InnerNode or LeafNode)."""
    __slots__ = ('children',)

    def __init__(self, children=()):
        self.children = tuple(children)

    def __repr__(self):
        return f"Inner(n={len(self.children)})"


def _new_path(level, node):
    """Create a single-child spine of inner nodes from *level* down to *node*."""
    if level == 0:
        return node
    return InnerNode((_new_path(level - B, node),))


class PersistentVector:
    """Immutable vector backed by a radix-balanced tree with structural sharing."""

    def __init__(self, size=0, shift=B, root=None, tail=None):
        self.size = size
        self.shift = shift
        self.root = root if root is not None else InnerNode()
        self.tail = tail if tail is not None else LeafNode()

    # ---- construction helpers ------------------------------------------------

    @classmethod
    def of(cls, *args):
        """Create a vector from positional arguments."""
        v = cls()
        for a in args:
            v = v.push_back(a)
        return v

    # ---- read ----------------------------------------------------------------

    def __len__(self):
        return self.size

    def _tail_offset(self):
        if self.size < M:
            return 0
        return ((self.size - 1) >> B) << B

    def __getitem__(self, index):
        if isinstance(index, slice):
            return [self[i] for i in range(*index.indices(self.size))]
        if index < 0:
            index += self.size
        if not 0 <= index < self.size:
            raise IndexError(index)
        if index >= self._tail_offset():
            return self.tail.data[index - self._tail_offset()]
        node = self.root
        level = self.shift
        while level > 0:
            node = node.children[(index >> level) & MASK]
            level -= B
        return node.data[index & MASK]

    # ---- write (returns a new vector) ----------------------------------------

    def push_back(self, value):
        """Return a new vector with *value* appended."""
        # Room in the tail?
        if self.size - self._tail_offset() < M:
            new_tail = LeafNode(self.tail.data + (value,))
            return PersistentVector(self.size + 1, self.shift,
                                   self.root, new_tail)

        # Tail is full -- flush it into the tree.
        old_tail = self.tail
        new_tail = LeafNode((value,))

        # Does the tree need to grow a new level?
        if (self.size >> B) > (1 << self.shift):
            new_root = InnerNode((self.root,
                                  _new_path(self.shift, old_tail)))
            return PersistentVector(self.size + 1, self.shift + B,
                                   new_root, new_tail)

        new_root = self._push_tail(self.shift, self.root, old_tail)
        return PersistentVector(self.size + 1, self.shift,
                                new_root, new_tail)

    def _push_tail(self, level, parent, tail_node):
        """Insert *tail_node* into *parent*, path-copying along the way."""
        sub_idx = ((self.size - 1) >> level) & MASK
        new_children = list(parent.children)

        if level == B:
            # Bottom inner level: just append the leaf.
            new_children.append(tail_node)
        elif sub_idx < len(parent.children):
            # Recurse into an existing subtree.
            new_children[sub_idx] = self._push_tail(
                level - B, parent.children[sub_idx], tail_node)
        else:
            # Create a fresh spine for the new leaf.
            new_children.append(_new_path(level - B, tail_node))

        return InnerNode(tuple(new_children))

    def set(self, index, value):
        """Return a new vector with the element at *index* replaced."""
        if index < 0:
            index += self.size
        if not 0 <= index < self.size:
            raise IndexError(index)

        if index >= self._tail_offset():
            pos = index - self._tail_offset()
            d = list(self.tail.data)
            d[pos] = value
            return PersistentVector(self.size, self.shift,
                                   self.root, LeafNode(tuple(d)))

        new_root = self._do_set(self.shift, self.root, index, value)
        return PersistentVector(self.size, self.shift,
                                new_root, self.tail)

    def _do_set(self, level, node, index, value):
        """Path-copy replacement of a single element."""
        if level == 0:
            d = list(node.data)
            d[index & MASK] = value
            return LeafNode(tuple(d))
        ci = (index >> level) & MASK
        ch = list(node.children)
        ch[ci] = self._do_set(level - B, node.children[ci], index, value)
        return InnerNode(tuple(ch))

    # ---- comparison / display ------------------------------------------------

    def to_list(self):
        """Materialise to a plain Python list."""
        return [self[i] for i in range(self.size)]

    def __eq__(self, other):
        if not isinstance(other, PersistentVector):
            return NotImplemented
        return self.size == other.size and self.to_list() == other.to_list()

    def __repr__(self):
        items = self.to_list() if self.size <= 20 else self.to_list()[:10] + ['...']
        return f"PVec({items})"
