#!/usr/bin/env python3
"""
BSP Tree Compiler and Front-to-Back Traversal Engine.

Reads 2D map segments from JSON, builds a BSP tree by choosing splitting
lines from input segments, and answers front-to-back traversal queries.

"""

import json
import sys
import math

EPSILON = 1e-6


class Seg:
    _counter = 0

    def __init__(self, x1, y1, x2, y2, line_id):
        self.id = Seg._counter
        Seg._counter += 1
        self.x1 = float(x1)
        self.y1 = float(y1)
        self.x2 = float(x2)
        self.y2 = float(y2)
        self.line_id = line_id

    def to_dict(self):
        return {
            "id": self.id,
            "x1": self.x1, "y1": self.y1,
            "x2": self.x2, "y2": self.y2,
            "line_id": self.line_id
        }


def point_side(px, py, lx1, ly1, lx2, ly2):
    """Signed area: positive = front (left), negative = back (right)."""
    return (lx2 - lx1) * (py - ly1) - (ly2 - ly1) * (px - lx1)


def classify_seg(seg, splitter):
    """Classify seg relative to the line through splitter endpoints."""
    d1 = point_side(seg.x1, seg.y1,
                    splitter.x1, splitter.y1, splitter.x2, splitter.y2)
    d2 = point_side(seg.x2, seg.y2,
                    splitter.x1, splitter.y1, splitter.x2, splitter.y2)

    eps = EPSILON
    on1 = abs(d1) < eps
    on2 = abs(d2) < eps

    if on1 and on2:
        return "COLLINEAR"

    if on1:
        d1 = 0.0
    if on2:
        d2 = 0.0

    if d1 >= 0 and d2 >= 0:
        return "FRONT"
    if d1 <= 0 and d2 <= 0:
        return "BACK"
    return "SPANNING"


def split_seg(seg, splitter):
    """Split a spanning seg by the line through splitter. Returns (front, back)."""
    d1 = point_side(seg.x1, seg.y1,
                    splitter.x1, splitter.y1, splitter.x2, splitter.y2)
    d2 = point_side(seg.x2, seg.y2,
                    splitter.x1, splitter.y1, splitter.x2, splitter.y2)

    t = d1 / (d1 - d2)
    ix = seg.x1 + t * (seg.x2 - seg.x1)
    iy = seg.y1 + t * (seg.y2 - seg.y1)

    if d1 >= 0:
        front = Seg(seg.x1, seg.y1, ix, iy, seg.line_id)
        back = Seg(ix, iy, seg.x2, seg.y2, seg.line_id)
    else:
        front = Seg(ix, iy, seg.x2, seg.y2, seg.line_id)
        back = Seg(seg.x1, seg.y1, ix, iy, seg.line_id)

    return front, back


def segs_cross(s1, s2):
    """Check if two segments have a proper interior intersection."""
    d1 = point_side(s1.x1, s1.y1, s2.x1, s2.y1, s2.x2, s2.y2)
    d2 = point_side(s1.x2, s1.y2, s2.x1, s2.y1, s2.x2, s2.y2)
    d3 = point_side(s2.x1, s2.y1, s1.x1, s1.y1, s1.x2, s1.y2)
    d4 = point_side(s2.x2, s2.y2, s1.x1, s1.y1, s1.x2, s1.y2)
    return (d1 * d2 < 0) and (d3 * d4 < 0)


def choose_splitter(segs):
    """Choose the best splitting segment: minimize splits, then balance.

    Rejects candidates that place all other segments on the same side
    with zero splits, as those produce degenerate trees with no progress.
    """
    best_idx = None
    best_score = float("inf")

    for i, candidate in enumerate(segs):
        splits = 0
        front_count = 0
        back_count = 0

        for j, seg in enumerate(segs):
            if i == j:
                continue
            c = classify_seg(seg, candidate)
            if c == "SPANNING":
                splits += 1
            elif c in ("FRONT", "COLLINEAR"):
                front_count += 1
            else:
                back_count += 1

        # Reject degenerate candidates: no splits and all segs on one side
        if splits == 0 and (front_count == 0 or back_count == 0):
            continue

        score = splits * 8 + abs(front_count - back_count)
        if score < best_score:
            best_score = score
            best_idx = i

    # Fallback: pick any seg that causes at least one split
    if best_idx is None:
        for i, candidate in enumerate(segs):
            for j, seg in enumerate(segs):
                if i != j and classify_seg(seg, candidate) == "SPANNING":
                    return i
        return 0

    return best_idx


def build_bsp(segs, depth=0):
    """Recursively build a BSP tree from a list of Seg objects."""
    if not segs:
        return {"type": "leaf", "segs": []}

    if depth > 64:
        return {"type": "leaf", "segs": [s.to_dict() for s in segs]}

    # Check if any pair of segments crosses
    needs_split = False
    for i in range(len(segs)):
        if needs_split:
            break
        for j in range(i + 1, len(segs)):
            if segs_cross(segs[i], segs[j]):
                needs_split = True
                break

    if not needs_split:
        return {"type": "leaf", "segs": [s.to_dict() for s in segs]}

    splitter_idx = choose_splitter(segs)
    splitter = segs[splitter_idx]

    front_segs = []
    back_segs = []

    for seg in segs:
        c = classify_seg(seg, splitter)
        if c in ("FRONT", "COLLINEAR"):
            front_segs.append(seg)
        elif c == "BACK":
            back_segs.append(seg)
        else:
            f, b = split_seg(seg, splitter)
            front_segs.append(f)
            back_segs.append(b)

    return {
        "type": "node",
        "split": {
            "x1": splitter.x1, "y1": splitter.y1,
            "x2": splitter.x2, "y2": splitter.y2
        },
        "front": build_bsp(front_segs, depth + 1),
        "back": build_bsp(back_segs, depth + 1)
    }


def traverse_bsp(node, vx, vy):
    """Front-to-back traversal: visit the viewpoint's side first."""
    if node["type"] == "leaf":
        return list(node["segs"])

    side = point_side(vx, vy,
                      node["split"]["x1"], node["split"]["y1"],
                      node["split"]["x2"], node["split"]["y2"])

    if side >= 0:
        result = traverse_bsp(node["front"], vx, vy)
        result.extend(traverse_bsp(node["back"], vx, vy))
    else:
        result = traverse_bsp(node["back"], vx, vy)
        result.extend(traverse_bsp(node["front"], vx, vy))

    return result


def count_stats(node):
    """Compute BSP tree statistics."""
    if node["type"] == "leaf":
        return {
            "num_nodes": 0,
            "num_leaves": 1,
            "num_segs": len(node["segs"]),
            "max_depth": 0
        }

    f = count_stats(node["front"])
    b = count_stats(node["back"])

    return {
        "num_nodes": 1 + f["num_nodes"] + b["num_nodes"],
        "num_leaves": f["num_leaves"] + b["num_leaves"],
        "num_segs": f["num_segs"] + b["num_segs"],
        "max_depth": 1 + max(f["max_depth"], b["max_depth"])
    }


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <input.json> <output.json>", file=sys.stderr)
        sys.exit(1)

    with open(sys.argv[1]) as f:
        data = json.load(f)

    Seg._counter = 0

    segs = []
    for s in data["segments"]:
        segs.append(Seg(s["x1"], s["y1"], s["x2"], s["y2"], s["id"]))

    bsp = build_bsp(segs)
    stats = count_stats(bsp)

    query_results = []
    for q in data["queries"]:
        vx, vy = q["x"], q["y"]
        seg_order = traverse_bsp(bsp, vx, vy)
        query_results.append({
            "viewpoint": {"x": vx, "y": vy},
            "seg_order": seg_order
        })

    result = {
        "bsp": bsp,
        "stats": stats,
        "query_results": query_results
    }

    with open(sys.argv[2], "w") as f:
        json.dump(result, f, indent=2)

    print(f"BSP: {stats['num_nodes']} nodes, {stats['num_leaves']} leaves, "
          f"{stats['num_segs']} segs, depth {stats['max_depth']}", file=sys.stderr)


if __name__ == "__main__":
    main()
