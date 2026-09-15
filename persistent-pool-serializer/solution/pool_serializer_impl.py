
"""
Complete implementation of pool-based serialization for PersistentVector.
"""

import sys
sys.path.insert(0, '/app')
import copy
from persistent_vector import Node, PersistentVector, BITS, WIDTH, MASK


def serialize_to_pools(vectors):
    node_ids = {}
    leaves = []
    inners = []
    next_id = [0]

    def assign_id(node):
        py_id = id(node)
        if py_id in node_ids:
            return node_ids[py_id]
        nid = next_id[0]
        next_id[0] += 1
        node_ids[py_id] = nid

        if node.is_leaf:
            leaves.append([nid, list(node.values)])
        else:
            child_ids = [assign_id(c) for c in node.children]
            inners.append([nid, {"children": child_ids}])
        return nid

    vec_data = []
    for v in vectors:
        root_id = assign_id(v.root) if v.root is not None else None
        vec_data.append({
            "root": root_id,
            "tail": list(v.tail),
            "size": v.size,
            "shift": v.shift,
        })

    return {
        "B": BITS,
        "leaves": leaves,
        "inners": inners,
        "vectors": vec_data,
    }


def deserialize_from_pools(pool_data):
    node_map = {}

    for nid, values in pool_data["leaves"]:
        node_map[nid] = Node(values=list(values))

    pending = list(pool_data["inners"])
    safety = len(pending) + 1
    while pending and safety > 0:
        next_pending = []
        for nid, data in pending:
            child_ids = data["children"]
            if all(cid in node_map for cid in child_ids):
                children = [node_map[cid] for cid in child_ids]
                node_map[nid] = Node(children=children)
            else:
                next_pending.append((nid, data))
        if len(next_pending) == len(pending):
            raise ValueError("Unresolvable inner node dependencies")
        pending = next_pending
        safety -= 1

    vectors = []
    for vd in pool_data["vectors"]:
        root = node_map[vd["root"]] if vd["root"] is not None else None
        vectors.append(PersistentVector(
            size=vd["size"],
            shift=vd["shift"],
            root=root,
            tail=list(vd["tail"]),
        ))
    return vectors


def transform_pool(pool_data, transform_fn):
    result = copy.deepcopy(pool_data)
    result["leaves"] = [
        [nid, [transform_fn(v) for v in values]]
        for nid, values in result["leaves"]
    ]
    result["vectors"] = [
        {**vd, "tail": [transform_fn(v) for v in vd["tail"]]}
        for vd in result["vectors"]
    ]
    return result


def compute_shared_diff(vec_a, vec_b):
    changed = []
    added = []
    removed = []
    counter = [0]
    min_len = min(len(vec_a), len(vec_b))

    def diff_nodes(na, nb, shift, base_idx, limit):
        if na is nb:
            return
        counter[0] += 1
        if na.is_leaf and nb.is_leaf:
            for j in range(min(len(na.values), len(nb.values))):
                idx = base_idx + j
                if idx < limit:
                    if na.values[j] != nb.values[j]:
                        changed.append((idx, na.values[j], nb.values[j]))
        elif not na.is_leaf and not nb.is_leaf:
            stride = 1 << shift
            for j in range(min(len(na.children), len(nb.children))):
                child_base = base_idx + j * stride
                if child_base < limit:
                    diff_nodes(na.children[j], nb.children[j],
                               shift - BITS, child_base, limit)

    if (vec_a.root is not None and vec_b.root is not None
            and vec_a.shift == vec_b.shift):
        tree_limit = min(vec_a._tail_offset(), vec_b._tail_offset(), min_len)
        diff_nodes(vec_a.root, vec_b.root, vec_a.shift, 0, tree_limit)
        for i in range(tree_limit, min_len):
            va = vec_a.get(i)
            vb = vec_b.get(i)
            if va != vb:
                changed.append((i, va, vb))
    elif vec_a.root is not None or vec_b.root is not None:
        for i in range(min_len):
            va = vec_a.get(i)
            vb = vec_b.get(i)
            if va != vb:
                changed.append((i, va, vb))
    else:
        for i in range(min_len):
            va = vec_a.get(i)
            vb = vec_b.get(i)
            if va != vb:
                changed.append((i, va, vb))

    if len(vec_b) > len(vec_a):
        for i in range(len(vec_a), len(vec_b)):
            added.append((i, vec_b.get(i)))
    elif len(vec_a) > len(vec_b):
        for i in range(len(vec_b), len(vec_a)):
            removed.append((i, vec_a.get(i)))

    return {
        "changed": changed,
        "added": added,
        "removed": removed,
        "nodes_visited": counter[0],
    }
