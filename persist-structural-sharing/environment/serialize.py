"""
Pool-based serialization for PersistentVector with content-based deduplication.

Serialises one or more named PersistentVector instances into a single JSON-
compatible "pool" dictionary.  Shared subtrees — whether shared by Python
object identity or by structural content equality — are stored exactly once.

Deserialization reconstructs the vectors so that shared pool entries become
the same Python object (preserving structural sharing).

"""

import sys

sys.path.insert(0, "/app")

from pvec import PersistentVector, LeafNode, InnerNode, B


def serialize_pool(vectors):
    """
    Serialize a ``{name: PersistentVector}`` mapping into a pool dict.

    Two subtrees with identical recursive structure and leaf data are
    assigned the same pool ID (content-based deduplication / hash consing).
    An identity cache (Python ``id()``) avoids redundant traversals of
    subtrees that are already the same Python object.
    """
    identity_cache = {}   # id(node) -> pool_id
    content_cache = {}    # structural_key -> pool_id
    nodes = {}            # str(pool_id) -> node descriptor
    _next_id = [0]

    def _register(node):
        # Fast path: exact same Python object already registered.
        oid = id(node)
        if oid in identity_cache:
            return identity_cache[oid]

        # Build a structural content key bottom-up.
        if isinstance(node, LeafNode):
            key = ("L", node.data)            # data is already a tuple
        elif isinstance(node, InnerNode):
            child_ids = tuple(_register(c) for c in node.children)
            key = ("I", child_ids)
        else:
            raise TypeError(f"Unknown node type: {type(node)}")

        # Content dedup: reuse an existing pool entry with the same key.
        if key in content_cache:
            pid = content_cache[key]
            identity_cache[oid] = pid
            return pid

        # Allocate a fresh pool ID.
        pid = _next_id[0]
        _next_id[0] += 1
        content_cache[key] = pid
        identity_cache[oid] = pid

        if isinstance(node, LeafNode):
            nodes[str(pid)] = {"type": "leaf", "data": list(node.data)}
        else:
            nodes[str(pid)] = {"type": "inner", "children": list(child_ids)}

        return pid

    vec_entries = {}
    for name in sorted(vectors):
        v = vectors[name]
        root_id = _register(v.root)
        tail_id = _register(v.tail)
        vec_entries[name] = {
            "root": root_id,
            "tail": tail_id,
            "size": v.size,
            "shift": v.shift,
        }

    return {"B": B, "nodes": nodes, "vectors": vec_entries}


def deserialize_pool(pool):
    """
    Reconstruct ``{name: PersistentVector}`` from a pool dict.

    Nodes sharing a pool ID become the same Python object, preserving
    structural sharing.
    """
    nodes_data = pool["nodes"]
    built = {}             # int(pool_id) -> reconstructed node

    def _build(pid):
        pid_int = int(pid)
        if pid_int in built:
            return built[pid_int]

        info = nodes_data[str(pid_int)]
        if info["type"] == "leaf":
            node = LeafNode(tuple(info["data"]))
        elif info["type"] == "inner":
            children = tuple(_build(cid) for cid in info["children"])
            node = InnerNode(children)
        else:
            raise ValueError(f"Unknown node type: {info['type']}")

        built[pid_int] = node
        return node

    result = {}
    for name, vi in pool["vectors"].items():
        root = _build(vi["root"])
        tail = _build(vi["tail"])
        result[name] = PersistentVector(
            size=vi["size"],
            shift=vi["shift"],
            root=root,
            tail=tail,
        )
    return result
