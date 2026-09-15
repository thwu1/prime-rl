"""Undead puzzle generator with unique-solution guarantee."""

import random
from pathlib import Path


def trace_path(grid, n, start_row, start_col, direction):
    """Trace a sight line through the grid."""
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


def visibility_int(monster, reflected):
    """Visibility for integer-coded monsters (0=G, 1=V, 2=Z)."""
    if monster == 2:
        return 1
    if monster == 0:
        return 0 if reflected else 1
    return 1 if reflected else 0


def visibility_char(monster, reflected):
    """Visibility for character monsters ('G','V','Z')."""
    if monster == 'Z':
        return 1
    if monster == 'G':
        return 0 if reflected else 1
    if monster == 'V':
        return 1 if reflected else 0
    return 0


class Solver:
    """CSP solver with solution counting for uniqueness verification."""

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
        raw_paths = []
        for c in range(self.n):
            raw_paths.append(trace_path(self.grid, self.n, 0, c, 0))
        for c in range(self.n):
            raw_paths.append(trace_path(self.grid, self.n, self.n - 1, c, 2))
        for r in range(self.n):
            raw_paths.append(trace_path(self.grid, self.n, r, 0, 1))
        for r in range(self.n):
            raw_paths.append(trace_path(self.grid, self.n, r, self.n - 1, 3))

        self.paths = []
        for path_cells, clue in zip(raw_paths, clues):
            indices, refls = [], []
            for r, c, refl in path_cells:
                if (r, c) in self.cell_index:
                    indices.append(self.cell_index[(r, c)])
                    refls.append(refl)
            self.paths.append((indices, refls, clue))

    def count_solutions(self, limit=2):
        """Count solutions up to limit (for uniqueness verification)."""
        self._count = 0
        self._limit = limit
        self._count_search([frozenset({0, 1, 2}) for _ in range(self.num_cells)])
        return self._count

    def _count_search(self, domains):
        if self._count >= self._limit:
            return
        domains = self._propagate(list(domains))
        if domains is None:
            return
        if all(len(d) == 1 for d in domains):
            assignment = [next(iter(d)) for d in domains]
            if self._verify(assignment):
                self._count += 1
            return

        best = min(
            (ci for ci in range(self.num_cells) if len(domains[ci]) > 1),
            key=lambda ci: len(domains[ci]),
            default=None,
        )
        if best is None:
            return
        for m in sorted(domains[best]):
            if self._count >= self._limit:
                return
            nd = list(domains)
            nd[best] = frozenset({m})
            self._count_search(nd)

    def _propagate(self, domains):
        domains = [set(d) for d in domains]
        changed = True
        while changed:
            changed = False
            for m in range(3):
                must = sum(1 for d in domains if d == {m})
                can = sum(1 for d in domains if m in d)
                if must > self.targets[m] or can < self.targets[m]:
                    return None
                if must == self.targets[m]:
                    for ci in range(self.num_cells):
                        if len(domains[ci]) > 1 and m in domains[ci]:
                            domains[ci].discard(m)
                            changed = True
                            if not domains[ci]:
                                return None
                if can == self.targets[m]:
                    for ci in range(self.num_cells):
                        if m in domains[ci] and len(domains[ci]) > 1:
                            domains[ci] = {m}
                            changed = True
            for indices, refls, target in self.paths:
                assigned_vis = 0
                unassigned = []
                for ci, refl in zip(indices, refls):
                    if len(domains[ci]) == 1:
                        assigned_vis += visibility_int(next(iter(domains[ci])), refl)
                    else:
                        mn = min(visibility_int(mv, refl) for mv in domains[ci])
                        mx = max(visibility_int(mv, refl) for mv in domains[ci])
                        unassigned.append((ci, refl, mn, mx))
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
                                  if visibility_int(mv, refl) == mx}
                            if nd != domains[ci]:
                                domains[ci] = nd
                                changed = True
                                if not domains[ci]:
                                    return None
                if remaining == u_min:
                    for ci, refl, mn, mx in unassigned:
                        if mn < mx:
                            nd = {mv for mv in domains[ci]
                                  if visibility_int(mv, refl) == mn}
                            if nd != domains[ci]:
                                domains[ci] = nd
                                changed = True
                                if not domains[ci]:
                                    return None
        return [frozenset(d) for d in domains]

    def _verify(self, assignment):
        counts = [0, 0, 0]
        for m in assignment:
            counts[m] += 1
        if counts != self.targets:
            return False
        for indices, refls, target in self.paths:
            vis = sum(visibility_int(assignment[ci], refl)
                      for ci, refl in zip(indices, refls))
            if vis != target:
                return False
        return True


def encode_grid(grid, n):
    """Encode puzzle grid into compact letter-based format."""
    desc = ""
    empty_count = 0
    for r in range(n):
        for c in range(n):
            cell = grid[r][c]
            if cell == '.':
                empty_count += 1
            else:
                while empty_count > 26:
                    desc += 'z'
                    empty_count -= 26
                if empty_count > 0:
                    desc += chr(ord('a') + empty_count - 1)
                    empty_count = 0
                if cell == '\\':
                    desc += 'L'
                elif cell == '/':
                    desc += 'R'
    while empty_count > 26:
        desc += 'z'
        empty_count -= 26
    if empty_count > 0:
        desc += chr(ord('a') + empty_count - 1)
    return desc


def compute_clues(grid, n):
    """Compute all edge clues from a solved grid (with character monsters)."""
    top, bottom, left, right = [], [], [], []
    for col in range(n):
        path = trace_path(grid, n, 0, col, 0)
        vis = sum(visibility_char(grid[r][c], refl) for r, c, refl in path)
        top.append(vis)
    for col in range(n):
        path = trace_path(grid, n, n - 1, col, 2)
        vis = sum(visibility_char(grid[r][c], refl) for r, c, refl in path)
        bottom.append(vis)
    for row in range(n):
        path = trace_path(grid, n, row, 0, 1)
        vis = sum(visibility_char(grid[r][c], refl) for r, c, refl in path)
        left.append(vis)
    for row in range(n):
        path = trace_path(grid, n, row, n - 1, 3)
        vis = sum(visibility_char(grid[r][c], refl) for r, c, refl in path)
        right.append(vis)
    return top, bottom, left, right


def generate_puzzle(n, num_mirrors, seed_start, max_attempts=500):
    """Generate a puzzle with guaranteed unique solution.

    Constructs random solved grids, computes edge clues, strips monster
    info, then verifies the resulting puzzle has exactly one solution.
    Retries with different random seeds until a unique puzzle is found.
    """
    for seed in range(seed_start, seed_start + max_attempts):
        random.seed(seed)

        grid = [['.' for _ in range(n)] for _ in range(n)]
        positions = [(r, c) for r in range(n) for c in range(n)]
        random.shuffle(positions)

        for r, c in positions[:num_mirrors]:
            grid[r][c] = random.choice(['/', '\\'])

        for r in range(n):
            for c in range(n):
                if grid[r][c] == '.':
                    grid[r][c] = random.choice(['G', 'V', 'Z'])

        top, bottom, left, right = compute_clues(grid, n)

        g = sum(row.count('G') for row in grid)
        v = sum(row.count('V') for row in grid)
        z = sum(row.count('Z') for row in grid)

        puzzle_grid = [
            ['.' if cell in ('G', 'V', 'Z') else cell for cell in row]
            for row in grid
        ]

        puzzle = {
            'n': n, 'grid': puzzle_grid,
            'top': top, 'bottom': bottom, 'left': left, 'right': right,
            'ghosts': g, 'vampires': v, 'zombies': z,
        }

        solver = Solver(puzzle)
        nsol = solver.count_solutions(2)

        if nsol == 1:
            desc = encode_grid(puzzle_grid, n)
            clues = top + bottom + left + right + [g, v, z]
            game_desc = f"{n}x{n}:{desc},{','.join(map(str, clues))}"
            return game_desc, seed

    raise RuntimeError(
        f"Could not find unique {n}x{n} puzzle in {max_attempts} attempts"
    )


def main():
    gen_dir = Path('/app/generated')
    gen_dir.mkdir(exist_ok=True)

    specs = [
        ('gen_4x4.txt', 4, 6, 0),
        ('gen_5x5.txt', 5, 10, 0),
        ('gen_7x7.txt', 7, 32, 0),
    ]

    for filename, n, mirrors, seed_start in specs:
        print(f"Generating {filename} ({n}x{n}, {mirrors} mirrors)...")
        game_desc, seed = generate_puzzle(n, mirrors, seed_start)
        filepath = gen_dir / filename
        with open(filepath, 'w') as f:
            f.write(game_desc + '\n')
        print(f"  Written to {filepath} (seed={seed})")


if __name__ == '__main__':
    main()
