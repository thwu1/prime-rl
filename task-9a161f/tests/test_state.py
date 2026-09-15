"""Verification tests for Undead puzzle solutions and generator."""

import os
import subprocess
import pytest


def parse_game_description(filepath):
    """Parse a game description file into puzzle components.

    Format: WxH:GRID_DESC,C1,C2,...,G_COUNT,V_COUNT,Z_COUNT

    Grid encoding (row-major scan):
      - lowercase letters a-z represent 1-26 consecutive empty cells
      - 'L' represents a backslash mirror
      - 'R' represents a forward-slash mirror

    Clue order after grid: top L-R, bottom L-R, left T-B, right T-B,
    then total ghost/vampire/zombie counts.
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

    assert len(grid) == n, f"Grid decode error: got {len(grid)} rows, expected {n}"

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
    """Trace a sight line through the grid, returning visited cells with
    reflection state.  Direction: 0=DOWN, 1=RIGHT, 2=UP, 3=LEFT."""
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


def compute_visibility(monster, reflected):
    """Return 1 if monster is visible given the current reflection state."""
    if monster == 'Z':
        return 1
    elif monster == 'G':
        return 1 if not reflected else 0
    elif monster == 'V':
        return 1 if reflected else 0
    return 0


def parse_solution(filepath, n):
    """Parse a solution file into a grid."""
    with open(filepath) as f:
        lines = [line.rstrip('\n') for line in f if line.strip()]
    assert len(lines) >= n, f"Solution file has {len(lines)} lines, expected at least {n}"
    grid = [list(lines[i]) for i in range(n)]
    return grid


def verify_solution(puzzle, solution):
    """Verify that a solution satisfies all puzzle constraints."""
    n = puzzle['n']
    errors = []

    if len(solution) != n:
        errors.append(f"Solution has {len(solution)} rows, expected {n}")
        return errors
    for r in range(n):
        if len(solution[r]) != n:
            errors.append(f"Row {r} has {len(solution[r])} cols, expected {n}")
            return errors

    for r in range(n):
        for c in range(n):
            if puzzle['grid'][r][c] in ('/', '\\'):
                if solution[r][c] != puzzle['grid'][r][c]:
                    errors.append(
                        f"Mirror at ({r},{c}) changed from "
                        f"'{puzzle['grid'][r][c]}' to '{solution[r][c]}'"
                    )

    for r in range(n):
        for c in range(n):
            if puzzle['grid'][r][c] == '.':
                if solution[r][c] not in ('G', 'V', 'Z'):
                    errors.append(
                        f"Cell ({r},{c}) has invalid value '{solution[r][c]}'"
                    )

    if errors:
        return errors

    g_count = sum(row.count('G') for row in solution)
    v_count = sum(row.count('V') for row in solution)
    z_count = sum(row.count('Z') for row in solution)

    if g_count != puzzle['ghosts']:
        errors.append(f"Ghost count: got {g_count}, expected {puzzle['ghosts']}")
    if v_count != puzzle['vampires']:
        errors.append(f"Vampire count: got {v_count}, expected {puzzle['vampires']}")
    if z_count != puzzle['zombies']:
        errors.append(f"Zombie count: got {z_count}, expected {puzzle['zombies']}")

    for c_idx in range(n):
        path = trace_path(solution, n, 0, c_idx, 0)
        vis = sum(compute_visibility(solution[r][c], refl) for r, c, refl in path)
        if vis != puzzle['top'][c_idx]:
            errors.append(f"Top clue col {c_idx}: visible={vis}, expected={puzzle['top'][c_idx]}")

    for c_idx in range(n):
        path = trace_path(solution, n, n - 1, c_idx, 2)
        vis = sum(compute_visibility(solution[r][c], refl) for r, c, refl in path)
        if vis != puzzle['bottom'][c_idx]:
            errors.append(f"Bottom clue col {c_idx}: visible={vis}, expected={puzzle['bottom'][c_idx]}")

    for r_idx in range(n):
        path = trace_path(solution, n, r_idx, 0, 1)
        vis = sum(compute_visibility(solution[r][c], refl) for r, c, refl in path)
        if vis != puzzle['left'][r_idx]:
            errors.append(f"Left clue row {r_idx}: visible={vis}, expected={puzzle['left'][r_idx]}")

    for r_idx in range(n):
        path = trace_path(solution, n, r_idx, n - 1, 3)
        vis = sum(compute_visibility(solution[r][c], refl) for r, c, refl in path)
        if vis != puzzle['right'][r_idx]:
            errors.append(f"Right clue row {r_idx}: visible={vis}, expected={puzzle['right'][r_idx]}")

    return errors


class SolutionCounter:
    """Independent solution enumerator for uniqueness verification.

    Uses constraint propagation + backtracking to count solutions up to
    a given limit.  Monster encoding: 0=Ghost, 1=Vampire, 2=Zombie.
    """

    def __init__(self, puzzle, limit=2):
        self.n = puzzle['n']
        self.grid = puzzle['grid']
        self.targets = [puzzle['ghosts'], puzzle['vampires'], puzzle['zombies']]
        self.limit = limit
        self.count = 0

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

    @staticmethod
    def _vis(monster, reflected):
        if monster == 2:
            return 1
        if monster == 0:
            return 0 if reflected else 1
        return 1 if reflected else 0

    def count_solutions(self):
        self.count = 0
        self._search([frozenset({0, 1, 2}) for _ in range(self.num_cells)])
        return self.count

    def _search(self, domains):
        if self.count >= self.limit:
            return
        domains = self._propagate(list(domains))
        if domains is None:
            return
        if all(len(d) == 1 for d in domains):
            assignment = [next(iter(d)) for d in domains]
            if self._verify(assignment):
                self.count += 1
            return

        best = min(
            (ci for ci in range(self.num_cells) if len(domains[ci]) > 1),
            key=lambda ci: len(domains[ci]),
            default=None,
        )
        if best is None:
            return
        for m in sorted(domains[best]):
            if self.count >= self.limit:
                return
            nd = list(domains)
            nd[best] = frozenset({m})
            self._search(nd)

    def _propagate(self, domains):
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
                        assigned_vis += self._vis(next(iter(domains[ci])), refl)
                    else:
                        mn = min(self._vis(mv, refl) for mv in domains[ci])
                        mx = max(self._vis(mv, refl) for mv in domains[ci])
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
                                  if self._vis(mv, refl) == mx}
                            if nd != domains[ci]:
                                domains[ci] = nd
                                changed = True
                                if not domains[ci]:
                                    return None

                if remaining == u_min:
                    for ci, refl, mn, mx in unassigned:
                        if mn < mx:
                            nd = {mv for mv in domains[ci]
                                  if self._vis(mv, refl) == mn}
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
            vis = sum(self._vis(assignment[ci], refl)
                      for ci, refl in zip(indices, refls))
            if vis != target:
                return False
        return True


BINARY_PATH = '/app/tools/undead-tool'


def get_puzzle_files():
    """Find all provided puzzle files."""
    puzzles_dir = '/app/puzzles'
    return sorted(
        f for f in os.listdir(puzzles_dir)
        if f.endswith('.txt')
    )


def get_generated_files():
    """Find all generated puzzle files."""
    gen_dir = '/app/generated'
    if not os.path.isdir(gen_dir):
        return []
    return sorted(
        f for f in os.listdir(gen_dir)
        if f.endswith('.txt')
    )


class TestSolverInfrastructure:
    """Verify the solver and its outputs exist."""

    def test_solver_exists(self):
        assert os.path.exists('/app/solver.py'), "Solver not found at /app/solver.py"

    def test_solutions_directory_exists(self):
        assert os.path.isdir('/app/solutions'), "Solutions directory not found"
        sol_files = [f for f in os.listdir('/app/solutions') if f.endswith('.txt')]
        assert len(sol_files) > 0, "No solution files found in /app/solutions/"

    def test_all_provided_puzzles_have_solutions(self):
        for pf in get_puzzle_files():
            sol_path = f'/app/solutions/{pf}'
            assert os.path.exists(sol_path), f"Solution missing for {pf}"


class TestProvidedSolutions:
    """Verify solutions for all provided puzzles are correct."""

    def _verify_puzzle(self, filename):
        puzzle_path = f'/app/puzzles/{filename}'
        solution_path = f'/app/solutions/{filename}'
        assert os.path.exists(puzzle_path), f"Puzzle {puzzle_path} not found"
        assert os.path.exists(solution_path), f"Solution {solution_path} not found"
        puzzle = parse_game_description(puzzle_path)
        solution = parse_solution(solution_path, puzzle['n'])
        errors = verify_solution(puzzle, solution)
        assert len(errors) == 0, (
            f"Solution for {filename} has {len(errors)} error(s):\n" +
            "\n".join(f"  - {e}" for e in errors)
        )

    def test_puzzle_1_solution(self):
        """Verify solution for puzzle 1 (4x4)."""
        self._verify_puzzle('puzzle_1.txt')

    def test_puzzle_2_solution(self):
        """Verify solution for puzzle 2 (5x5)."""
        self._verify_puzzle('puzzle_2.txt')

    def test_puzzle_3_solution(self):
        """Verify solution for puzzle 3 (6x6)."""
        self._verify_puzzle('puzzle_3.txt')

    def test_puzzle_4_solution(self):
        """Verify solution for puzzle 4 (8x8)."""
        self._verify_puzzle('puzzle_4.txt')

    def test_puzzle_5_solution(self):
        """Verify solution for extra test-time puzzle (5x5)."""
        self._verify_puzzle('puzzle_5.txt')


class TestGeneratorInfrastructure:
    """Verify the generator and its outputs exist."""

    def test_generator_exists(self):
        assert os.path.exists('/app/generator.py'), \
            "Generator not found at /app/generator.py"

    def test_generated_directory_exists(self):
        assert os.path.isdir('/app/generated'), \
            "Generated puzzles directory not found at /app/generated/"

    def test_gen_4x4_exists(self):
        assert os.path.exists('/app/generated/gen_4x4.txt'), \
            "Generated 4x4 puzzle not found"

    def test_gen_5x5_exists(self):
        assert os.path.exists('/app/generated/gen_5x5.txt'), \
            "Generated 5x5 puzzle not found"

    def test_gen_7x7_exists(self):
        assert os.path.exists('/app/generated/gen_7x7.txt'), \
            "Generated 7x7 puzzle not found"


class TestGeneratedPuzzleFormat:
    """Verify generated puzzles have correct dimensions and mirror counts."""

    def test_gen_4x4_format(self):
        puzzle = parse_game_description('/app/generated/gen_4x4.txt')
        assert puzzle['n'] == 4, f"Expected 4x4, got {puzzle['n']}x{puzzle['n']}"
        mirrors = sum(
            1 for r in range(4) for c in range(4)
            if puzzle['grid'][r][c] in ('/', '\\')
        )
        assert mirrors >= 5, f"Expected >= 5 mirrors, got {mirrors}"

    def test_gen_5x5_format(self):
        puzzle = parse_game_description('/app/generated/gen_5x5.txt')
        assert puzzle['n'] == 5, f"Expected 5x5, got {puzzle['n']}x{puzzle['n']}"
        mirrors = sum(
            1 for r in range(5) for c in range(5)
            if puzzle['grid'][r][c] in ('/', '\\')
        )
        assert mirrors >= 8, f"Expected >= 8 mirrors, got {mirrors}"

    def test_gen_7x7_format(self):
        puzzle = parse_game_description('/app/generated/gen_7x7.txt')
        assert puzzle['n'] == 7, f"Expected 7x7, got {puzzle['n']}x{puzzle['n']}"
        mirrors = sum(
            1 for r in range(7) for c in range(7)
            if puzzle['grid'][r][c] in ('/', '\\')
        )
        assert mirrors >= 20, f"Expected >= 20 mirrors, got {mirrors}"


class TestGeneratedSolutions:
    """Verify solutions for generated puzzles are correct."""

    def _verify_generated(self, filename):
        puzzle_path = f'/app/generated/{filename}'
        sol_path = f'/app/solutions/{filename}'
        assert os.path.exists(puzzle_path), f"{puzzle_path} not found"
        assert os.path.exists(sol_path), f"Solution missing for generated {filename}"
        puzzle = parse_game_description(puzzle_path)
        solution = parse_solution(sol_path, puzzle['n'])
        errors = verify_solution(puzzle, solution)
        assert len(errors) == 0, (
            f"Solution for generated {filename} has {len(errors)} error(s):\n" +
            "\n".join(f"  - {e}" for e in errors)
        )

    def test_gen_4x4_solution(self):
        self._verify_generated('gen_4x4.txt')

    def test_gen_5x5_solution(self):
        self._verify_generated('gen_5x5.txt')

    def test_gen_7x7_solution(self):
        self._verify_generated('gen_7x7.txt')


class TestGeneratedUniqueness:
    """Verify each generated puzzle has exactly one valid solution.

    Uses an independent solution counter (CSP solver that continues
    searching after finding the first solution) to prove uniqueness.
    """

    def _check_unique(self, filename):
        puzzle_path = f'/app/generated/{filename}'
        assert os.path.exists(puzzle_path), f"{puzzle_path} not found"
        puzzle = parse_game_description(puzzle_path)
        counter = SolutionCounter(puzzle, limit=2)
        nsol = counter.count_solutions()
        assert nsol == 1, (
            f"Generated puzzle {filename} has {nsol} solution(s), "
            f"expected exactly 1"
        )

    def test_gen_4x4_unique(self):
        """4x4 puzzle must have a unique solution."""
        self._check_unique('gen_4x4.txt')

    def test_gen_5x5_unique(self):
        """5x5 puzzle must have a unique solution."""
        self._check_unique('gen_5x5.txt')

    def test_gen_7x7_unique(self):
        """7x7 puzzle must have a unique solution."""
        self._check_unique('gen_7x7.txt')


class TestBinaryCrossValidation:
    """Cross-validate solutions using the compiled C verification tool."""

    def test_binary_built(self):
        assert os.path.exists(BINARY_PATH), (
            f"undead-tool binary not found at {BINARY_PATH}"
        )

    def _binary_verify(self, puzzle_dir, filename):
        puzzle_path = f'{puzzle_dir}/{filename}'
        solution_path = f'/app/solutions/{filename}'
        assert os.path.exists(puzzle_path), f"Puzzle {puzzle_path} missing"
        assert os.path.exists(solution_path), f"Solution {solution_path} missing"

        with open(puzzle_path) as f:
            game_id = f.read().strip()

        result = subprocess.run(
            [BINARY_PATH, 'verify', game_id, solution_path],
            capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, (
            f"Binary verify failed for {filename}:\n{result.stderr}"
        )
        assert 'OK' in result.stdout, (
            f"Binary verify did not output OK for {filename}: {result.stdout}"
        )

    def test_binary_puzzle_1(self):
        self._binary_verify('/app/puzzles', 'puzzle_1.txt')

    def test_binary_puzzle_2(self):
        self._binary_verify('/app/puzzles', 'puzzle_2.txt')

    def test_binary_puzzle_3(self):
        self._binary_verify('/app/puzzles', 'puzzle_3.txt')

    def test_binary_puzzle_4(self):
        self._binary_verify('/app/puzzles', 'puzzle_4.txt')

    def test_binary_puzzle_5(self):
        self._binary_verify('/app/puzzles', 'puzzle_5.txt')

    def test_binary_gen_4x4(self):
        self._binary_verify('/app/generated', 'gen_4x4.txt')

    def test_binary_gen_5x5(self):
        self._binary_verify('/app/generated', 'gen_5x5.txt')

    def test_binary_gen_7x7(self):
        self._binary_verify('/app/generated', 'gen_7x7.txt')


class TestValidationPipeline:
    """Test that validate.sh exists and works correctly."""

    def test_validate_sh_exists(self):
        assert os.path.exists('/app/validate.sh'), (
            "validate.sh not found at /app/validate.sh"
        )

    def test_validate_sh_runs_successfully(self):
        assert os.path.exists('/app/validate.sh'), "validate.sh missing"
        result = subprocess.run(
            ['bash', '/app/validate.sh'],
            capture_output=True, text=True, timeout=240,
            cwd='/app'
        )
        assert result.returncode == 0, (
            f"validate.sh failed (exit {result.returncode}):\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
