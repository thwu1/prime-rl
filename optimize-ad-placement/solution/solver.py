#!/usr/bin/env python3
"""
Rectangle packing solver: multi-start weighted KD-tree partition with
iterative coordinate-descent boundary refinement.

Builds several KD-trees using different axis-selection strategies
(spread-based, region-based, randomized). Each tree is refined via
multi-pass bottom-up coordinate descent on split positions. The tree
with the highest total satisfaction is selected.
"""

import sys
import random as rng_mod


def read_input():
    data = sys.stdin.read().strip().split('\n')
    n = int(data[0])
    cos = []
    for i in range(1, n + 1):
        x, y, r = map(int, data[i].split())
        cos.append((x, y, r))
    return n, cos


class Leaf:
    __slots__ = ['idx']
    def __init__(self, idx):
        self.idx = idx


class Split:
    __slots__ = ['axis', 'pos', 'left', 'right', 'lo_bound', 'hi_bound']
    def __init__(self, axis, pos, left, right, lo_bound, hi_bound):
        self.axis = axis
        self.pos = pos
        self.left = left
        self.right = right
        self.lo_bound = lo_bound
        self.hi_bound = hi_bound


def build_tree(items, x1, y1, x2, y2, strategy='spread', rng=None):
    """Build weighted KD-tree with configurable axis selection."""
    if len(items) <= 1:
        return Leaf(items[0][0]) if items else None

    w, h = x2 - x1, y2 - y1
    total_r = sum(it[3] for it in items) or len(items)

    x_spread = max(it[1] for it in items) - min(it[1] for it in items)
    y_spread = max(it[2] for it in items) - min(it[2] for it in items)

    if strategy == 'spread':
        if x_spread > y_spread:
            axes = [0, 1]
        elif y_spread > x_spread:
            axes = [1, 0]
        elif w >= h:
            axes = [0, 1]
        else:
            axes = [1, 0]
    elif strategy == 'region':
        axes = [0, 1] if w >= h else [1, 0]
    elif strategy == 'random':
        if rng and rng.random() < 0.5:
            axes = [0, 1]
        else:
            axes = [1, 0]
    else:
        axes = [0, 1] if w >= h else [1, 0]

    for axis in axes:
        ci = 1 + axis
        dim = w if axis == 0 else h
        if dim < 2:
            continue

        sorted_items = sorted(items, key=lambda it: it[ci])

        # Find best separable split index
        cum = 0
        best_k = None
        best_diff = float('inf')
        for i in range(len(sorted_items) - 1):
            cum += sorted_items[i][3]
            if sorted_items[i][ci] < sorted_items[i + 1][ci]:
                diff = abs(2 * cum - total_r)
                if diff < best_diff:
                    best_diff = diff
                    best_k = i + 1

        if best_k is None:
            continue

        left_items = sorted_items[:best_k]
        right_items = sorted_items[best_k:]

        lo_bound = left_items[-1][ci] + 1
        hi_bound = right_items[0][ci]

        lo = x1 if axis == 0 else y1
        hi = x2 if axis == 0 else y2
        left_r = sum(it[3] for it in left_items)
        ideal = lo + max(1, round((hi - lo) * left_r / total_r))
        pos = max(lo_bound, min(hi_bound, ideal))
        pos = max(lo + 1, min(hi - 1, pos))

        if axis == 0:
            ln = build_tree(left_items, x1, y1, pos, y2, strategy, rng)
            rn = build_tree(right_items, pos, y1, x2, y2, strategy, rng)
        else:
            ln = build_tree(left_items, x1, y1, x2, pos, strategy, rng)
            rn = build_tree(right_items, x1, pos, x2, y2, strategy, rng)

        return Split(axis, pos, ln, rn, lo_bound, hi_bound)

    return Leaf(items[0][0])


def subtree_satisfaction(node, x1, y1, x2, y2, cos):
    if node is None:
        return 0.0
    if isinstance(node, Leaf):
        x, y, r = cos[node.idx]
        if x1 <= x and x + 1 <= x2 and y1 <= y and y + 1 <= y2:
            s = (x2 - x1) * (y2 - y1)
            ratio = min(r, s) / max(r, s) if s > 0 else 0
            return 1.0 - (1.0 - ratio) ** 2
        return 0.0
    if node.axis == 0:
        return (subtree_satisfaction(node.left, x1, y1, node.pos, y2, cos) +
                subtree_satisfaction(node.right, node.pos, y1, x2, y2, cos))
    return (subtree_satisfaction(node.left, x1, y1, x2, node.pos, cos) +
            subtree_satisfaction(node.right, x1, node.pos, x2, y2, cos))


def refine_pass(node, x1, y1, x2, y2, cos):
    if isinstance(node, Leaf) or node is None:
        return 0.0

    if node.axis == 0:
        imp = refine_pass(node.left, x1, y1, node.pos, y2, cos)
        imp += refine_pass(node.right, node.pos, y1, x2, y2, cos)
    else:
        imp = refine_pass(node.left, x1, y1, x2, node.pos, cos)
        imp += refine_pass(node.right, x1, node.pos, x2, y2, cos)

    lo = x1 if node.axis == 0 else y1
    hi = x2 if node.axis == 0 else y2
    mn = max(node.lo_bound, lo + 1)
    mx = min(node.hi_bound, hi - 1)
    if mn > mx:
        return imp

    cur = subtree_satisfaction(node, x1, y1, x2, y2, cos)

    rng = mx - mn + 1
    if rng <= 200:
        cands = list(range(mn, mx + 1))
    else:
        step = max(1, rng // 200)
        cands = sorted(set(
            list(range(mn, mx + 1, step)) + [mn, mx, node.pos]
        ))

    bp, bs = node.pos, cur
    for p in cands:
        node.pos = p
        s = subtree_satisfaction(node, x1, y1, x2, y2, cos)
        if s > bs:
            bs, bp = s, p
    node.pos = bp
    return imp + max(0.0, bs - cur)


def extract_rects(node, x1, y1, x2, y2, out):
    if node is None:
        return
    if isinstance(node, Leaf):
        out[node.idx] = (x1, y1, x2, y2)
        return
    if node.axis == 0:
        extract_rects(node.left, x1, y1, node.pos, y2, out)
        extract_rects(node.right, node.pos, y1, x2, y2, out)
    else:
        extract_rects(node.left, x1, y1, x2, node.pos, out)
        extract_rects(node.right, x1, node.pos, x2, y2, out)


def solve_with_strategy(items, cos, strategy, seed=0):
    """Build tree, refine, return (root, score)."""
    rng = rng_mod.Random(seed) if strategy == 'random' else None
    root = build_tree(items, 0, 0, 10000, 10000, strategy, rng)
    for _ in range(15):
        if refine_pass(root, 0, 0, 10000, 10000, cos) < 1e-7:
            break
    score = subtree_satisfaction(root, 0, 0, 10000, 10000, cos)
    return root, score


def main():
    n, cos = read_input()
    items = [(i, cos[i][0], cos[i][1], cos[i][2]) for i in range(n)]

    # Multi-start: try different tree construction strategies
    strategies = [
        ('spread', 0),
        ('region', 0),
        ('random', 1),
        ('random', 2),
        ('random', 3),
    ]

    best_root = None
    best_score = -1.0

    for strategy, seed in strategies:
        root, score = solve_with_strategy(items, cos, strategy, seed)
        if score > best_score:
            best_score = score
            best_root = root

    rects = {}
    extract_rects(best_root, 0, 0, 10000, 10000, rects)
    lines = [''] * n
    for idx, r in rects.items():
        lines[idx] = f'{r[0]} {r[1]} {r[2]} {r[3]}'
    sys.stdout.write('\n'.join(lines) + '\n')


if __name__ == '__main__':
    main()
