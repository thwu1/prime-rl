#!/usr/bin/env python3
"""
PACE Twinwidth Contraction Sequence Verifier

Validates a contraction sequence against a graph and reports its width.

Usage:
  verify_tww GRAPH.gr [SOLUTION.txt]

If SOLUTION.txt is omitted, reads the contraction sequence from stdin.

Exit codes:
  0 - Valid sequence
  1 - Invalid sequence
  2 - Usage error
"""
import sys


def parse_gr(text):
    n, edges = 0, []
    for line in text.strip().split("\n"):
        line = line.strip()
        if not line or line.startswith("c"):
            continue
        if line.startswith("p"):
            parts = line.split()
            n = int(parts[2])
        else:
            u, v = map(int, line.split()[:2])
            edges.append((u, v))
    return n, edges


def verify(n, edges, sequence):
    vertices = set(range(1, n + 1))
    black = {v: set() for v in vertices}
    red = {v: set() for v in vertices}
    for u, v in edges:
        black[u].add(v)
        black[v].add(u)

    max_red = 0
    step_widths = []

    for i, (x, y) in enumerate(sequence):
        if x not in vertices:
            return False, -1, f"Step {i+1}: vertex {x} not alive"
        if y not in vertices:
            return False, -1, f"Step {i+1}: vertex {y} not alive"
        if x == y:
            return False, -1, f"Step {i+1}: self-contraction"

        x_n = (black[x] | red[x]) - {y}
        y_n = (black[y] | red[y]) - {x}
        nb, nr = set(), set()

        for z in x_n:
            if z in y_n:
                (nb if z in black[x] else nr).add(z)
            else:
                nr.add(z)
        for z in y_n - x_n:
            nr.add(z)

        vertices.discard(y)
        del black[y]
        del red[y]
        for v in vertices:
            black[v].discard(y)
            red[v].discard(y)

        black[x] = nb
        red[x] = nr
        for z in vertices:
            if z == x:
                continue
            black[z].discard(x)
            red[z].discard(x)
            if z in nb:
                black[z].add(x)
            elif z in nr:
                red[z].add(x)

        step_max = max(len(red[v]) for v in vertices)
        max_red = max(max_red, step_max)
        step_widths.append(step_max)

    if len(vertices) != 1:
        return False, -1, f"Sequence incomplete: {len(vertices)} vertices remain"

    return True, max_red, ""


def main():
    if len(sys.argv) < 2:
        print(__doc__.strip())
        sys.exit(2)

    with open(sys.argv[1]) as f:
        gr_text = f.read()
    n, edges = parse_gr(gr_text)

    if len(sys.argv) >= 3:
        with open(sys.argv[2]) as f:
            sol_text = f.read()
    else:
        sol_text = sys.stdin.read()

    seq = []
    for line in sol_text.strip().split("\n"):
        line = line.strip()
        if line and not line.startswith("c"):
            parts = line.split()
            if len(parts) >= 2:
                seq.append((int(parts[0]), int(parts[1])))

    expected = n - 1
    if len(seq) != expected:
        print(f"ERROR: Expected {expected} contractions, got {len(seq)}")
        sys.exit(1)

    valid, width, err = verify(n, edges, seq)
    if valid:
        print(f"VALID")
        print(f"Width: {width}")
        print(f"Vertices: {n}, Edges: {len(edges)}")
    else:
        print(f"INVALID: {err}")
    sys.exit(0 if valid else 1)


if __name__ == "__main__":
    main()
