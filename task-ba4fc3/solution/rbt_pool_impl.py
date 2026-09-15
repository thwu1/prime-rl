#!/usr/bin/env python3
"""
RBT Pool Tool — Persistent Vector with Pool-Based Serialization.

Implements Radix Balanced Trees (RBTs) with structural sharing and a JSON
pool format inspired by immer::persist.
"""

import json
import sys
import argparse
import subprocess
import sqlite3
from collections import defaultdict


# ── Node types ──────────────────────────────────────────────────────────────


class LeafNode:
    __slots__ = ["elements"]

    def __init__(self, elements):
        self.elements = list(elements)


class InnerNode:
    __slots__ = ["children"]

    def __init__(self, children):
        self.children = list(children)


# ── Persistent vector ──────────────────────────────────────────────────────


class PersistentVector:
    """Persistent vector backed by a Radix Balanced Tree with tail optimisation."""

    def __init__(self, root=None, tail=None, size=0, shift=0, B=5, BL=5):
        self.root = root
        self.tail = tail if tail is not None else LeafNode([])
        self.size = size
        self.shift = shift
        self.B = B
        self.BL = BL
        self.M = 1 << B
        self.ML = 1 << BL

    # ── helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def from_elements(elements, B=5, BL=5):
        vec = PersistentVector(B=B, BL=BL)
        for e in elements:
            vec = vec.push_back(e)
        return vec

    def tail_offset(self):
        if self.size == 0:
            return 0
        return ((self.size - 1) >> self.BL) << self.BL

    def tail_size(self):
        return self.size - self.tail_offset()

    # ── read ────────────────────────────────────────────────────────────

    def get(self, index):
        if index < 0 or index >= self.size:
            raise IndexError(index)
        to = self.tail_offset()
        if index >= to:
            return self.tail.elements[index - to]
        node = self.root
        shift = self.shift
        while shift > self.BL:
            node = node.children[(index >> shift) & (self.M - 1)]
            shift -= self.B
        leaf = node.children[(index >> self.BL) & (self.M - 1)]
        return leaf.elements[index & (self.ML - 1)]

    # ── push_back ───────────────────────────────────────────────────────

    def push_back(self, value):
        if self.tail_size() < self.ML:
            new_tail = LeafNode(self.tail.elements + [value])
            return PersistentVector(
                self.root, new_tail, self.size + 1, self.shift, self.B, self.BL
            )

        old_tail = self.tail
        new_tail = LeafNode([value])

        if self.root is None:
            return PersistentVector(
                InnerNode([old_tail]),
                new_tail,
                self.size + 1,
                self.BL,
                self.B,
                self.BL,
            )

        tree_cap = 1 << (self.shift + self.B)
        if self.tail_offset() >= tree_cap:
            new_root = InnerNode(
                [self.root, self._new_path(self.shift, old_tail)]
            )
            return PersistentVector(
                new_root,
                new_tail,
                self.size + 1,
                self.shift + self.B,
                self.B,
                self.BL,
            )

        new_root = self._push_tail(
            self.root, self.shift, self.tail_offset(), old_tail
        )
        return PersistentVector(
            new_root, new_tail, self.size + 1, self.shift, self.B, self.BL
        )

    def _push_tail(self, node, shift, idx, tail_leaf):
        if shift == self.BL:
            return InnerNode(list(node.children) + [tail_leaf])
        ci = (idx >> shift) & (self.M - 1)
        if ci < len(node.children):
            updated = self._push_tail(
                node.children[ci], shift - self.B, idx, tail_leaf
            )
            children = list(node.children)
            children[ci] = updated
            return InnerNode(children)
        return InnerNode(
            list(node.children)
            + [self._new_path(shift - self.B, tail_leaf)]
        )

    def _new_path(self, shift, leaf):
        if shift == self.BL:
            return InnerNode([leaf])
        return InnerNode([self._new_path(shift - self.B, leaf)])

    # ── set ─────────────────────────────────────────────────────────────

    def set(self, index, value):
        if index < 0 or index >= self.size:
            raise IndexError(index)
        to = self.tail_offset()
        if index >= to:
            elems = list(self.tail.elements)
            elems[index - to] = value
            return PersistentVector(
                self.root, LeafNode(elems), self.size, self.shift, self.B, self.BL
            )
        new_root = self._set_tree(self.root, self.shift, index, value)
        return PersistentVector(
            new_root, self.tail, self.size, self.shift, self.B, self.BL
        )

    def _set_tree(self, node, shift, index, value):
        children = list(node.children)
        if shift == self.BL:
            ci = (index >> self.BL) & (self.M - 1)
            elems = list(node.children[ci].elements)
            elems[index & (self.ML - 1)] = value
            children[ci] = LeafNode(elems)
        else:
            ci = (index >> shift) & (self.M - 1)
            children[ci] = self._set_tree(
                node.children[ci], shift - self.B, index, value
            )
        return InnerNode(children)

    # ── materialise ────────────────────────────────────────────────────

    def to_list(self):
        out = []
        if self.root is not None:
            self._collect(self.root, out)
        out.extend(self.tail.elements)
        return out

    def _collect(self, node, out):
        if isinstance(node, LeafNode):
            out.extend(node.elements)
        else:
            for c in node.children:
                self._collect(c, out)

    def __len__(self):
        return self.size

    def __getitem__(self, i):
        return self.get(i)


# ── Pool serialisation ─────────────────────────────────────────────────────


def serialize_pools(named_vectors, B, BL):
    """Serialise a dict of {name: PersistentVector} to pool JSON."""
    id_map = {}  # python id(node) → assigned int id
    leaves = []
    inners = []
    counter = [0]

    def assign(node):
        key = id(node)
        if key in id_map:
            return id_map[key]
        nid = counter[0]
        counter[0] += 1
        id_map[key] = nid
        if isinstance(node, LeafNode):
            leaves.append([nid, list(node.elements)])
        else:
            cids = [assign(c) for c in node.children]
            inners.append([nid, {"children": cids, "relaxed": False}])
        return nid

    vectors_list = []
    name_map = {}
    vec_ident = {}  # (id(root), id(tail)) → vec index

    for name, vec in named_vectors.items():
        vk = (id(vec.root), id(vec.tail))
        if vk in vec_ident:
            name_map[name] = vec_ident[vk]
            continue
        vi = len(vectors_list)
        vec_ident[vk] = vi
        name_map[name] = vi
        root_id = assign(vec.root) if vec.root is not None else None
        tail_id = assign(vec.tail) if vec.size > 0 else None
        vectors_list.append({"root": root_id, "tail": tail_id})

    return {
        "named_vectors": name_map,
        "pool": {
            "B": B,
            "BL": BL,
            "leaves": leaves,
            "inners": inners,
            "vectors": vectors_list,
        },
    }


# ── Pool deserialisation ──────────────────────────────────────────────────


def deserialize_pool(pool_json):
    pool = pool_json["pool"]
    leaves = {item[0]: item[1] for item in pool["leaves"]}
    inners = {item[0]: item[1] for item in pool["inners"]}

    def collect(nid):
        if nid in leaves:
            return list(leaves[nid])
        elems = []
        for cid in inners[nid]["children"]:
            elems.extend(collect(cid))
        return elems

    result = {}
    for name, idx in pool_json["named_vectors"].items():
        vec = pool["vectors"][idx]
        elems = []
        if vec["root"] is not None:
            elems.extend(collect(vec["root"]))
        if vec.get("tail") is not None:
            elems.extend(collect(vec["tail"]))
        result[name] = elems
    return result


# ── Validation ─────────────────────────────────────────────────────────────


def validate_pool(pool_json):
    errors = []
    pool = pool_json.get("pool", {})
    B = pool.get("B")
    BL = pool.get("BL")

    if not isinstance(B, int) or B < 1:
        errors.append(f"Invalid B: {B}")
    if not isinstance(BL, int) or BL < 1:
        errors.append(f"Invalid BL: {BL}")
    if errors:
        return False, errors

    M = 1 << B
    ML = 1 << BL
    leaf_ids = set()
    inner_ids = set()

    for item in pool.get("leaves", []):
        lid, elems = item[0], item[1]
        if lid in leaf_ids:
            errors.append(f"Duplicate leaf ID: {lid}")
        leaf_ids.add(lid)
        if not isinstance(elems, list):
            errors.append(f"Leaf {lid}: elements not a list")
        elif len(elems) > ML:
            errors.append(f"Leaf {lid}: {len(elems)} elements > ML={ML}")
        elif len(elems) == 0:
            errors.append(f"Leaf {lid}: empty")

    for item in pool.get("inners", []):
        iid, data = item[0], item[1]
        if iid in inner_ids:
            errors.append(f"Duplicate inner ID: {iid}")
        if iid in leaf_ids:
            errors.append(f"ID {iid} used as both leaf and inner")
        inner_ids.add(iid)
        children = data.get("children", [])
        if len(children) > M:
            errors.append(f"Inner {iid}: {len(children)} children > M={M}")
        if len(children) == 0:
            errors.append(f"Inner {iid}: no children")

    all_ids = leaf_ids | inner_ids
    inner_lookup = {}
    for item in pool.get("inners", []):
        inner_lookup[item[0]] = item[1]
        for cid in item[1].get("children", []):
            if cid not in all_ids:
                errors.append(f"Dangling ref: inner {item[0]} -> child {cid}")

    for i, vec in enumerate(pool.get("vectors", [])):
        rid = vec.get("root")
        tid = vec.get("tail")
        if rid is not None and rid not in inner_ids:
            errors.append(f"Vector {i}: root {rid} not in inners")
        if tid is not None and tid not in leaf_ids:
            errors.append(f"Vector {i}: tail {tid} not in leaves")

    # cycle detection
    def has_cycle(nid, path):
        if nid in path:
            return True
        if nid not in inner_lookup:
            return False
        extended = path | {nid}
        for cid in inner_lookup[nid].get("children", []):
            if has_cycle(cid, extended):
                return True
        return False

    for iid in inner_ids:
        if has_cycle(iid, frozenset()):
            errors.append(f"Cycle involving inner {iid}")
            break

    return len(errors) == 0, errors


# ── Analysis ───────────────────────────────────────────────────────────────


def analyze_pool(pool_json):
    pool = pool_json["pool"]
    leaves = {item[0]: item[1] for item in pool["leaves"]}
    inners = {item[0]: item[1] for item in pool["inners"]}

    refcount = defaultdict(int)

    def walk(nid, seen):
        if nid in seen:
            return
        seen.add(nid)
        refcount[nid] += 1
        if nid in inners:
            for cid in inners[nid]["children"]:
                walk(cid, seen)

    for vec in pool["vectors"]:
        seen = set()
        if vec["root"] is not None:
            walk(vec["root"], seen)
        if vec.get("tail") is not None:
            walk(vec["tail"], seen)

    shared = {nid: c for nid, c in refcount.items() if c > 1}

    per_vec = {}
    for name, idx in pool_json["named_vectors"].items():
        vec = pool["vectors"][idx]
        elems = []

        def _coll(nid):
            if nid in leaves:
                elems.extend(leaves[nid])
            elif nid in inners:
                for cid in inners[nid]["children"]:
                    _coll(cid)

        if vec["root"] is not None:
            _coll(vec["root"])
        if vec.get("tail") is not None:
            _coll(vec["tail"])
        per_vec[name] = len(elems)

    naive = sum(per_vec.values())
    actual = sum(len(v) for v in leaves.values())
    ratio = round(1 - actual / naive, 4) if naive > 0 else 0.0

    return {
        "total_nodes": len(leaves) + len(inners),
        "leaf_nodes": len(leaves),
        "inner_nodes": len(inners),
        "shared_nodes": len(shared),
        "shared_node_ids": sorted(shared.keys()),
        "elements_per_vector": per_vec,
        "naive_total_elements": naive,
        "actual_stored_elements": actual,
        "sharing_ratio": ratio,
    }


# ── Transform ──────────────────────────────────────────────────────────────


def transform_pool(pool_json, spec):
    pool = pool_json["pool"]
    ttype = spec["type"]

    def xform(elem):
        if ttype == "multiply":
            return elem * spec["factor"]
        if ttype == "add":
            return elem + spec["value"]
        if ttype == "uppercase":
            return elem.upper() if isinstance(elem, str) else elem
        if ttype == "negate":
            return -elem
        if ttype == "to_string":
            return str(elem)
        raise ValueError(f"Unknown transform type: {ttype}")

    new_leaves = [[lid, [xform(e) for e in elems]] for lid, elems in pool["leaves"]]

    return {
        "named_vectors": pool_json["named_vectors"],
        "pool": {**pool, "leaves": new_leaves},
    }


# ── Visualize (DOT → SVG via graphviz) ───────────────────────────────────


def _find_shared_nodes(pool_json):
    """Return set of node IDs referenced by more than one vector."""
    pool = pool_json["pool"]
    inners = {item[0]: item[1] for item in pool["inners"]}
    leaf_ids = {item[0] for item in pool["leaves"]}
    refcount = defaultdict(int)

    def walk(nid, seen):
        if nid in seen:
            return
        seen.add(nid)
        refcount[nid] += 1
        if nid in inners:
            for cid in inners[nid]["children"]:
                walk(cid, seen)

    for vec in pool["vectors"]:
        seen = set()
        if vec["root"] is not None:
            walk(vec["root"], seen)
        if vec.get("tail") is not None:
            walk(vec["tail"], seen)

    return {nid for nid, c in refcount.items() if c > 1}


def visualize_pool(pool_json, output_path):
    pool = pool_json["pool"]
    leaf_map = {item[0]: item[1] for item in pool["leaves"]}
    inner_map = {item[0]: item[1] for item in pool["inners"]}
    shared = _find_shared_nodes(pool_json)

    lines = ["digraph pool {", "  rankdir=TB;", "  node [shape=record];"]

    # Leaf nodes
    for lid, elems in pool["leaves"]:
        color = "#ffd700" if lid in shared else "#90ee90"
        elem_str = ",".join(str(e) for e in elems)
        label = f"L{lid}|{elem_str}"
        lines.append(
            f'  n{lid} [label="{{{label}}}" style=filled fillcolor="{color}"];'
        )

    # Inner nodes
    for iid, data in pool["inners"]:
        color = "#ffd700" if iid in shared else "#add8e6"
        lines.append(
            f'  n{iid} [label="I{iid}" style=filled fillcolor="{color}"];'
        )
        for cid in data["children"]:
            lines.append(f"  n{iid} -> n{cid};")

    # Vector descriptors
    for i, vec in enumerate(pool["vectors"]):
        names = [n for n, idx in pool_json["named_vectors"].items() if idx == i]
        label = f"V{i}: {','.join(sorted(names))}"
        lines.append(
            f'  vec{i} [label="{label}" shape=ellipse style=filled fillcolor="#ffc0cb"];'
        )
        if vec["root"] is not None:
            lines.append(f'  vec{i} -> n{vec["root"]} [label="root"];')
        if vec.get("tail") is not None:
            lines.append(f'  vec{i} -> n{vec["tail"]} [label="tail"];')

    lines.append("}")
    dot_source = "\n".join(lines)

    result = subprocess.run(
        ["dot", "-Tsvg"],
        input=dot_source,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"dot error: {result.stderr}", file=sys.stderr)
        sys.exit(1)

    with open(output_path, "w") as f:
        f.write(result.stdout)


# ── Store (pool → SQLite) ────────────────────────────────────────────────


def store_pool_to_db(pool_json, db_path):
    pool = pool_json["pool"]
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")

    conn.execute(
        "CREATE TABLE metadata ("
        "key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE leaf_nodes ("
        "node_id INTEGER PRIMARY KEY, elements TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE inner_nodes ("
        "node_id INTEGER PRIMARY KEY, relaxed INTEGER NOT NULL DEFAULT 0)"
    )
    conn.execute(
        "CREATE TABLE inner_children ("
        "inner_id INTEGER NOT NULL, "
        "position INTEGER NOT NULL, "
        "child_id INTEGER NOT NULL, "
        "PRIMARY KEY (inner_id, position), "
        "FOREIGN KEY (inner_id) REFERENCES inner_nodes(node_id))"
    )
    conn.execute(
        "CREATE TABLE vectors ("
        "vector_index INTEGER PRIMARY KEY, "
        "root_id INTEGER, "
        "tail_id INTEGER, "
        "FOREIGN KEY (tail_id) REFERENCES leaf_nodes(node_id))"
    )
    conn.execute(
        "CREATE TABLE named_vectors ("
        "name TEXT PRIMARY KEY, "
        "vector_index INTEGER NOT NULL, "
        "FOREIGN KEY (vector_index) REFERENCES vectors(vector_index))"
    )

    conn.execute("INSERT INTO metadata VALUES (?, ?)", ("B", str(pool["B"])))
    conn.execute("INSERT INTO metadata VALUES (?, ?)", ("BL", str(pool["BL"])))

    for lid, elems in pool["leaves"]:
        conn.execute(
            "INSERT INTO leaf_nodes VALUES (?, ?)", (lid, json.dumps(elems))
        )

    for iid, data in pool["inners"]:
        conn.execute(
            "INSERT INTO inner_nodes VALUES (?, ?)",
            (iid, int(data.get("relaxed", False))),
        )
        for pos, cid in enumerate(data["children"]):
            conn.execute(
                "INSERT INTO inner_children VALUES (?, ?, ?)", (iid, pos, cid)
            )

    for i, vec in enumerate(pool["vectors"]):
        conn.execute(
            "INSERT INTO vectors VALUES (?, ?, ?)",
            (i, vec["root"], vec["tail"]),
        )

    for name, idx in pool_json["named_vectors"].items():
        conn.execute("INSERT INTO named_vectors VALUES (?, ?)", (name, idx))

    conn.commit()
    conn.close()


# ── Load (SQLite → pool) ────────────────────────────────────────────────


def load_pool_from_db(db_path):
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")

    meta = dict(conn.execute("SELECT key, value FROM metadata").fetchall())
    B = int(meta["B"])
    BL = int(meta["BL"])

    leaves = []
    for row in conn.execute("SELECT node_id, elements FROM leaf_nodes ORDER BY node_id"):
        leaves.append([row[0], json.loads(row[1])])

    inners = []
    for row in conn.execute("SELECT node_id, relaxed FROM inner_nodes ORDER BY node_id"):
        iid = row[0]
        relaxed = bool(row[1])
        children = [
            r[0]
            for r in conn.execute(
                "SELECT child_id FROM inner_children "
                "WHERE inner_id=? ORDER BY position",
                (iid,),
            )
        ]
        inners.append([iid, {"children": children, "relaxed": relaxed}])

    vectors = []
    for row in conn.execute(
        "SELECT vector_index, root_id, tail_id FROM vectors ORDER BY vector_index"
    ):
        vectors.append({"root": row[1], "tail": row[2]})

    named = {}
    for row in conn.execute("SELECT name, vector_index FROM named_vectors"):
        named[row[0]] = row[1]

    conn.close()

    return {
        "named_vectors": named,
        "pool": {
            "B": B,
            "BL": BL,
            "leaves": leaves,
            "inners": inners,
            "vectors": vectors,
        },
    }


# ── Build from operations ─────────────────────────────────────────────────


def build_from_ops(ops):
    B, BL = ops["B"], ops["BL"]
    vectors = {}
    for op in ops["operations"]:
        kind = op["op"]
        if kind == "create":
            vectors[op["name"]] = PersistentVector.from_elements(
                op["elements"], B, BL
            )
        elif kind == "push_back":
            vectors[op["name"]] = vectors[op["source"]].push_back(op["value"])
        elif kind == "set":
            vectors[op["name"]] = vectors[op["source"]].set(
                op["index"], op["value"]
            )
        elif kind == "copy":
            vectors[op["name"]] = vectors[op["source"]]
        else:
            raise ValueError(f"Unknown op: {kind}")
    return serialize_pools(vectors, B, BL)


# ── CLI ────────────────────────────────────────────────────────────────────


def main():
    p = argparse.ArgumentParser(description="RBT Pool Tool")
    sp = p.add_subparsers(dest="cmd")

    b = sp.add_parser("build")
    b.add_argument("operations")
    b.add_argument("-o", "--output")

    r = sp.add_parser("reconstruct")
    r.add_argument("pool")

    t = sp.add_parser("transform")
    t.add_argument("pool")
    t.add_argument("spec")
    t.add_argument("-o", "--output")

    v = sp.add_parser("validate")
    v.add_argument("pool")

    a = sp.add_parser("analyze")
    a.add_argument("pool")

    viz = sp.add_parser("visualize")
    viz.add_argument("pool")
    viz.add_argument("-o", "--output", required=True)

    st = sp.add_parser("store")
    st.add_argument("pool")
    st.add_argument("-o", "--output", required=True)

    ld = sp.add_parser("load")
    ld.add_argument("database")

    args = p.parse_args()

    def _write(data, path):
        txt = json.dumps(data, indent=2)
        if path:
            with open(path, "w") as f:
                f.write(txt)
        else:
            print(txt)

    if args.cmd == "build":
        with open(args.operations) as f:
            ops = json.load(f)
        _write(build_from_ops(ops), args.output)

    elif args.cmd == "reconstruct":
        with open(args.pool) as f:
            pool = json.load(f)
        print(json.dumps(deserialize_pool(pool), indent=2))

    elif args.cmd == "transform":
        with open(args.pool) as f:
            pool = json.load(f)
        with open(args.spec) as f:
            spec = json.load(f)
        _write(transform_pool(pool, spec), args.output)

    elif args.cmd == "validate":
        with open(args.pool) as f:
            pool = json.load(f)
        ok, errs = validate_pool(pool)
        if ok:
            print("VALID")
        else:
            print("INVALID")
            for e in errs:
                print(f"  - {e}")
            sys.exit(1)

    elif args.cmd == "analyze":
        with open(args.pool) as f:
            pool = json.load(f)
        print(json.dumps(analyze_pool(pool), indent=2))

    elif args.cmd == "visualize":
        with open(args.pool) as f:
            pool = json.load(f)
        visualize_pool(pool, args.output)

    elif args.cmd == "store":
        with open(args.pool) as f:
            pool = json.load(f)
        store_pool_to_db(pool, args.output)

    elif args.cmd == "load":
        loaded = load_pool_from_db(args.database)
        print(json.dumps(loaded, indent=2))

    else:
        p.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
