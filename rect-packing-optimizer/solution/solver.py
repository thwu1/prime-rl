#!/usr/bin/env python3
"""

Rectangle Ad Placement solver.

Algorithm:
1. Recursive area-proportional spatial partition (kd-tree style) for initial layout
2. Simulated annealing to refine boundary positions
3. Greedy expansion pass for undersize rectangles
"""
import math
import random
import sys
import time

# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------

def read_input():
    data = sys.stdin.buffer.read().split()
    ptr = 0
    n = int(data[ptr]); ptr += 1
    xs = [0] * n
    ys = [0] * n
    rs = [0] * n
    for i in range(n):
        xs[i] = int(data[ptr]); ptr += 1
        ys[i] = int(data[ptr]); ptr += 1
        rs[i] = int(data[ptr]); ptr += 1
    return n, xs, ys, rs


# ---------------------------------------------------------------------------
# Satisfaction helper
# ---------------------------------------------------------------------------

def _sat(r, s):
    """Satisfaction when point IS contained, given desired area r and actual s."""
    ratio = min(r, s) / max(r, s)
    return 1.0 - (1.0 - ratio) ** 2


# ---------------------------------------------------------------------------
# Phase 1: Recursive area-proportional partition
# ---------------------------------------------------------------------------

def initial_partition(n, xs, ys, rs):
    rects = [None] * n  # (a, b, c, d) per company
    _partition(xs, ys, rs, list(range(n)), 0, 0, 10000, 10000, rects)
    return rects


def _partition(xs, ys, rs, indices, x1, y1, x2, y2, rects):
    k = len(indices)
    if k == 0:
        return
    if k == 1:
        rects[indices[0]] = [x1, y1, x2, y2]
        return

    total_r = sum(rs[i] for i in indices)

    # Try both split directions; pick the one with lowest cost
    best = None  # (cost, use_x, split_k, split_s, sorted_indices)

    for use_x in (True, False):
        if use_x:
            sorted_idx = sorted(indices, key=lambda i: (xs[i], ys[i]))
        else:
            sorted_idx = sorted(indices, key=lambda i: (ys[i], xs[i]))

        running_r = 0
        for kk in range(1, k):
            running_r += rs[sorted_idx[kk - 1]]

            if use_x:
                left_c = xs[sorted_idx[kk - 1]]
                right_c = xs[sorted_idx[kk]]
            else:
                left_c = ys[sorted_idx[kk - 1]]
                right_c = ys[sorted_idx[kk]]

            if left_c >= right_c:
                continue  # same coordinate — can't split here

            area_ratio = running_r / total_r

            if use_x:
                ideal = x1 + area_ratio * (x2 - x1)
                lo = max(x1 + 1, left_c + 1)
                hi = min(x2 - 1, right_c)
            else:
                ideal = y1 + area_ratio * (y2 - y1)
                lo = max(y1 + 1, left_c + 1)
                hi = min(y2 - 1, right_c)

            if lo > hi:
                continue

            s = max(lo, min(int(round(ideal)), hi))

            if use_x:
                actual_ratio = (s - x1) / (x2 - x1)
            else:
                actual_ratio = (s - y1) / (y2 - y1)

            cost = (area_ratio - actual_ratio) ** 2

            if best is None or cost < best[0]:
                best = (cost, use_x, kk, s, list(sorted_idx))

    if best is None:
        # Fallback: split in half along longer dimension
        mid = k // 2
        use_x = (x2 - x1) >= (y2 - y1)
        if use_x:
            sorted_idx = sorted(indices, key=lambda i: (xs[i], ys[i]))
        else:
            sorted_idx = sorted(indices, key=lambda i: (ys[i], xs[i]))
        s_val = ((x1 + x2) // 2) if use_x else ((y1 + y2) // 2)
        s_val = max((x1 if use_x else y1) + 1,
                    min(s_val, (x2 if use_x else y2) - 1))
        if use_x:
            _partition(xs, ys, rs, sorted_idx[:mid], x1, y1, s_val, y2, rects)
            _partition(xs, ys, rs, sorted_idx[mid:], s_val, y1, x2, y2, rects)
        else:
            _partition(xs, ys, rs, sorted_idx[:mid], x1, y1, x2, s_val, rects)
            _partition(xs, ys, rs, sorted_idx[mid:], x1, s_val, x2, y2, rects)
        return

    _, use_x, split_k, split_s, sorted_idx = best
    left = sorted_idx[:split_k]
    right = sorted_idx[split_k:]

    if use_x:
        _partition(xs, ys, rs, left, x1, y1, split_s, y2, rects)
        _partition(xs, ys, rs, right, split_s, y1, x2, y2, rects)
    else:
        _partition(xs, ys, rs, left, x1, y1, x2, split_s, rects)
        _partition(xs, ys, rs, right, x1, split_s, x2, y2, rects)


# ---------------------------------------------------------------------------
# Phase 2: Simulated annealing
# ---------------------------------------------------------------------------

def sa_refine(n, xs, ys, rs, rects, time_limit=7.0):
    rng = random.Random(12345)
    t0 = time.monotonic()

    # Precompute current satisfactions
    sats = [0.0] * n
    for i in range(n):
        a, b, c, d = rects[i]
        if a <= xs[i] and c >= xs[i] + 1 and b <= ys[i] and d >= ys[i] + 1:
            sats[i] = _sat(rs[i], (c - a) * (d - b))

    best_rects = [r[:] for r in rects]
    best_total = sum(sats)
    current_total = best_total

    iters = 0
    check_interval = 200

    while True:
        iters += 1
        if iters % check_interval == 0:
            elapsed = time.monotonic() - t0
            if elapsed >= time_limit:
                break
            progress = elapsed / time_limit
        else:
            progress = min(1.0, (time.monotonic() - t0) / time_limit)

        i = rng.randint(0, n - 1)
        a, b, c, d = rects[i]

        max_delta = max(2, int(300 * (1.0 - progress) + 5))
        bnd = rng.randint(0, 3)
        delta = rng.randint(1, max_delta)
        if rng.random() < 0.5:
            delta = -delta

        na, nb, nc, nd = a, b, c, d
        if bnd == 0:
            na += delta
        elif bnd == 1:
            nb += delta
        elif bnd == 2:
            nc += delta
        else:
            nd += delta

        # Quick validity checks
        if na >= nc or nb >= nd:
            continue
        if na < 0 or nb < 0 or nc > 10000 or nd > 10000:
            continue
        # Containment
        xi, yi = xs[i], ys[i]
        if na > xi or nc < xi + 1 or nb > yi or nd < yi + 1:
            continue

        # Overlap check
        overlap = False
        for j in range(n):
            if j == i:
                continue
            aj, bj, cj, dj = rects[j]
            if na < cj and nc > aj and nb < dj and nd > bj:
                overlap = True
                break
        if overlap:
            continue

        # Evaluate
        new_s = _sat(rs[i], (nc - na) * (nd - nb))
        ds = new_s - sats[i]

        T = 0.08 * max(0.001, 1.0 - progress)
        if ds >= 0 or rng.random() < math.exp(ds / max(T, 1e-12)):
            rects[i] = [na, nb, nc, nd]
            sats[i] = new_s
            current_total += ds
            if current_total > best_total:
                best_total = current_total
                best_rects = [r[:] for r in rects]

    # Restore best
    for i in range(n):
        rects[i] = best_rects[i]
    return rects


# ---------------------------------------------------------------------------
# Phase 3: Greedy expansion for undersize rectangles
# ---------------------------------------------------------------------------

def greedy_expand(n, xs, ys, rs, rects):
    """Expand rectangles that are too small into free space."""
    # Sort by area deficit (most deficit first)
    order = sorted(range(n), key=lambda i: rs[i] / max(1, (rects[i][2] - rects[i][0]) * (rects[i][3] - rects[i][1])), reverse=True)

    for i in order:
        a, b, c, d = rects[i]
        s = (c - a) * (d - b)
        if s >= rs[i]:
            continue  # already has enough area

        # Try all 4 directions
        for direction in range(4):
            a, b, c, d = rects[i]
            s = (c - a) * (d - b)
            if s >= rs[i]:
                break

            if direction == 0:  # expand right
                limit = 10000
                for j in range(n):
                    if j == i:
                        continue
                    aj, bj, cj, dj = rects[j]
                    if aj >= c and b < dj and d > bj:
                        limit = min(limit, aj)
                if limit <= c:
                    continue
                # Expand to match target area (or to limit)
                needed = (rs[i] - s + (d - b) - 1) // (d - b)
                new_c = min(limit, c + max(1, needed))
                new_s = (new_c - a) * (d - b)
                if min(rs[i], new_s) / max(rs[i], new_s) > min(rs[i], s) / max(rs[i], s):
                    rects[i] = [a, b, new_c, d]

            elif direction == 1:  # expand down
                limit = 10000
                for j in range(n):
                    if j == i:
                        continue
                    aj, bj, cj, dj = rects[j]
                    if bj >= d and a < cj and c > aj:
                        limit = min(limit, bj)
                if limit <= d:
                    continue
                needed = (rs[i] - s + (c - a) - 1) // (c - a)
                new_d = min(limit, d + max(1, needed))
                new_s = (c - a) * (new_d - b)
                if min(rs[i], new_s) / max(rs[i], new_s) > min(rs[i], s) / max(rs[i], s):
                    rects[i] = [a, b, c, new_d]

            elif direction == 2:  # expand left
                limit = 0
                for j in range(n):
                    if j == i:
                        continue
                    aj, bj, cj, dj = rects[j]
                    if cj <= a and b < dj and d > bj:
                        limit = max(limit, cj)
                if limit >= a:
                    continue
                needed = (rs[i] - s + (d - b) - 1) // (d - b)
                new_a = max(limit, a - max(1, needed))
                if new_a > xs[i]:
                    new_a = min(new_a, xs[i])
                new_s = (c - new_a) * (d - b)
                if new_a < a and min(rs[i], new_s) / max(rs[i], new_s) > min(rs[i], s) / max(rs[i], s):
                    rects[i] = [new_a, b, c, d]

            else:  # expand up
                limit = 0
                for j in range(n):
                    if j == i:
                        continue
                    aj, bj, cj, dj = rects[j]
                    if dj <= b and a < cj and c > aj:
                        limit = max(limit, dj)
                if limit >= b:
                    continue
                needed = (rs[i] - s + (c - a) - 1) // (c - a)
                new_b = max(limit, b - max(1, needed))
                if new_b > ys[i]:
                    new_b = min(new_b, ys[i])
                new_s = (c - a) * (d - new_b)
                if new_b < b and min(rs[i], new_s) / max(rs[i], new_s) > min(rs[i], s) / max(rs[i], s):
                    rects[i] = [a, new_b, c, d]

    return rects


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    sys.setrecursionlimit(10000)
    n, xs, ys, rs = read_input()

    rects = initial_partition(n, xs, ys, rs)
    rects = sa_refine(n, xs, ys, rs, rects, time_limit=7.0)
    rects = greedy_expand(n, xs, ys, rs, rects)

    out_lines = []
    for i in range(n):
        a, b, c, d = rects[i]
        out_lines.append(f"{a} {b} {c} {d}")
    sys.stdout.write("\n".join(out_lines) + "\n")


if __name__ == "__main__":
    main()
