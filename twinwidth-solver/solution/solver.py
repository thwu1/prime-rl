#!/usr/bin/env python3
"""
Optimal twinwidth solver using branch-and-bound with greedy upper bound.

Reads a graph in PACE .gr format from stdin and writes a minimum-width
contraction sequence to stdout.
"""
import sys


def parse_gr(text):
    """Parse PACE .gr format. Returns (n, list_of_edge_tuples)."""
    n = 0
    edges = []
    for line in text.strip().split("\n"):
        line = line.strip()
        if not line or line.startswith("c"):
            continue
        if line.startswith("p"):
            parts = line.split()
            n = int(parts[2])
        else:
            parts = line.split()
            edges.append((int(parts[0]), int(parts[1])))
    return n, edges


class Trigraph:
    """Graph with black and red edges supporting contraction."""

    __slots__ = ("verts", "black", "red")

    def __init__(self, n, edges):
        self.verts = list(range(1, n + 1))
        self.black = {v: set() for v in self.verts}
        self.red = {v: set() for v in self.verts}
        for u, v in edges:
            self.black[u].add(v)
            self.black[v].add(u)

    def copy(self):
        t = object.__new__(Trigraph)
        t.verts = list(self.verts)
        t.black = {v: set(s) for v, s in self.black.items()}
        t.red = {v: set(s) for v, s in self.red.items()}
        return t

    def max_red_degree(self):
        return max((len(self.red[v]) for v in self.verts), default=0)

    def contract(self, x, y):
        """Contract y into x (x survives, y removed). Modifies in place."""
        x_neigh = (self.black[x] | self.red[x]) - {y}
        y_neigh = (self.black[y] | self.red[y]) - {x}

        new_b = set()
        new_r = set()

        for z in x_neigh:
            if z in y_neigh:
                # Neighbor of both: keep current color
                if z in self.black[x]:
                    new_b.add(z)
                else:
                    new_r.add(z)
            else:
                # Neighbor of x only: becomes red
                new_r.add(z)

        # Neighbors of y only: new red edge
        for z in y_neigh:
            if z not in x_neigh:
                new_r.add(z)

        # Remove y
        self.verts.remove(y)
        del self.black[y]
        del self.red[y]
        for v in self.verts:
            self.black[v].discard(y)
            self.red[v].discard(y)

        # Set x adjacencies
        self.black[x] = new_b
        self.red[x] = new_r
        for z in self.verts:
            if z == x:
                continue
            self.black[z].discard(x)
            self.red[z].discard(x)
            if z in new_b:
                self.black[z].add(x)
            elif z in new_r:
                self.red[z].add(x)


def _greedy_upper_bound(tg):
    """Greedy heuristic: always merge the pair with smallest resulting max red degree."""
    tg = tg.copy()
    width = 0
    seq = []
    while len(tg.verts) > 1:
        best_pair = None
        best_w = float("inf")
        verts = tg.verts[:]
        for i in range(len(verts)):
            for j in range(i + 1, len(verts)):
                x, y = verts[i], verts[j]
                tc = tg.copy()
                tc.contract(x, y)
                w = tc.max_red_degree()
                if w < best_w:
                    best_w = w
                    best_pair = (x, y)
        x, y = best_pair
        tg.contract(x, y)
        width = max(width, tg.max_red_degree())
        seq.append((x, y))
    return width, seq


def solve(n, edges):
    """Branch-and-bound search for an optimal contraction sequence."""
    if n <= 1:
        return 0, []

    initial = Trigraph(n, edges)

    # Greedy upper bound for pruning
    best_w, best_seq = _greedy_upper_bound(initial)

    if best_w == 0:
        return 0, best_seq

    best = [best_w, best_seq]

    def search(tg, cur_w, seq):
        if len(tg.verts) == 1:
            if cur_w < best[0]:
                best[0] = cur_w
                best[1] = list(seq)
            return

        if cur_w >= best[0]:
            return

        verts = sorted(tg.verts)
        nv = len(verts)
        for i in range(nv):
            for j in range(i + 1, nv):
                x, y = verts[i], verts[j]
                tc = tg.copy()
                tc.contract(x, y)
                w = max(cur_w, tc.max_red_degree())
                if w < best[0]:
                    seq.append((x, y))
                    search(tc, w, seq)
                    seq.pop()

    search(initial, 0, [])
    return best[0], best[1]


def main():
    text = sys.stdin.read()
    n, edges = parse_gr(text)
    _, seq = solve(n, edges)
    for x, y in seq:
        print(f"{x} {y}")


if __name__ == "__main__":
    main()
