
"""
Persistent Vector implementation using a Radix Balanced Tree.

Uses structural sharing: modifications create new paths in the tree
while sharing unchanged subtrees with previous versions.

Branching factor: 2 (BITS=1) for clarity and testability.

Tree structure:
- Inner nodes have a `children` list of child Nodes
- Leaf nodes have a `values` list of stored elements
- A "tail" buffer holds the rightmost elements not yet pushed into the tree
- `shift` = depth * BITS, determines tree depth
- `size` = total number of elements

Addressing: element at index i is found by extracting BITS-wide chunks
from i at each tree level (from shift down to 0).

Structural sharing: push_back() and set() create new nodes only along
the modified path; all other subtrees are shared with the original vector.
"""

BITS = 1
WIDTH = 1 << BITS  # 2
MASK = WIDTH - 1    # 1


class Node:
    """A node in the radix balanced tree."""

    __slots__ = ('children', 'values')

    def __init__(self, children=None, values=None):
        self.children = children
        self.values = values

    @property
    def is_leaf(self):
        return self.values is not None

    def __repr__(self):
        if self.is_leaf:
            return f"Leaf({self.values})"
        return f"Inner(children={len(self.children)})"


def _new_path(level, node):
    """Create a spine of single-child inner nodes from level down to node."""
    if level == 0:
        return node
    return Node(children=[_new_path(level - BITS, node)])


class PersistentVector:
    """An immutable vector with efficient structural sharing.

    Modifications return new vectors sharing unchanged subtrees with the original.

    Attributes:
        size:  Total number of elements.
        shift: Tree depth indicator (depth * BITS).
        root:  Root Node of the tree, or None if all elements are in the tail.
        tail:  List of rightmost elements not yet pushed into the tree.
    """

    def __init__(self, size=0, shift=0, root=None, tail=None):
        self.size = size
        self.shift = shift
        self.root = root
        self.tail = tail if tail is not None else []

    @staticmethod
    def from_list(items):
        """Build a PersistentVector from an iterable."""
        v = PersistentVector()
        for item in items:
            v = v.push_back(item)
        return v

    def _tail_offset(self):
        """Index of the first element stored in the tail buffer."""
        if self.size < WIDTH:
            return 0
        return ((self.size - 1) >> BITS) << BITS

    def get(self, i):
        """Return element at index i."""
        if i < 0 or i >= self.size:
            raise IndexError(i)
        if i >= self._tail_offset():
            return self.tail[i & MASK]
        node = self.root
        for level in range(self.shift, 0, -BITS):
            node = node.children[(i >> level) & MASK]
        return node.values[i & MASK]

    def set(self, i, val):
        """Return a new vector with element at index i replaced by val."""
        if i < 0 or i >= self.size:
            raise IndexError(i)
        if i >= self._tail_offset():
            new_tail = list(self.tail)
            new_tail[i & MASK] = val
            return PersistentVector(self.size, self.shift, self.root, new_tail)
        new_root = self._do_set(self.shift, self.root, i, val)
        return PersistentVector(self.size, self.shift, new_root, list(self.tail))

    def _do_set(self, level, node, i, val):
        if level == 0:
            new_vals = list(node.values)
            new_vals[i & MASK] = val
            return Node(values=new_vals)
        idx = (i >> level) & MASK
        new_children = list(node.children)
        new_children[idx] = self._do_set(level - BITS, node.children[idx], i, val)
        return Node(children=new_children)

    def push_back(self, val):
        """Return a new vector with val appended."""
        if self.size - self._tail_offset() < WIDTH:
            new_tail = list(self.tail) + [val]
            return PersistentVector(self.size + 1, self.shift, self.root, new_tail)

        tail_node = Node(values=list(self.tail))

        if self.root is None:
            return PersistentVector(self.size + 1, 0, tail_node, [val])

        if (self.size >> BITS) > (1 << self.shift):
            new_root = Node(children=[self.root, _new_path(self.shift, tail_node)])
            return PersistentVector(self.size + 1, self.shift + BITS, new_root, [val])

        new_root = self._do_push_tail(self.shift, self.root, tail_node)
        return PersistentVector(self.size + 1, self.shift, new_root, [val])

    def _do_push_tail(self, level, parent, tail_node):
        subidx = ((self.size - 1) >> level) & MASK
        if level == BITS:
            new_children = list(parent.children) + [tail_node]
            return Node(children=new_children)
        if subidx < len(parent.children):
            new_child = self._do_push_tail(
                level - BITS, parent.children[subidx], tail_node
            )
            new_children = list(parent.children)
            new_children[subidx] = new_child
            return Node(children=new_children)
        else:
            new_child = _new_path(level - BITS, tail_node)
            new_children = list(parent.children) + [new_child]
            return Node(children=new_children)

    def __len__(self):
        return self.size

    def __iter__(self):
        for i in range(self.size):
            yield self.get(i)

    def __eq__(self, other):
        if not isinstance(other, PersistentVector):
            return NotImplemented
        if self.size != other.size:
            return False
        return list(self) == list(other)

    def __repr__(self):
        return f"PersistentVector({list(self)})"
