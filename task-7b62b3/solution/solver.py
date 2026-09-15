#!/usr/bin/env python3
"""
Reference solver for exact cover constraint suite.

"""
import os
import sys


# ---------------------------------------------------------------------------
# Problem 1: N-Queens counting via bitwise backtracking
# ---------------------------------------------------------------------------
def solve_nqueens_count(n):
    """Count all solutions to the N-Queens problem using bitwise backtracking."""
    count = 0
    all_ones = (1 << n) - 1

    def solve(cols, left_diag, right_diag):
        nonlocal count
        if cols == all_ones:
            count += 1
            return
        available = all_ones & ~(cols | left_diag | right_diag)
        while available:
            bit = available & (-available)
            available -= bit
            solve(cols | bit, (left_diag | bit) << 1, (right_diag | bit) >> 1)

    solve(0, 0, 0)
    return count


# ---------------------------------------------------------------------------
# Problem 2: Sudoku via constraint-tracking backtracking
# ---------------------------------------------------------------------------
def solve_sudoku(puzzle_str):
    """Solve a Sudoku puzzle given as an 81-char string (0 = empty)."""
    board = [int(c) for c in puzzle_str.strip()]
    rows = [set() for _ in range(9)]
    cols = [set() for _ in range(9)]
    blocks = [set() for _ in range(9)]
    empty = []

    for i in range(81):
        r, c = i // 9, i % 9
        b = (r // 3) * 3 + c // 3
        if board[i] != 0:
            rows[r].add(board[i])
            cols[c].add(board[i])
            blocks[b].add(board[i])
        else:
            empty.append(i)

    def solve(idx):
        if idx == len(empty):
            return True
        pos = empty[idx]
        r, c = pos // 9, pos % 9
        b = (r // 3) * 3 + c // 3
        for v in range(1, 10):
            if v not in rows[r] and v not in cols[c] and v not in blocks[b]:
                board[pos] = v
                rows[r].add(v)
                cols[c].add(v)
                blocks[b].add(v)
                if solve(idx + 1):
                    return True
                rows[r].discard(v)
                cols[c].discard(v)
                blocks[b].discard(v)
                board[pos] = 0
        return False

    solve(0)
    return "".join(str(d) for d in board)


# ---------------------------------------------------------------------------
# Problem 3: Plus Noise 5x5 grid counting
# ---------------------------------------------------------------------------
def count_plus_noise(n=5):
    """Count all valid nxn Plus Noise grids.

    Each cell has a value in {1..n}. For every cell, the plus-shaped
    neighborhood (cell + 4 cardinal neighbours, toroidal) must contain
    all n distinct values.
    """
    grid = [[0] * n for _ in range(n)]
    count = 0

    # Precompute: plus cells for each center
    plus_cells = {}
    for i in range(n):
        for j in range(n):
            plus_cells[(i, j)] = [
                (i, j),
                ((i - 1) % n, j),
                ((i + 1) % n, j),
                (i, (j - 1) % n),
                (i, (j + 1) % n),
            ]

    # Precompute: which plus-centers include cell (i,j)
    cell_centers = {}
    for i in range(n):
        for j in range(n):
            cell_centers[(i, j)] = [
                (i, j),
                ((i - 1) % n, j),
                ((i + 1) % n, j),
                (i, (j - 1) % n),
                (i, (j + 1) % n),
            ]

    def is_valid(i, j, v):
        """Return True if placing v at (i,j) causes no duplicate in any plus."""
        for ci, cj in cell_centers[(i, j)]:
            for pi, pj in plus_cells[(ci, cj)]:
                if (pi, pj) != (i, j) and grid[pi][pj] == v:
                    return False
        return True

    def solve(pos):
        nonlocal count
        if pos == n * n:
            count += 1
            return
        i, j = pos // n, pos % n
        for v in range(1, n + 1):
            if is_valid(i, j, v):
                grid[i][j] = v
                solve(pos + 1)
                grid[i][j] = 0

    solve(0)
    return count


# ---------------------------------------------------------------------------
# Problem 4: IGN feasibility via CSP with MRV heuristic
# ---------------------------------------------------------------------------
def check_ign_feasibility():
    """Check whether a 9x9 grid satisfying full IGN constraints exists.

    Constraints:
      - Every row has values 1-9 exactly once.
      - Every column has values 1-9 exactly once.
      - For every cell (i,j), the 3x3 block centred at (i,j) with toroidal
        wrapping has values 1-9 exactly once (81 overlapping blocks).
    """
    n = 9
    grid = [[0] * n for _ in range(n)]

    # Precompute peers for each cell: all cells that share a row, column,
    # or toroidal 3x3 block with it.
    cell_peers = {}
    for i in range(n):
        for j in range(n):
            peers = set()
            # Row peers
            for c in range(n):
                if c != j:
                    peers.add((i, c))
            # Column peers
            for r in range(n):
                if r != i:
                    peers.add((r, j))
            # Block peers: (i,j) is in the 3x3 block centred at each (ci,cj)
            # where ci in {i-1,i,i+1}%9, cj in {j-1,j,j+1}%9.
            for di in range(-1, 2):
                for dj in range(-1, 2):
                    ci = (i + di) % n
                    cj = (j + dj) % n
                    for dr in range(-1, 2):
                        for dc in range(-1, 2):
                            pr = (ci + dr) % n
                            pc = (cj + dc) % n
                            if (pr, pc) != (i, j):
                                peers.add((pr, pc))
            cell_peers[(i, j)] = peers

    # Possible values for each cell
    possible = [[set(range(1, n + 1)) for _ in range(n)] for _ in range(n)]

    def solve():
        # MRV: choose unfilled cell with fewest remaining values
        best = None
        best_count = n + 1
        for i in range(n):
            for j in range(n):
                if grid[i][j] == 0:
                    cnt = len(possible[i][j])
                    if cnt == 0:
                        return False
                    if cnt < best_count:
                        best_count = cnt
                        best = (i, j)
                        if best_count == 1:
                            break
            if best is not None and best_count == 1:
                break

        if best is None:
            return True  # all cells filled

        i, j = best
        for v in list(possible[i][j]):
            grid[i][j] = v
            # Propagate: remove v from all peers' possibility sets
            removed = []
            conflict = False
            for pi, pj in cell_peers[(i, j)]:
                if grid[pi][pj] == 0 and v in possible[pi][pj]:
                    possible[pi][pj].discard(v)
                    removed.append((pi, pj))
                    if len(possible[pi][pj]) == 0:
                        conflict = True
                        break

            if not conflict and solve():
                return True

            # Undo propagation
            for pi, pj in removed:
                possible[pi][pj].add(v)
            grid[i][j] = 0

        return False

    return "feasible" if solve() else "infeasible"


# ---------------------------------------------------------------------------
# Main driver
# ---------------------------------------------------------------------------
def main():
    os.makedirs("/app/results", exist_ok=True)

    print("Problem 1: N-Queens N=13 counting...")
    nq = solve_nqueens_count(13)
    with open("/app/results/nqueens_count.txt", "w") as f:
        f.write(str(nq))
    print(f"  Result: {nq}")

    print("Problem 2: Sudoku...")
    with open("/app/puzzles/sudoku.txt") as f:
        puzzle = f.read().strip()
    sudoku_sol = solve_sudoku(puzzle)
    with open("/app/results/sudoku_solution.txt", "w") as f:
        f.write(sudoku_sol)
    print(f"  Result: {sudoku_sol}")

    print("Problem 3: Plus Noise 5x5 counting...")
    pn = count_plus_noise(5)
    with open("/app/results/plus_noise_count.txt", "w") as f:
        f.write(str(pn))
    print(f"  Result: {pn}")

    print("Problem 4: IGN feasibility...")
    ign = check_ign_feasibility()
    with open("/app/results/ign_feasible.txt", "w") as f:
        f.write(ign)
    print(f"  Result: {ign}")

    print("Done.")


if __name__ == "__main__":
    main()
