
"""
Key-value store — reference solution.
"""

from bplustree import (
    Config, DataNode, IndexNode, new_tree, lookup_path,
    right_successor_path, _insert_into_tree, _delete_from_tree, _compare,
)
from ops import InsertOp, DeleteOp


def _enqueue_recursive(tree, ops, deferred_ops):
    """Recursive enqueue implementation.

    Returns the updated tree node. deferred_ops accumulates ops that
    reached a leaf and must be applied directly to the tree.
    """
    if isinstance(tree, DataNode):
        deferred_ops.extend(ops)
        return tree

    if not ops:
        return tree

    # Check if buffer has room
    total = len(ops) + len(tree.op_buf)
    if total <= tree.cfg.op_buf_size:
        return IndexNode(
            children=list(tree.children),
            op_buf=list(tree.op_buf) + list(ops),
            cfg=tree.cfg,
        )

    # Overflow: combine existing buffer + new ops, sort by key, partition among children
    all_ops = sorted(
        list(tree.op_buf) + list(ops),
        key=lambda op: op.affects_key(),
    )

    new_children = list(tree.children)
    remaining_ops = list(all_ops)

    for i in range(len(tree.children)):
        is_last = (i == len(tree.children) - 1)
        child = tree.children[i]

        if is_last:
            took = remaining_ops
            remaining_ops = []
        else:
            child_last_key = child.last_key()
            if child_last_key is None:
                took = []
            else:
                took = []
                leftover = []
                for op in remaining_ops:
                    if _compare(op.affects_key(), child_last_key) <= 0:
                        took.append(op)
                    else:
                        leftover.append(op)
                remaining_ops = leftover

        if took:
            new_child = _enqueue_recursive(child, took, deferred_ops)
            new_children[i] = new_child

    return IndexNode(
        children=new_children,
        op_buf=[],
        cfg=tree.cfg,
    )


def enqueue(tree, ops: list):
    """Apply a batch of operations to the tree. Returns the new tree root."""
    if not ops:
        return tree

    deferred_ops = []
    result = _enqueue_recursive(tree, ops, deferred_ops)

    # Apply deferred ops (those that reached leaves) directly
    for op in deferred_ops:
        if isinstance(op, InsertOp):
            result = _insert_into_tree(result, op.key, op.value)
        elif isinstance(op, DeleteOp):
            result = _delete_from_tree(result, op.key)

    return result


def _apply_ops_in_path(path: list) -> dict:
    """Collect pending ops from all index nodes in the path, filter to the
    target leaf's key range, apply them, and return the resulting dict.

    Path format: [node, child_index, node, child_index, ..., leaf_node]
    """
    if not path:
        return {}

    leaf = path[-1]
    if not isinstance(leaf, DataNode):
        return {}

    if len(path) <= 1:
        return dict(leaf.children)

    # Collect all ops from index nodes along the path
    all_ops = []
    for elem in path:
        if isinstance(elem, IndexNode):
            all_ops.extend(elem.op_buf)

    if not all_ops:
        return dict(leaf.children)

    # Sort ops by key (stable sort for same-key ordering preservation)
    all_ops.sort(key=lambda op: op.affects_key())

    # Compute left boundary: max last_key of left siblings along the path
    left_boundaries = []
    is_last = True

    p = list(path)
    while len(p) >= 3:
        node = p[-1]
        child_idx = p[-2]
        parent = p[-3]

        if child_idx < len(parent.children) - 1:
            is_last = False

        if child_idx > 0:
            left_sib = parent.children[child_idx - 1]
            lk = left_sib.last_key()
            if lk is not None:
                left_boundaries.append(lk)

        p = p[:-2]

    left_bound = max(left_boundaries) if left_boundaries else None
    right_bound = leaf.last_key() if not is_last else None

    # Filter ops
    filtered = []
    for op in all_ops:
        k = op.affects_key()
        if left_bound is not None and _compare(k, left_bound) <= 0:
            continue
        if right_bound is not None and _compare(k, right_bound) > 0:
            continue
        filtered.append(op)

    # Apply filtered ops to leaf's data
    result = dict(leaf.children)
    for op in filtered:
        result = op.apply_to_collection(result)

    return result


def lookup(tree, key, default=None):
    """Look up a key in the tree. Returns the value or default if absent."""
    path = lookup_path(tree, key)
    if not path:
        return default
    expanded = _apply_ops_in_path(path)
    return expanded.get(key, default)


def insert(tree, key, value):
    """Insert a key-value pair. Returns the new tree root."""
    return enqueue(tree, [InsertOp(key=key, value=value)])


def delete(tree, key):
    """Delete a key. Returns the new tree root."""
    return enqueue(tree, [DeleteOp(key=key)])


def forward_iter(tree, start_key):
    """Return a list of (key, value) pairs with key >= start_key, in sorted order."""
    result = []
    path = lookup_path(tree, start_key)

    if not path:
        return result

    first_leaf = True

    while path is not None:
        leaf = path[-1]
        if not isinstance(leaf, DataNode):
            break

        expanded = _apply_ops_in_path(path)

        for k in sorted(expanded.keys()):
            if first_leaf and _compare(k, start_key) < 0:
                continue
            result.append((k, expanded[k]))

        first_leaf = False
        path = right_successor_path(path)

    return result


def save_tree(tree, name, host="localhost", port=6379):
    """Persist the tree to Redis under the given name."""
    import pickle
    import redis as _redis
    r = _redis.Redis(host=host, port=port)
    data = pickle.dumps(tree, protocol=pickle.HIGHEST_PROTOCOL)
    r.set(f"hitchhiker:{name}", data)


def load_tree(name, host="localhost", port=6379):
    """Load a previously saved tree from Redis. Raise if not found."""
    import pickle
    import redis as _redis
    r = _redis.Redis(host=host, port=port)
    data = r.get(f"hitchhiker:{name}")
    if data is None:
        raise KeyError(f"No tree found with name '{name}'")
    return pickle.loads(data)
