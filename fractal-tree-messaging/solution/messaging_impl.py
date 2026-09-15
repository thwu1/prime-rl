"""
Hitchhiker tree messaging layer — reference implementation.

Implements the operation buffer overlay on top of the B+ tree core,
plus Redis-backed tree persistence.
"""


import sys
import json
import uuid

sys.path.insert(0, "/app")

from hitchhiker.core import (
    Config, DataNode, IndexNode, Split,
    new_tree, lookup_path, right_successor,
    insert as core_insert,
    delete as core_delete,
)


# ---- Operation types -------------------------------------------------------

class InsertOp:
    """Represents a buffered insert operation."""
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

    def __repr__(self):
        return f"InsertOp({self.key!r}, {self.value!r})"


class DeleteOp:
    """Represents a buffered delete operation."""
    __slots__ = ("key",)

    def __init__(self, key):
        self.key = key

    def apply_to_coll(self, d):
        result = dict(d)
        result.pop(self.key, None)
        return result

    def apply_to_tree(self, tree):
        return core_delete(tree, self.key)

    def __repr__(self):
        return f"DeleteOp({self.key!r})"


# ---- Core messaging algorithm ----------------------------------------------

def enqueue(tree, ops):
    """Add operations to message buffers with overflow cascading."""
    deferred = []
    result = _enqueue_recursive(tree, ops, deferred)
    for op in deferred:
        result = op.apply_to_tree(result)
    return result


def _enqueue_recursive(tree, ops, deferred):
    if tree.is_data():
        deferred.extend(ops)
        return tree

    if len(ops) + len(tree.op_buf) <= tree.cfg.op_buf_size:
        return IndexNode(tree.cfg, list(tree.children),
                         list(tree.op_buf) + list(ops))

    all_ops = sorted(list(tree.op_buf) + list(ops), key=lambda o: o.key)

    rebuilt_children = []
    remaining = all_ops

    for i, child in enumerate(tree.children):
        is_last = (i == len(tree.children) - 1)

        if is_last:
            if remaining:
                new_child = _enqueue_recursive(child, remaining, deferred)
            else:
                new_child = child
        else:
            child_last = child.last_key()
            took = []
            rest = []
            for op in remaining:
                if child_last is not None and op.key <= child_last:
                    took.append(op)
                else:
                    rest.append(op)

            if took:
                new_child = _enqueue_recursive(child, took, deferred)
            else:
                new_child = child
            remaining = rest

        rebuilt_children.append(new_child)

    return IndexNode(tree.cfg, rebuilt_children, [])


def apply_ops_in_path(path):
    """Materialize leaf data by applying buffered ops along the path."""
    if not path:
        return {}
    if len(path) <= 1:
        return dict(path[0].children)

    index_nodes = []
    for elem in path:
        if hasattr(elem, "is_index") and callable(elem.is_index) and elem.is_index():
            index_nodes.append(elem)

    all_ops = []
    for node in reversed(index_nodes):
        all_ops.extend(node.op_buf)

    all_ops.sort(key=lambda o: o.key)

    data_node = path[-1]

    left_sibs = []
    is_last = True

    i = len(path) - 1
    while i >= 2:
        node_idx = path[i - 1]
        parent = path[i - 2]

        local_last = (node_idx == len(parent.children) - 1)
        is_last = is_last and local_last

        if node_idx > 0:
            left_sibs.append(parent.children[node_idx - 1])

        i -= 2

    left_max = None
    if left_sibs:
        left_keys = [s.last_key() for s in left_sibs if s.last_key() is not None]
        if left_keys:
            left_max = max(left_keys)

    my_last = data_node.last_key()

    filtered = []
    for op in all_ops:
        if left_max is not None and op.key <= left_max:
            continue
        if not is_last and my_last is not None and op.key > my_last:
            continue
        filtered.append(op)

    result = dict(data_node.children)
    for op in filtered:
        result = op.apply_to_coll(result)

    return result


def lookup(tree, key, default=None):
    path = lookup_path(tree, key)
    expanded = apply_ops_in_path(path)
    return expanded.get(key, default)


def insert(tree, key, value):
    return enqueue(tree, [InsertOp(key, value)])


def delete(tree, key):
    return enqueue(tree, [DeleteOp(key)])


def forward_iterator(tree, start_key):
    """Yield (key, value) pairs >= start_key in sorted order."""
    path = lookup_path(tree, start_key)
    is_first = True

    while path:
        expanded = apply_ops_in_path(path)
        for k, v in sorted(expanded.items()):
            if is_first and k < start_key:
                continue
            yield (k, v)
        is_first = False
        path = right_successor(path)


# ---- Redis persistence -----------------------------------------------------

def save_tree(tree, redis_client):
    """Serialize a tree to Redis with per-node granularity. Returns root key."""

    def _save_node(node):
        nkey = f"ht:{uuid.uuid4()}"
        if node.is_data():
            mapping = {
                'type': 'data',
                'cfg_ib': str(node.cfg.index_b),
                'cfg_db': str(node.cfg.data_b),
                'cfg_obs': str(node.cfg.op_buf_size),
                'children': json.dumps(list(node.children.items())),
            }
        else:
            child_keys = [_save_node(c) for c in node.children]
            ops = []
            for op in node.op_buf:
                if isinstance(op, InsertOp):
                    ops.append(['i', op.key, op.value])
                else:
                    ops.append(['d', op.key])
            mapping = {
                'type': 'index',
                'cfg_ib': str(node.cfg.index_b),
                'cfg_db': str(node.cfg.data_b),
                'cfg_obs': str(node.cfg.op_buf_size),
                'children': json.dumps(child_keys),
                'op_buf': json.dumps(ops),
            }
        redis_client.hset(nkey, mapping=mapping)
        return nkey

    return _save_node(tree)


def load_tree(root_key, redis_client):
    """Deserialize a tree from Redis."""
    raw = redis_client.hgetall(root_key)
    d = {(k.decode() if isinstance(k, bytes) else k):
         (v.decode() if isinstance(v, bytes) else v)
         for k, v in raw.items()}

    if not d:
        raise ValueError(f"No data found at Redis key: {root_key}")

    cfg = Config(
        index_b=int(d['cfg_ib']),
        data_b=int(d['cfg_db']),
        op_buf_size=int(d['cfg_obs']),
    )

    if d['type'] == 'data':
        items = json.loads(d['children'])
        children = {k: v for k, v in items}
        return DataNode(cfg, children)
    else:
        child_keys = json.loads(d['children'])
        children = [load_tree(ck, redis_client) for ck in child_keys]
        ops_raw = json.loads(d['op_buf'])
        ops = []
        for entry in ops_raw:
            if entry[0] == 'i':
                ops.append(InsertOp(entry[1], entry[2]))
            else:
                ops.append(DeleteOp(entry[1]))
        return IndexNode(cfg, children, ops)
