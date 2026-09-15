"""
Persistent hash map based on a hash-array mapped prefix trie with
dual-bitmap compressed storage.

Each mutation returns a new map; previous versions remain valid.
Internal nodes use structural sharing to minimize memory overhead.
"""

# --- Constants ---
BITS_PER_LEVEL = 5
BRANCH_FACTOR = 1 << BITS_PER_LEVEL  # 32
MASK = BRANCH_FACTOR - 1
MAX_DEPTH = 6  # depths 0-5 consume 30 hash bits
HASH_MASK = 0xFFFFFFFF


def _hash32(key):
    return hash(key) & HASH_MASK


def _fragment(h, depth):
    return (h >> (depth * BITS_PER_LEVEL)) & MASK


def _bitpos(h, depth):
    return 1 << _fragment(h, depth)


def _popcount(n):
    return bin(n).count('1')


# --- Node types ---

class _Entry:
    """Inline key-value pair stored in a trie node's array."""
    __slots__ = ('hash', 'key', 'value')

    def __init__(self, h, key, value):
        self.hash = h
        self.key = key
        self.value = value


class _CollisionNode:
    """Leaf bucket for entries sharing the same 30-bit hash prefix."""
    __slots__ = ('entries',)

    def __init__(self, entries):
        self.entries = entries  # tuple of _Entry

    def get(self, key):
        for e in self.entries:
            if e.key == key:
                return e.value
        raise KeyError(key)

    def insert(self, h, key, value):
        for i, e in enumerate(self.entries):
            if e.key == key:
                if e.value == value:
                    return self, False
                lst = list(self.entries)
                lst[i] = _Entry(h, key, value)
                return _CollisionNode(tuple(lst)), False
        return _CollisionNode(self.entries + (_Entry(h, key, value),)), True

    def delete(self, key):
        for i, e in enumerate(self.entries):
            if e.key == key:
                remaining = self.entries[:i] + self.entries[i + 1:]
                return _CollisionNode(remaining), False
        raise KeyError(key)

    def iter_entries(self):
        return iter(self.entries)


class _SubNode:
    """Internal trie node with dual bitmaps for data and child slots."""
    __slots__ = ('data_map', 'node_map', 'array')

    def __init__(self, data_map, node_map, array):
        self.data_map = data_map
        self.node_map = node_map
        self.array = array  # tuple

    def _data_index(self, bit):
        return _popcount(self.data_map & (bit - 1))

    def _node_index(self, bit):
        return _popcount(self.data_map) + _popcount(self.node_map & (bit - 1))

    # -- lookup --

    def get(self, depth, h, key):
        bit = _bitpos(h, depth)
        if self.data_map & bit:
            e = self.array[self._data_index(bit)]
            if e.key == key:
                return e.value
            raise KeyError(key)
        if self.node_map & bit:
            child = self.array[self._node_index(bit)]
            if isinstance(child, _SubNode):
                return child.get(depth + 1, h, key)
            return child.get(key)
        raise KeyError(key)

    # -- insert --

    def insert(self, depth, h, key, value):
        bit = _bitpos(h, depth)

        if self.data_map & bit:
            idx = self._data_index(bit)
            entry = self.array[idx]
            if entry.key == key:
                # Key exists — replace value
                arr = list(self.array)
                arr[idx] = _Entry(h, key, value)
                return _SubNode(self.data_map, self.node_map, tuple(arr)), False
            child = _merge_two(depth + 1, entry, _Entry(h, key, value))
            dm = self.data_map ^ bit
            nm = self.node_map | bit
            arr = list(self.array)
            del arr[idx]
            ni = _popcount(dm) + _popcount(nm & (bit - 1))
            arr.insert(ni, child)
            return _SubNode(dm, nm, tuple(arr)), True

        if self.node_map & bit:
            idx = self._node_index(bit)
            child = self.array[idx]
            if isinstance(child, _SubNode):
                new_child, added = child.insert(depth + 1, h, key, value)
            else:
                new_child, added = child.insert(h, key, value)
            if new_child is child:
                return self, False
            arr = list(self.array)
            arr[idx] = new_child
            return _SubNode(self.data_map, self.node_map, tuple(arr)), added

        dm = self.data_map | bit
        idx = _popcount(dm & (bit - 1))
        arr = list(self.array)
        arr.insert(idx, _Entry(h, key, value))
        return _SubNode(dm, self.node_map, tuple(arr)), True

    # -- delete --

    def delete(self, depth, h, key):
        bit = _bitpos(h, depth)

        if self.data_map & bit:
            idx = self._data_index(bit)
            if self.array[idx].key != key:
                raise KeyError(key)
            dm = self.data_map ^ bit
            arr = list(self.array)
            del arr[idx]
            return _SubNode(dm, self.node_map, tuple(arr))

        if self.node_map & bit:
            idx = self._node_index(bit)
            child = self.array[idx]

            if isinstance(child, _SubNode):
                new_child = child.delete(depth + 1, h, key)
                arr = list(self.array)
                arr[idx] = new_child
                return _SubNode(self.data_map, self.node_map, tuple(arr))
            else:  # _CollisionNode
                result, _ = child.delete(key)
                arr = list(self.array)
                arr[idx] = result
                return _SubNode(self.data_map, self.node_map, tuple(arr))

        raise KeyError(key)

    # -- iteration --

    def iter_entries(self):
        nd = _popcount(self.data_map)
        for i in range(nd):
            yield self.array[i]
        for i in range(nd, len(self.array)):
            yield from self.array[i].iter_entries()


# --- Helpers ---

def _merge_two(depth, e1, e2):
    """Build a subtree containing exactly two entries."""
    if depth >= MAX_DEPTH:
        return _CollisionNode((e1, e2))
    i1 = _fragment(e1.hash, depth)
    i2 = _fragment(e2.hash, depth)
    if i1 == i2:
        child = _merge_two(depth + 1, e1, e2)
        return _SubNode(0, 1 << i1, (child,))
    b1, b2 = 1 << i1, 1 << i2
    if i1 < i2:
        return _SubNode(b1 | b2, 0, (e1, e2))
    return _SubNode(b1 | b2, 0, (e2, e1))


_EMPTY = _SubNode(0, 0, ())


# --- Diff ---

def _diff_nodes(a, b, depth, out):
    """Recursively collect keys that differ between two nodes."""
    if a is b:
        return
    if isinstance(a, _SubNode) and isinstance(b, _SubNode):
        _diff_sub(a, b, depth, out)
    elif isinstance(a, _CollisionNode) and isinstance(b, _CollisionNode):
        _diff_coll(a, b, out)
    else:
        for e in a.iter_entries():
            out.add(e.key)
        for e in b.iter_entries():
            out.add(e.key)


def _diff_sub(a, b, depth, out):
    remaining = a.data_map | a.node_map | b.data_map | b.node_map
    while remaining:
        bit = remaining & (-remaining)
        remaining ^= bit
        ad = bool(a.data_map & bit)
        an = bool(a.node_map & bit)
        bd = bool(b.data_map & bit)
        bn = bool(b.node_map & bit)

        if ad and bd:
            ea = a.array[a._data_index(bit)]
            eb = b.array[b._data_index(bit)]
            if ea.key != eb.key or ea.value != eb.value:
                out.add(ea.key)
                if ea.key != eb.key:
                    out.add(eb.key)
        elif an and bn:
            ca = a.array[a._node_index(bit)]
            cb = b.array[b._node_index(bit)]
            _diff_nodes(ca, cb, depth + 1, out)
        elif ad and bn:
            ea = a.array[a._data_index(bit)]
            cb = b.array[b._node_index(bit)]
            _entry_vs_node(ea, cb, depth + 1, out)
        elif an and bd:
            ca = a.array[a._node_index(bit)]
            eb = b.array[b._data_index(bit)]
            _entry_vs_node(eb, ca, depth + 1, out)
        elif ad:
            out.add(a.array[a._data_index(bit)].key)
        elif an:
            for e in a.array[a._node_index(bit)].iter_entries():
                out.add(e.key)
        elif bd:
            out.add(b.array[b._data_index(bit)].key)
        elif bn:
            for e in b.array[b._node_index(bit)].iter_entries():
                out.add(e.key)


def _entry_vs_node(entry, node, depth, out):
    """Diff a single inline entry against a subtree."""
    if isinstance(node, _SubNode):
        try:
            v = node.get(depth, entry.hash, entry.key)
            if v != entry.value:
                out.add(entry.key)
        except KeyError:
            out.add(entry.key)
        for e in node.iter_entries():
            if e.key != entry.key:
                out.add(e.key)
    else:  # _CollisionNode
        found = False
        for e in node.entries:
            if e.key == entry.key:
                if e.value != entry.value:
                    out.add(entry.key)
                found = True
            else:
                out.add(e.key)
        if not found:
            out.add(entry.key)


def _diff_coll(a, b, out):
    da = {e.key: e.value for e in a.entries}
    db = {e.key: e.value for e in b.entries}
    for k, v in da.items():
        if k not in db or db[k] != v:
            out.add(k)
    for k, v in db.items():
        if k not in da or da[k] != v:
            out.add(k)


# --- Public API ---

class PersistentMap:
    """Persistent (immutable) hash map with structural sharing."""
    __slots__ = ('_root', '_size')

    def __init__(self, root=None, size=0):
        self._root = root if root is not None else _EMPTY
        self._size = size

    def get(self, key, default=None):
        try:
            return self._root.get(0, _hash32(key), key)
        except KeyError:
            return default

    def __getitem__(self, key):
        return self._root.get(0, _hash32(key), key)

    def __contains__(self, key):
        try:
            self._root.get(0, _hash32(key), key)
            return True
        except KeyError:
            return False

    def __len__(self):
        return self._size

    def insert(self, key, value):
        new_root, added = self._root.insert(0, _hash32(key), key, value)
        if new_root is self._root:
            return self
        return PersistentMap(new_root, self._size + (1 if added else 0))

    def delete(self, key):
        new_root = self._root.delete(0, _hash32(key), key)
        return PersistentMap(new_root, self._size - 1)

    def __iter__(self):
        for e in self._root.iter_entries():
            yield e.key

    def items(self):
        for e in self._root.iter_entries():
            yield e.key, e.value

    def keys(self):
        return iter(self)

    def values(self):
        for e in self._root.iter_entries():
            yield e.value

    def diff(self, other):
        out = set()
        _diff_nodes(self._root, other._root, 0, out)
        return out

    @staticmethod
    def from_dict(d):
        m = PersistentMap()
        for k, v in d.items():
            m = m.insert(k, v)
        return m

    def to_dict(self):
        return dict(self.items())

    def _root_node(self):
        return self._root
