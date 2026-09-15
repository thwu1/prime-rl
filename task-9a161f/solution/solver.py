"""Reference solver for the Undead puzzle with encoded game descriptions."""

import os
from pathlib import Path


def parse_game_description(filepath):
    """Parse a game description file.

    Format: WxH:GRID_DESC,C1,C2,...,G_COUNT,V_COUNT,Z_COUNT

    Grid encoding (row-major scan):
      - lowercase a-z = 1-26 consecutive empty cells
      - L = backslash mirror
      - R = forward-slash mirror
    Clue order: top L-R, bottom L-R, left T-B, right T-B, then counts.
    """
    with open(filepath) as f:
        s = f.read().strip()

    params, rest = s.split(':')
    w, h = map(int, params.split('x'))
    n = w

    parts = rest.split(',')
    grid_desc = parts[0]
    numbers = list(map(int, parts[1:]))

    grid = []
    row = []
    for ch in grid_desc:
        if 'a' <= ch <= 'z':
            count = ord(ch) - ord('a') + 1
            for _ in range(count):
                row.append('.')
                if len(row) == n:
                    grid.append(row)
                    row = []
        elif ch == 'L':
            row.append('\\')
            if len(row) == n:
                grid.append(row)
                row = []
        elif ch == 'R':
            row.append('/')
            if len(row) == n:
                grid.append(row)
                row = []

    top = numbers[:n]
    bottom = numbers[n:2 * n]
    left = numbers[2 * n:3 * n]
    right = numbers[3 * n:4 * n]
    ghosts = numbers[4 * n]
    vampires = numbers[4 * n + 1]
    zombies = numbers[4 * n + 2]

    return {
        'n': n, 'grid': grid,
        'top': top, 'bottom': bottom, 'left': left, 'right': right,
        'ghosts': ghosts, 'vampires': vampires, 'zombies': zombies,
    }


def trace_path(grid, n, start_row, start_col, direction):
    """Trace a sight line through the grid.

    Returns list of (row, col, is_reflected) for each non-mirror cell visited.
    Direction: 0=DOWN, 1=RIGHT, 2=UP, 3=LEFT.
    """
    dr = [1, 0, -1, 0]
    dc = [0, 1, 0, -1]
    r, c = start_row, start_col
    reflected = False
    cells = []
    visited = set()
    while 0 <= r < n and 0 <= c < n:
        state = (r, c, direction)
        if state in visited:
            break
        visited.add(state)
        cell = grid[r][c]
        if cell == '/':
            direction = {0: 3, 1: 2, 2: 1, 3: 0}[direction]
            reflected = not reflected
        elif cell == '\\':
            direction = {0: 1, 1: 0, 2: 3, 3: 2}[direction]
            reflected = not reflected
        else:
            cells.append((r, c, reflected))
        r += dr[direction]
        c += dc[direction]
    return cells


def precompute_paths(grid, n):
    """Compute all 4*n sight-line paths."""
    paths = []
    for c in range(n):
        paths.append(trace_path(grid, n, 0, c, 0))
    for c in range(n):
        paths.append(trace_path(grid, n, n - 1, c, 2))
    for r in range(n):
        paths.append(trace_path(grid, n, r, 0, 1))
    for r in range(n):
        paths.append(trace_path(grid, n, r, n - 1, 3))
    return paths


def visibility(monster, reflected):
    """Return 1 if monster is visible given reflection state, else 0."""
    if monster == 2:  # Z
        return 1
    if monster == 0:  # G
        return 0 if reflected else 1
    return 1 if reflected else 0  # V


class UndeadSolver:
    """CSP solver using constraint propagation + backtracking."""

    def __init__(self, puzzle):
        self.n = puzzle['n']
        self.grid = puzzle['grid']
        self.targets = [puzzle['ghosts'], puzzle['vampires'], puzzle['zombies']]

        self.empty_cells = []
        self.cell_index = {}
        for r in range(self.n):
            for c in range(self.n):
                if self.grid[r][c] == '.':
                    self.cell_index[(r, c)] = len(self.empty_cells)
                    self.empty_cells.append((r, c))
        self.num_cells = len(self.empty_cells)

        clues = puzzle['top'] + puzzle['bottom'] + puzzle['left'] + puzzle['right']
        raw_paths = precompute_paths(self.grid, self.n)
        self.paths = []
        for path_cells, clue in zip(raw_paths, clues):
            indices = []
            refls = []
            for r, c, refl in path_cells:
                if (r, c) in self.cell_index:
                    indices.append(self.cell_index[(r, c)])
                    refls.append(refl)
            self.paths.append((indices, refls, clue))

    def solve(self):
        """Solve the puzzle. Returns solution grid or None."""
        domains = [frozenset({0, 1, 2}) for _ in range(self.num_cells)]
        result = self._search(domains)
        if result is None:
            return None
        solution = [row[:] for row in self.grid]
        chars = {0: 'G', 1: 'V', 2: 'Z'}
        for ci, (r, c) in enumerate(self.empty_cells):
            solution[r][c] = chars[result[ci]]
        return solution

    def _search(self, domains):
        """Recursive search with propagation."""
        domains = self._propagate(list(domains))
        if domains is None:
            return None
        if all(len(d) == 1 for d in domains):
            assignment = [next(iter(d)) for d in domains]
            if self._verify(assignment):
                return assignment
            return None
        best_ci = min(
            (ci for ci in range(self.num_cells) if len(domains[ci]) > 1),
            key=lambda ci: len(domains[ci]),
            default=None
        )
        if best_ci is None:
            return None
        for m in sorted(domains[best_ci]):
            new_domains = list(domains)
            new_domains[best_ci] = frozenset({m})
            result = self._search(new_domains)
            if result is not None:
                return result
        return None

    def _propagate(self, domains):
        """Iterative constraint propagation."""
        domains = [set(d) for d in domains]
        changed = True
        while changed:
            changed = False

            for m in range(3):
                must_count = sum(1 for d in domains if d == {m})
                can_count = sum(1 for d in domains if m in d)
                if must_count > self.targets[m] or can_count < self.targets[m]:
                    return None
                if must_count == self.targets[m]:
                    for ci in range(self.num_cells):
                        if len(domains[ci]) > 1 and m in domains[ci]:
                            domains[ci].discard(m)
                            changed = True
                            if not domains[ci]:
                                return None
                if can_count == self.targets[m]:
                    for ci in range(self.num_cells):
                        if m in domains[ci] and len(domains[ci]) > 1:
                            domains[ci] = {m}
                            changed = True

            for indices, refls, target in self.paths:
                assigned_vis = 0
                unassigned = []
                for ci, refl in zip(indices, refls):
                    if len(domains[ci]) == 1:
                        assigned_vis += visibility(next(iter(domains[ci])), refl)
                    else:
                        min_v = min(visibility(mv, refl) for mv in domains[ci])
                        max_v = max(visibility(mv, refl) for mv in domains[ci])
                        unassigned.append((ci, refl, min_v, max_v))

                remaining = target - assigned_vis
                if remaining < 0:
                    return None

                u_min = sum(mn for _, _, mn, _ in unassigned)
                u_max = sum(mx for _, _, _, mx in unassigned)

                if remaining < u_min or remaining > u_max:
                    return None

                if remaining == u_max:
                    for ci, refl, mn, mx in unassigned:
                        if mn < mx:
                            nd = {mv for mv in domains[ci]
                                  if visibility(mv, refl) == mx}
                            if nd != domains[ci]:
                                domains[ci] = nd
                                changed = True
                                if not domains[ci]:
                                    return None

                if remaining == u_min:
                    for ci, refl, mn, mx in unassigned:
                        if mn < mx:
                            nd = {mv for mv in domains[ci]
                                  if visibility(mv, refl) == mn}
                            if nd != domains[ci]:
                                domains[ci] = nd
                                changed = True
                                if not domains[ci]:
                                    return None

        return [frozenset(d) for d in domains]

    def _verify(self, assignment):
        """Check that a complete assignment satisfies all constraints."""
        counts = [0, 0, 0]
        for m in assignment:
            counts[m] += 1
        if counts != self.targets:
            return False
        for indices, refls, target in self.paths:
            vis = sum(visibility(assignment[ci], refl)
                      for ci, refl in zip(indices, refls))
            if vis != target:
                return False
        return True


def main():
    solutions_dir = Path('/app/solutions')
    solutions_dir.mkdir(exist_ok=True)

    puzzle_dirs = [Path('/app/puzzles'), Path('/app/generated')]

    for puzzles_dir in puzzle_dirs:
        if not puzzles_dir.exists():
            continue
        puzzle_files = sorted(puzzles_dir.glob('*.txt'))

        for pf in puzzle_files:
            print(f"Solving {pf.name}...")
            puzzle = parse_game_description(str(pf))
            solver = UndeadSolver(puzzle)
            solution = solver.solve()

            if solution is None:
                print(f"  No solution found for {pf.name}!")
                continue

            sol_file = solutions_dir / pf.name
            with open(sol_file, 'w') as f:
                for row in solution:
                    f.write(''.join(row) + '\n')
            print(f"  Solution written to {sol_file}")


if __name__ == '__main__':
    main()
