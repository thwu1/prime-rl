"""
Nurikabe puzzle solver.


Reads /app/puzzles.json, solves each puzzle using constraint propagation
and backtracking search, writes solutions to /app/solutions.json.
"""

import json
import sys
import time
from collections import deque

DIRS = [(-1, 0), (1, 0), (0, -1), (0, 1)]
UNKNOWN, SEA, ISLAND = 0, 1, 2


def in_bounds(r, c, R, C):
    return 0 <= r < R and 0 <= c < C


def solve_nurikabe(rows, cols, clues_list, timeout=120):
    """Solve a Nurikabe puzzle. Returns grid (1=sea, 0=island) or None."""
    clues = {(r, c): v for r, c, v in clues_list}
    grid = [[UNKNOWN] * cols for _ in range(rows)]
    for r, c in clues:
        grid[r][c] = ISLAND
    deadline = time.time() + timeout
    result = _solve(grid, clues, rows, cols, deadline)
    if result is None:
        return None
    return [
        [1 if result[r][c] == SEA else 0 for c in range(cols)]
        for r in range(rows)
    ]


def _solve(grid, clues, R, C, deadline):
    grid = [row[:] for row in grid]
    if time.time() > deadline:
        return None

    # Seal complete islands (always safe)
    if not _seal_complete(grid, clues, R, C):
        return None

    # Quick prune
    if not _prune(grid, clues, R, C):
        return None

    unknown = [
        (r, c) for r in range(R) for c in range(C) if grid[r][c] == UNKNOWN
    ]
    if not unknown:
        return grid if _verify_full(grid, clues, R, C) else None

    # Pick most constrained unknown cell
    best = None
    best_score = -1
    for r, c in unknown:
        score = sum(
            1
            for dr, dc in DIRS
            if in_bounds(r + dr, c + dc, R, C)
            and grid[r + dr][c + dc] != UNKNOWN
        )
        if score > best_score:
            best_score = score
            best = (r, c)

    r, c = best
    for state in [SEA, ISLAND]:
        g2 = [row[:] for row in grid]
        g2[r][c] = state
        if _prune(g2, clues, R, C):
            result = _solve(g2, clues, R, C, deadline)
            if result is not None:
                return result
    return None


def _seal_complete(grid, clues, R, C):
    """Iteratively seal complete islands."""
    changed = True
    while changed:
        changed = False
        islands = _get_clue_islands(grid, clues, R, C)
        if islands is None:
            return False

        for cpos, cells in islands.items():
            target = clues[cpos]
            if len(cells) > target:
                return False
            if len(cells) == target:
                for ir, ic in cells:
                    for dr, dc in DIRS:
                        nr, nc = ir + dr, ic + dc
                        if (
                            in_bounds(nr, nc, R, C)
                            and grid[nr][nc] == UNKNOWN
                        ):
                            grid[nr][nc] = SEA
                            changed = True
    return True


def _get_clue_islands(grid, clues, R, C):
    """Get island components connected to clues. None on merged-clue contradiction."""
    visited = [[False] * C for _ in range(R)]
    islands = {}
    for cr, cc in clues:
        if visited[cr][cc]:
            return None
        cells = set()
        q = deque([(cr, cc)])
        visited[cr][cc] = True
        while q:
            r, c = q.popleft()
            cells.add((r, c))
            for dr, dc in DIRS:
                nr, nc = r + dr, c + dc
                if (
                    in_bounds(nr, nc, R, C)
                    and not visited[nr][nc]
                    and grid[nr][nc] == ISLAND
                ):
                    visited[nr][nc] = True
                    q.append((nr, nc))
        if sum(1 for p in cells if p in clues) > 1:
            return None
        islands[(cr, cc)] = cells
    return islands


def _prune(grid, clues, R, C):
    """Quick pruning checks for partial assignment."""
    # No 2x2 sea
    for r in range(R - 1):
        for c in range(C - 1):
            if (
                grid[r][c] == SEA
                and grid[r][c + 1] == SEA
                and grid[r + 1][c] == SEA
                and grid[r + 1][c + 1] == SEA
            ):
                return False

    # Islands not oversized or merged
    islands = _get_clue_islands(grid, clues, R, C)
    if islands is None:
        return False
    for cpos, cells in islands.items():
        if len(cells) > clues[cpos]:
            return False

    # Each incomplete island must be able to reach enough cells
    for cpos, cells in islands.items():
        target = clues[cpos]
        if len(cells) < target:
            reachable = set(cells)
            q = deque([(r, c, 0) for r, c in cells])
            while q:
                r, c, d = q.popleft()
                if d < target - 1:
                    for dr, dc in DIRS:
                        nr, nc = r + dr, c + dc
                        if (
                            in_bounds(nr, nc, R, C)
                            and (nr, nc) not in reachable
                            and grid[nr][nc] != SEA
                        ):
                            if grid[nr][nc] == ISLAND:
                                owner = _find_clue(
                                    grid, clues, R, C, nr, nc
                                )
                                if owner is not None and owner != cpos:
                                    continue
                            reachable.add((nr, nc))
                            q.append((nr, nc, d + 1))
            if len(reachable) < target:
                return False

    # Sea connectivity (through non-ISLAND cells)
    sea = [
        (r, c)
        for r in range(R)
        for c in range(C)
        if grid[r][c] == SEA
    ]
    if len(sea) > 1:
        vis = set([sea[0]])
        q = deque([sea[0]])
        while q:
            cr, cc = q.popleft()
            for dr, dc in DIRS:
                nr, nc = cr + dr, cc + dc
                if (
                    (nr, nc) not in vis
                    and in_bounds(nr, nc, R, C)
                    and grid[nr][nc] != ISLAND
                ):
                    vis.add((nr, nc))
                    q.append((nr, nc))
        if not all((r, c) in vis for r, c in sea):
            return False

    return True


def _find_clue(grid, clues, R, C, r, c):
    """Find which clue an ISLAND cell belongs to."""
    if (r, c) in clues:
        return (r, c)
    if grid[r][c] != ISLAND:
        return None
    vis = set([(r, c)])
    q = deque([(r, c)])
    while q:
        cr, cc = q.popleft()
        if (cr, cc) in clues:
            return (cr, cc)
        for dr, dc in DIRS:
            nr, nc = cr + dr, cc + dc
            if (
                (nr, nc) not in vis
                and in_bounds(nr, nc, R, C)
                and grid[nr][nc] == ISLAND
            ):
                vis.add((nr, nc))
                q.append((nr, nc))
    return None


def _verify_full(grid, clues, R, C):
    """Verify a fully-assigned grid satisfies all constraints."""
    if any(grid[r][c] == UNKNOWN for r in range(R) for c in range(C)):
        return False
    islands = _get_clue_islands(grid, clues, R, C)
    if islands is None:
        return False
    # No orphan island cells
    visited = set()
    for cells in islands.values():
        visited.update(cells)
    for r in range(R):
        for c in range(C):
            if grid[r][c] == ISLAND and (r, c) not in visited:
                return False
    # Island sizes match
    for cpos in clues:
        if cpos not in islands or len(islands[cpos]) != clues[cpos]:
            return False
    # No 2x2 sea
    for r in range(R - 1):
        for c in range(C - 1):
            if (
                grid[r][c] == SEA
                and grid[r][c + 1] == SEA
                and grid[r + 1][c] == SEA
                and grid[r + 1][c + 1] == SEA
            ):
                return False
    # Sea connectivity
    sea = [
        (r, c)
        for r in range(R)
        for c in range(C)
        if grid[r][c] == SEA
    ]
    if len(sea) > 1:
        vis = set([sea[0]])
        q = deque([sea[0]])
        while q:
            cr, cc = q.popleft()
            for dr, dc in DIRS:
                nr, nc = cr + dr, cc + dc
                if (
                    (nr, nc) not in vis
                    and in_bounds(nr, nc, R, C)
                    and grid[nr][nc] == SEA
                ):
                    vis.add((nr, nc))
                    q.append((nr, nc))
        if len(vis) != len(sea):
            return False
    return True


def main():
    with open("/app/puzzles.json") as f:
        puzzles = json.load(f)

    solutions = []
    for puzzle in puzzles:
        pid = puzzle["id"]
        R, C = puzzle["rows"], puzzle["cols"]
        print(f"Solving {pid} ({R}x{C})...", end=" ", flush=True)
        t0 = time.time()
        result = solve_nurikabe(R, C, puzzle["clues"])
        elapsed = time.time() - t0
        if result is None:
            print(f"FAILED ({elapsed:.1f}s)")
            sys.exit(1)
        print(f"OK ({elapsed:.1f}s)")
        solutions.append({"id": pid, "grid": result})

    with open("/app/solutions.json", "w") as f:
        json.dump(solutions, f)
    print(f"Wrote {len(solutions)} solutions to /app/solutions.json")


if __name__ == "__main__":
    main()
