#!/usr/bin/env python3
"""Generate DLX problem files and workspace structure."""
import os

def write_file(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write(content)

def gen_example():
    """Knuth's basic example from TAOCP 7.2.2.1. 1 solution: AD, CEF, BG."""
    return """\
| Knuth's basic example (TAOCP 7.2.2.1)
A B C D E | F G
C E F
A D G
B C F
A D
B G
D E G
"""

def gen_queens(n):
    """N-Queens exact cover. Primary: rows + cols. Secondary: diagonals."""
    lines = [f"| {n}-Queens exact cover problem"]
    primary = [f"r{i}" for i in range(n)] + [f"c{i}" for i in range(n)]
    secondary = [f"a{i}" for i in range(2*n-1)] + [f"d{i}" for i in range(2*n-1)]
    lines.append(" ".join(primary) + " | " + " ".join(secondary))
    for row in range(n):
        for col in range(n):
            asc = row + col
            desc = (n - 1 - row) + col
            lines.append(f"r{row} c{col} a{asc} d{desc}")
    return "\n".join(lines) + "\n"

def gen_rooks(n):
    """N-Rooks exact cover. Primary: rows + cols. No diagonals."""
    lines = [f"| {n}-Rooks exact cover problem"]
    primary = [f"r{i}" for i in range(n)] + [f"c{i}" for i in range(n)]
    lines.append(" ".join(primary))
    for row in range(n):
        for col in range(n):
            lines.append(f"r{row} c{col}")
    return "\n".join(lines) + "\n"

def gen_sudoku_buggy(puzzle):
    """Sudoku DLX encoding with a transposed block index formula (bug).

    Correct: block = (row // 3) * 3 + (col // 3)
    Buggy:   block = (row // 3) + (col // 3) * 3
    This swaps blocks (1,3), (2,6), (5,7) while leaving 0,4,8 unchanged.
    """
    lines = ["| Sudoku exact cover problem"]
    items = []
    for r in range(9):
        for c in range(9):
            items.append(f"p{r}{c}")
    for r in range(9):
        for v in range(9):
            items.append(f"r{r}{v}")
    for c in range(9):
        for v in range(9):
            items.append(f"k{c}{v}")
    for b in range(9):
        for v in range(9):
            items.append(f"b{b}{v}")
    lines.append(" ".join(items))

    for r in range(9):
        for c in range(9):
            val = int(puzzle[r * 9 + c])
            blk = (r // 3) + (c // 3) * 3  # BUGGY: transposed
            if val != 0:
                v = val - 1
                lines.append(f"p{r}{c} r{r}{v} k{c}{v} b{blk}{v}")
            else:
                for v in range(9):
                    lines.append(f"p{r}{c} r{r}{v} k{c}{v} b{blk}{v}")
    return "\n".join(lines) + "\n"

def gen_plus_noise_5x5():
    """Plus Noise 5x5 grid with opaque item names. 240 solutions.

    25 cell items (s0-s24) + 125 constraint items (t0-t124), all primary.
    Each cell (r,c) with value v covers 1 cell item + 5 plus-center constraint items
    (the 5 plus-shaped neighborhoods that include this cell).
    """
    n, nv = 5, 5
    lines = ["| Unnamed constraint satisfaction problem"]
    items = [f"s{i}" for i in range(n * n)]
    items += [f"t{i}" for i in range(n * n * nv)]
    lines.append(" ".join(items))

    for r in range(n):
        for c in range(n):
            cell = r * n + c
            for v in range(nv):
                opt = [f"s{cell}"]
                for dr, dc in [(0, 0), (-1, 0), (1, 0), (0, -1), (0, 1)]:
                    pr, pc = (r + dr) % n, (c + dc) % n
                    idx = (pr * n + pc) * nv + v
                    opt.append(f"t{idx}")
                lines.append(" ".join(opt))
    return "\n".join(lines) + "\n"

def main():
    puzzle = "530070000600195000098000060800060003400803001700020006060000280000419005000080079"

    write_file("/app/problems/example.dlx", gen_example())
    write_file("/app/problems/queens8.dlx", gen_queens(8))
    write_file("/app/problems/rooks6.dlx", gen_rooks(6))
    write_file("/app/problems/sudoku.dlx", gen_sudoku_buggy(puzzle))
    write_file("/app/problems/unknown.dlx", gen_plus_noise_5x5())

    write_file("/app/puzzle.txt", puzzle + "\n")

    notes = """\
DLX Research Notes
==================
Knuth's DLX1 solver source: /app/knuth/ (CWEB literate programming format)
Problem files: /app/problems/ (DLX input format, specification in dlx1.w)
Sudoku puzzle (81-char, 0=empty): /app/puzzle.txt

Verified results:
  example.dlx: 1 solution
  queens8.dlx: 92 solutions (OEIS A000170)
  rooks6.dlx: 720 solutions (6! = 720)

Remaining work:
  - Validate all problem encodings
  - Characterize unknown.dlx
  - Extract and verify solutions
"""
    write_file("/app/notes.txt", notes)
    os.makedirs("/app/results", exist_ok=True)
    print("Setup complete.")

if __name__ == "__main__":
    main()
