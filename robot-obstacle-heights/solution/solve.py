#!/usr/bin/env python3
"""

Efficient solver for Robot Obstacle Navigation.

Uses an offline sweep-line with a segment tree supporting lazy propagation
to achieve O((n+q) log n) per suite.

Key insight: achievable robot heights after any contiguous subsequence of
obstacles always form a range [0, M]. This reduces the problem to tracking
a single value M with the update rule:
  - If M < a:       M unchanged  (robot too short)
  - If a <= M < 2a: M = a - 1    (all colliding heights map to [0, a-1])
  - If M >= 2a:     M = M - a    (enough headroom to preserve range width)

For large n and q (up to 10^5), the naive O(nq) simulation is infeasible.
Instead, process queries offline sorted by right endpoint r. Maintain a
segment tree where position l stores M(l, current_r). As r advances, the
M values are non-decreasing in l, enabling efficient boundary-finding via
segment tree descent.
"""
import sqlite3
import json
import sys
from collections import defaultdict


class SegTree:
    """Segment tree with range-set, range-add, max queries, and
    leftmost-position-with-value-ge-threshold descent."""
    __slots__ = ('sz', 'mx', 'lt', 'lv')

    def __init__(self, n):
        self.sz = 1
        while self.sz < n:
            self.sz <<= 1
        s = 2 * self.sz
        self.mx = [0] * s
        self.lt = [0] * s   # 0=none, 1=set, 2=add
        self.lv = [0] * s

    def _ap(self, x, t, v):
        if t == 1:
            self.mx[x] = v
            self.lt[x] = 1
            self.lv[x] = v
        elif t == 2:
            self.mx[x] += v
            if self.lt[x] == 0:
                self.lt[x] = 2
                self.lv[x] = v
            else:
                self.lv[x] += v

    def _pd(self, x):
        t = self.lt[x]
        if t:
            v = self.lv[x]
            x2 = x << 1
            self._ap(x2, t, v)
            self._ap(x2 | 1, t, v)
            self.lt[x] = 0
            self.lv[x] = 0

    def _upd(self, x, lo, hi, ql, qr, t, v):
        if qr < lo or hi < ql:
            return
        if ql <= lo and hi <= qr:
            self._ap(x, t, v)
            return
        self._pd(x)
        mid = (lo + hi) >> 1
        x2 = x << 1
        self._upd(x2, lo, mid, ql, qr, t, v)
        self._upd(x2 | 1, mid + 1, hi, ql, qr, t, v)
        self.mx[x] = max(self.mx[x2], self.mx[x2 | 1])

    def _qry(self, x, lo, hi, p):
        if lo == hi:
            return self.mx[x]
        self._pd(x)
        mid = (lo + hi) >> 1
        if p <= mid:
            return self._qry(x << 1, lo, mid, p)
        return self._qry(x << 1 | 1, mid + 1, hi, p)

    def _fge(self, x, lo, hi, ql, qr, thr):
        """Find leftmost position in [ql, qr] with value >= thr."""
        if qr < lo or hi < ql or self.mx[x] < thr:
            return -1
        if lo == hi:
            return lo
        self._pd(x)
        mid = (lo + hi) >> 1
        x2 = x << 1
        r = self._fge(x2, lo, mid, ql, qr, thr)
        if r != -1:
            return r
        return self._fge(x2 | 1, mid + 1, hi, ql, qr, thr)

    def set_pt(self, p, v):
        self._upd(1, 0, self.sz - 1, p, p, 1, v)

    def rng_set(self, l, r, v):
        if l <= r:
            self._upd(1, 0, self.sz - 1, l, r, 1, v)

    def rng_add(self, l, r, v):
        if l <= r:
            self._upd(1, 0, self.sz - 1, l, r, 2, v)

    def pt_qry(self, p):
        return self._qry(1, 0, self.sz - 1, p)

    def first_ge(self, l, r, thr):
        if l > r:
            return -1
        return self._fge(1, 0, self.sz - 1, l, r, thr)


def solve_suite(n, obstacles, queries_with_ids, d):
    """Solve all queries for one suite using offline sweep + segment tree.

    For a fixed right endpoint r, M(l, r) is non-decreasing in l
    (more obstacles traversed => smaller or equal M).

    When advancing r to r+1 (adding obstacle a[r]):
      - Positions with M < a:     no change       (prefix, small l)
      - Positions with a <= M < 2a: set M = a-1   (middle)
      - Positions with M >= 2a:   M -= a          (suffix, large l)

    Boundaries found via segment tree descent on max values.
    """
    by_r = defaultdict(list)
    for idx, (qid, l, r) in enumerate(queries_with_ids):
        by_r[r].append((l, idx))

    answers = [0] * len(queries_with_ids)
    seg = SegTree(n)

    for pos in range(n):
        # Initialize M(pos+1, pos+1) = d (query spanning just this position)
        seg.set_pt(pos, d)

        a = obstacles[pos]
        if a > 0:
            # Find leftmost position with value >= a
            ga = seg.first_ge(0, pos, a)
            if ga != -1:
                # Find leftmost position with value >= 2a
                g2a = seg.first_ge(0, pos, 2 * a)
                if g2a != -1:
                    # Middle region [ga, g2a-1]: set to a-1
                    seg.rng_set(ga, g2a - 1, a - 1)
                    # Suffix region [g2a, pos]: subtract a
                    seg.rng_add(g2a, pos, -a)
                else:
                    # All values >= a are in [a, 2a): set to a-1
                    seg.rng_set(ga, pos, a - 1)

        # Answer queries whose right endpoint is pos+1 (1-indexed)
        r_1 = pos + 1
        if r_1 in by_r:
            for l_1, idx in by_r[r_1]:
                answers[idx] = seg.pt_qry(l_1 - 1)

    return answers


def main():
    with open('/data/manifest.json') as f:
        manifest = json.load(f)

    db_path = manifest['database']
    output_path = manifest['output']['path']

    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    c.execute('SELECT suite_id, max_height FROM test_suites ORDER BY suite_id')
    suites = c.fetchall()

    all_results = []

    for suite_id, d in suites:
        c.execute(
            'SELECT height FROM obstacles WHERE suite_id=? ORDER BY position',
            (suite_id,))
        obstacles = [h for (h,) in c.fetchall()]

        c.execute(
            'SELECT query_id, range_start, range_end FROM queries '
            'WHERE suite_id=? ORDER BY query_id',
            (suite_id,))
        queries = c.fetchall()

        n = len(obstacles)
        answers = solve_suite(n, obstacles, queries, d)

        all_results.extend(str(a) for a in answers)
        print("Suite {}: {} queries solved".format(suite_id, len(queries)),
              file=sys.stderr)

    conn.close()

    with open(output_path, 'w') as f:
        f.write('\n'.join(all_results) + '\n')

    print("Wrote {} answers to {}".format(len(all_results), output_path))


if __name__ == '__main__':
    main()
