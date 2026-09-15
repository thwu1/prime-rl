#!/usr/bin/env python3
"""
Persistent Vector Pool Engine — reference solution.

Operates on pool-serialized persistent vectors stored as radix balanced trees
with structural sharing and tail optimization.
"""


import argparse
import json
import sys


class Pool:
    """Parsed pool with lookup dicts for leaves and inner nodes."""

    def __init__(self, data):
        self.B = data["B"]
        self.BL = data["BL"]
        self.branch = 1 << self.B          # M = 2^B
        self.leaf_cap = 1 << self.BL       # L = 2^BL
        self.leaves = {e[0]: e[1] for e in data["leaves"]}
        self.inners = {e[0]: e[1] for e in data["inners"]}
        self.vectors = data["vectors"]
        self.raw = data

    @classmethod
    def from_file(cls, path):
        with open(path) as f:
            return cls(json.load(f))

    # ------------------------------------------------------------------
    # depth helpers
    # ------------------------------------------------------------------

    def _tail_count(self, size):
        """Number of elements stored in the tail leaf."""
        if size == 0:
            return 0
        if size <= self.leaf_cap:
            return size
        r = size % self.leaf_cap
        return r if r != 0 else self.leaf_cap

    def _body_depth(self, size):
        """Tree depth for the body (smallest d >= 1 with M^d >= num_body_leaves)."""
        tc = self._tail_count(size)
        bc = size - tc
        nl = bc // self.leaf_cap
        if nl <= 0:
            return 0
        if nl <= 1:
            return 1
        d, cap = 1, self.branch
        while cap < nl:
            cap *= self.branch
            d += 1
        return d

    # ------------------------------------------------------------------
    # tree traversal
    # ------------------------------------------------------------------

    def _traverse(self, node_id, depth):
        """Collect elements left-to-right from a subtree rooted at an inner node."""
        inner = self.inners[node_id]
        elements = []
        for cid in inner["children"]:
            if depth == 1:
                elements.extend(self.leaves[cid])
            else:
                elements.extend(self._traverse(cid, depth - 1))
        return elements

    def _subtree_count(self, node_id, depth):
        """Count elements in a subtree."""
        inner = self.inners[node_id]
        total = 0
        for cid in inner["children"]:
            if depth == 1:
                total += len(self.leaves[cid])
            else:
                total += self._subtree_count(cid, depth - 1)
        return total

    # ------------------------------------------------------------------
    # reconstruct
    # ------------------------------------------------------------------

    def reconstruct_vector(self, vec):
        size = vec["size"]
        if size == 0:
            return []
        tail = list(self.leaves[vec["tail"]]) if vec["tail"] is not None else []
        if vec["root"] is None:
            return tail[:size]
        depth = self._body_depth(size)
        body = self._traverse(vec["root"], depth)
        return body + tail

    def reconstruct_all(self):
        return [self.reconstruct_vector(v) for v in self.vectors]

    # ------------------------------------------------------------------
    # sharing
    # ------------------------------------------------------------------

    def _collect_nodes(self, vec):
        """Return (leaf_ids, inner_ids) transitively reachable from a vector."""
        lids, iids = set(), set()
        if vec["size"] == 0:
            return lids, iids
        if vec["tail"] is not None:
            lids.add(vec["tail"])
        if vec["root"] is None:
            return lids, iids

        depth = self._body_depth(vec["size"])

        def walk(nid, d):
            iids.add(nid)
            for cid in self.inners[nid]["children"]:
                if d == 1:
                    lids.add(cid)
                else:
                    walk(cid, d - 1)

        walk(vec["root"], depth)
        return lids, iids

    def sharing_analysis(self):
        leaf_map, inner_map = {}, {}
        for idx, vec in enumerate(self.vectors):
            lids, iids = self._collect_nodes(vec)
            for lid in lids:
                leaf_map.setdefault(str(lid), []).append(idx)
            for iid in iids:
                inner_map.setdefault(str(iid), []).append(idx)
        return {"leaves": leaf_map, "inners": inner_map}

    # ------------------------------------------------------------------
    # transform
    # ------------------------------------------------------------------

    def transform(self, expr, output_path):
        new_leaves = []
        for entry in self.raw["leaves"]:
            lid, vals = entry[0], entry[1]
            new_vals = [eval(expr, {"x": v, "__builtins__": {}}) for v in vals]
            new_leaves.append([lid, new_vals])
        out = {
            "B": self.raw["B"],
            "BL": self.raw["BL"],
            "leaves": new_leaves,
            "inners": self.raw["inners"],
            "vectors": self.raw["vectors"],
        }
        with open(output_path, "w") as f:
            json.dump(out, f, indent=2)

    # ------------------------------------------------------------------
    # diff
    # ------------------------------------------------------------------

    def diff(self, idx1, idx2):
        v1, v2 = self.vectors[idx1], self.vectors[idx2]
        assert v1["size"] == v2["size"], "diff requires same-size vectors"
        size = v1["size"]
        changes = []
        compared = [0]
        skipped = [0]

        if size == 0:
            return {
                "changes": [],
                "stats": {
                    "elements_compared": 0,
                    "elements_skipped": 0,
                    "total_elements": 0,
                },
            }

        def diff_leaf(lid1, lid2, base):
            if lid1 == lid2:
                skipped[0] += len(self.leaves[lid1])
                return
            for i, (a, b) in enumerate(zip(self.leaves[lid1], self.leaves[lid2])):
                compared[0] += 1
                if a != b:
                    changes.append({"index": base + i, "old": a, "new": b})

        def diff_inner(nid1, nid2, depth, base):
            if nid1 == nid2:
                skipped[0] += self._subtree_count(nid1, depth)
                return
            c1 = self.inners[nid1]["children"]
            c2 = self.inners[nid2]["children"]
            offset = base
            for a, b in zip(c1, c2):
                if depth == 1:
                    diff_leaf(a, b, offset)
                    offset += len(self.leaves[a])
                else:
                    child_count = self._subtree_count(a, depth - 1)
                    diff_inner(a, b, depth - 1, offset)
                    offset += child_count

        depth = self._body_depth(size)
        tc = self._tail_count(size)
        bc = size - tc

        if v1["root"] is not None and v2["root"] is not None:
            diff_inner(v1["root"], v2["root"], depth, 0)

        if v1["tail"] is not None and v2["tail"] is not None:
            diff_leaf(v1["tail"], v2["tail"], bc)

        return {
            "changes": changes,
            "stats": {
                "elements_compared": compared[0],
                "elements_skipped": skipped[0],
                "total_elements": size,
            },
        }

    # ------------------------------------------------------------------
    # depth assignment (for merge)
    # ------------------------------------------------------------------

    def _assign_depths(self):
        """Assign depth to each inner node by tracing from vector roots."""
        depths = {}
        for vec in self.vectors:
            if vec["root"] is None:
                continue
            d = self._body_depth(vec["size"])
            self._trace_depth(vec["root"], d, depths)
        return depths

    def _trace_depth(self, nid, depth, depths):
        if nid in depths:
            return
        depths[nid] = depth
        if depth > 1:
            for cid in self.inners[nid]["children"]:
                self._trace_depth(cid, depth - 1, depths)


def merge_pools(pool1, pool2, output_path):
    """Merge two pools, deduplicating structurally identical subtrees."""
    assert pool1.B == pool2.B and pool1.BL == pool2.BL, \
        "Cannot merge pools with different encoding parameters"

    depths1 = pool1._assign_depths()
    depths2 = pool2._assign_depths()

    # --- Step 1: Canonicalize leaves by content ---
    leaf_content_map = {}   # tuple(values) -> canonical_id
    canonical_leaves = []   # [[id, values], ...]
    next_leaf_id = [0]
    leaf_remap1 = {}        # pool1 original_id -> canonical_id
    leaf_remap2 = {}        # pool2 original_id -> canonical_id

    def canon_leaves(pool, remap):
        for entry in pool.raw["leaves"]:
            orig_id, vals = entry[0], entry[1]
            key = tuple(vals)
            if key not in leaf_content_map:
                cid = next_leaf_id[0]
                next_leaf_id[0] += 1
                leaf_content_map[key] = cid
                canonical_leaves.append([cid, list(vals)])
            remap[orig_id] = leaf_content_map[key]

    canon_leaves(pool1, leaf_remap1)
    canon_leaves(pool2, leaf_remap2)

    # --- Step 2: Canonicalize inners bottom-up by depth ---
    max_depth = max(
        max(depths1.values()) if depths1 else 0,
        max(depths2.values()) if depths2 else 0,
        0,
    )

    # Key: (depth, tuple_of_canonical_children) -> canonical_inner_id
    # Using depth in key prevents conflation of nodes at different tree levels
    inner_content_map = {}
    canonical_inners = []
    next_inner_id = [0]
    inner_remap1 = {}
    inner_remap2 = {}

    def canon_inners_at_depth(pool, depths, leaf_remap, inner_remap, depth):
        for entry in pool.raw["inners"]:
            nid = entry[0]
            if nid not in depths or depths[nid] != depth:
                continue
            children = entry[1]["children"]
            if depth == 1:
                cc = tuple(leaf_remap[c] for c in children)
            else:
                cc = tuple(inner_remap[c] for c in children)
            key = (depth, cc)
            if key not in inner_content_map:
                cid = next_inner_id[0]
                next_inner_id[0] += 1
                inner_content_map[key] = cid
                canonical_inners.append(
                    [cid, {"children": list(cc), "relaxed": False}]
                )
            inner_remap[nid] = inner_content_map[key]

    for d in range(1, max_depth + 1):
        canon_inners_at_depth(pool1, depths1, leaf_remap1, inner_remap1, d)
        canon_inners_at_depth(pool2, depths2, leaf_remap2, inner_remap2, d)

    # --- Step 3: Build merged vectors ---
    vectors = []
    for vec in pool1.vectors:
        root = inner_remap1[vec["root"]] if vec["root"] is not None else None
        tail = leaf_remap1[vec["tail"]] if vec["tail"] is not None else None
        vectors.append({"root": root, "tail": tail, "size": vec["size"]})
    for vec in pool2.vectors:
        root = inner_remap2[vec["root"]] if vec["root"] is not None else None
        tail = leaf_remap2[vec["tail"]] if vec["tail"] is not None else None
        vectors.append({"root": root, "tail": tail, "size": vec["size"]})

    out = {
        "B": pool1.B,
        "BL": pool1.BL,
        "leaves": canonical_leaves,
        "inners": canonical_inners,
        "vectors": vectors,
    }
    with open(output_path, "w") as f:
        json.dump(out, f, indent=2)


def main():
    parser = argparse.ArgumentParser(description="Persistent Vector Pool Engine")
    sub = parser.add_subparsers(dest="command", required=True)

    p_recon = sub.add_parser("reconstruct")
    p_recon.add_argument("pool_file")

    p_share = sub.add_parser("sharing")
    p_share.add_argument("pool_file")

    p_trans = sub.add_parser("transform")
    p_trans.add_argument("pool_file")
    p_trans.add_argument("expr")
    p_trans.add_argument("-o", "--output", required=True)

    p_diff = sub.add_parser("diff")
    p_diff.add_argument("pool_file")
    p_diff.add_argument("idx1", type=int)
    p_diff.add_argument("idx2", type=int)

    p_merge = sub.add_parser("merge")
    p_merge.add_argument("pool_file1")
    p_merge.add_argument("pool_file2")
    p_merge.add_argument("-o", "--output", required=True)

    args = parser.parse_args()

    if args.command == "reconstruct":
        pool = Pool.from_file(args.pool_file)
        print(json.dumps(pool.reconstruct_all()))
    elif args.command == "sharing":
        pool = Pool.from_file(args.pool_file)
        print(json.dumps(pool.sharing_analysis()))
    elif args.command == "transform":
        pool = Pool.from_file(args.pool_file)
        pool.transform(args.expr, args.output)
    elif args.command == "diff":
        pool = Pool.from_file(args.pool_file)
        print(json.dumps(pool.diff(args.idx1, args.idx2)))
    elif args.command == "merge":
        pool1 = Pool.from_file(args.pool_file1)
        pool2 = Pool.from_file(args.pool_file2)
        merge_pools(pool1, pool2, args.output)


if __name__ == "__main__":
    main()
