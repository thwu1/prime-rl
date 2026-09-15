#!/usr/bin/env python3
"""

SameGame solver using beam search with isolated-cell penalty heuristic.
Usage: python3 solver.py <board_file>
Outputs one move per line: col row
"""
import sys
import time

ROWS = 15
COLS = 15
BEAM_WIDTH = 1000
TIME_LIMIT = 45.0


def load_board(filename):
    with open(filename) as f:
        lines = [line.strip() for line in f if line.strip()]
    grid = []
    for line in reversed(lines):
        grid.append(tuple(int(x) for x in line.split()))
    return tuple(grid)


def find_group(grid, col, row):
    color = grid[row][col]
    if color < 0:
        return frozenset()
    visited = set()
    stack = [(col, row)]
    while stack:
        c, r = stack.pop()
        if (c, r) in visited:
            continue
        if not (0 <= c < COLS and 0 <= r < ROWS):
            continue
        if grid[r][c] != color:
            continue
        visited.add((c, r))
        stack.append((c + 1, r))
        stack.append((c - 1, r))
        stack.append((c, r + 1))
        stack.append((c, r - 1))
    return frozenset(visited)


def get_all_groups(grid):
    visited = set()
    groups = []
    for r in range(ROWS):
        for c in range(COLS):
            if (c, r) not in visited and grid[r][c] >= 0:
                group = find_group(grid, c, r)
                visited |= group
                if len(group) >= 2:
                    groups.append(group)
    return groups


def apply_move(grid, group):
    g = [list(row) for row in grid]

    for c, r in group:
        g[r][c] = -1

    # Gravity
    for c in range(COLS):
        filled = [g[r][c] for r in range(ROWS) if g[r][c] >= 0]
        for r in range(ROWS):
            g[r][c] = filled[r] if r < len(filled) else -1

    # Column collapse
    non_empty = [c for c in range(COLS) if g[0][c] >= 0]
    result = [[-1] * COLS for _ in range(ROWS)]
    for new_c, old_c in enumerate(non_empty):
        for r in range(ROWS):
            result[r][new_c] = g[r][old_c]

    return tuple(tuple(row) for row in result)


def count_isolated(grid):
    count = 0
    for r in range(ROWS):
        for c in range(COLS):
            if grid[r][c] >= 0:
                color = grid[r][c]
                has_neighbor = False
                for dc, dr in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nc, nr = c + dc, r + dr
                    if 0 <= nc < COLS and 0 <= nr < ROWS and grid[nr][nc] == color:
                        has_neighbor = True
                        break
                if not has_neighbor:
                    count += 1
    return count


def evaluate(grid, score):
    val = score
    if grid[0][0] < 0:
        return val + 1000
    val -= count_isolated(grid) * 10
    return val


def beam_search(grid):
    start = time.time()

    # Each beam entry: (grid_tuple, accumulated_score, move_list)
    beam = [(grid, 0, [])]
    best_score = 0
    best_moves = []

    while beam:
        elapsed = time.time() - start
        if elapsed > TIME_LIMIT:
            break

        candidates = []
        for g, score, moves in beam:
            groups = get_all_groups(g)

            if not groups:
                fs = score + (1000 if g[0][0] < 0 else 0)
                if fs > best_score:
                    best_score = fs
                    best_moves = moves
                continue

            for group in groups:
                if time.time() - start > TIME_LIMIT:
                    break

                n = len(group)
                ms = (n - 2) ** 2
                new_score = score + ms
                new_grid = apply_move(g, group)

                # Pick smallest (col, row) in group as the representative move
                rep = min(group)
                new_moves = moves + [rep]

                ev = evaluate(new_grid, new_score)
                candidates.append((ev, id(new_grid), new_grid, new_score, new_moves))

        if not candidates:
            break

        # Sort descending by eval; id() as tiebreaker to avoid comparing tuples
        candidates.sort(key=lambda x: -x[0])
        beam = [
            (g, s, m) for _, _, g, s, m in candidates[:BEAM_WIDTH]
        ]

        # Track best from current beam
        for g, s, m in beam:
            fs = s + (1000 if g[0][0] < 0 else 0)
            if fs > best_score:
                best_score = fs
                best_moves = m

    return best_moves, best_score


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 solver.py <board_file>", file=sys.stderr)
        sys.exit(1)

    board_file = sys.argv[1]
    grid = load_board(board_file)

    moves, score = beam_search(grid)

    for col, row in moves:
        print(f"{col} {row}")

    print(f"# Final score: {score}", file=sys.stderr)


if __name__ == "__main__":
    main()
