"""
Sokoban solver verification tests.
Validates that the solver is a compiled ELF binary with a working build system,
and produces valid LURD solutions for all puzzles.

"""
import glob
import os
import shutil
import subprocess

import pytest

PUZZLE_DIR = "/app/puzzles"
SOLVER = "/app/solver"

DIR_MAP = {
    'u': (-1, 0), 'd': (1, 0), 'l': (0, -1), 'r': (0, 1),
    'U': (-1, 0), 'D': (1, 0), 'L': (0, -1), 'R': (0, 1),
}


def parse_puzzle(path):
    """Parse an XSB puzzle file. Returns walls, player, boxes, goals."""
    lines = []
    with open(path) as f:
        for raw in f:
            s = raw.rstrip('\n\r')
            if s.startswith(';'):
                continue
            if not s.strip():
                if lines:
                    break
                continue
            lines.append(s)

    walls = set()
    boxes = set()
    goals = set()
    player = None

    for r, line in enumerate(lines):
        for c, ch in enumerate(line):
            p = (r, c)
            if ch == '#':
                walls.add(p)
            elif ch == '@':
                player = p
            elif ch == '+':
                player = p
                goals.add(p)
            elif ch == '$':
                boxes.add(p)
            elif ch == '*':
                boxes.add(p)
                goals.add(p)
            elif ch == '.':
                goals.add(p)

    assert player is not None, f"No player found in {path}"
    assert len(boxes) == len(goals), (
        f"Box count ({len(boxes)}) != goal count ({len(goals)}) in {path}"
    )
    return walls, player, boxes, goals


def verify_solution(walls, player, boxes, goals, solution):
    """
    Simulate a LURD solution on the board.
    Returns (is_valid: bool, message: str).
    Treats any move into a box cell as a push regardless of case.
    """
    boxes = set(boxes)
    pr, pc = player

    for i, ch in enumerate(solution):
        if ch not in DIR_MAP:
            return False, f"Invalid character '{ch}' at position {i}"

        dr, dc = DIR_MAP[ch]
        nr, nc = pr + dr, pc + dc

        if (nr, nc) in walls:
            return False, f"Step {i} ('{ch}'): moved into wall at ({nr},{nc})"

        if (nr, nc) in boxes:
            br, bc = nr + dr, nc + dc
            if (br, bc) in walls:
                return False, f"Step {i} ('{ch}'): pushed box into wall at ({br},{bc})"
            if (br, bc) in boxes:
                return False, f"Step {i} ('{ch}'): pushed box into another box at ({br},{bc})"
            boxes.remove((nr, nc))
            boxes.add((br, bc))

        pr, pc = nr, nc

    if boxes == goals:
        return True, "All boxes on goals"
    else:
        missing = boxes - goals
        extra_goals = goals - boxes
        return False, (
            f"Not all boxes on goals. "
            f"Boxes not on goals: {sorted(missing)}; "
            f"Unoccupied goals: {sorted(extra_goals)}"
        )


def get_puzzle_files():
    """List all puzzle files sorted by name."""
    if not os.path.isdir(PUZZLE_DIR):
        return []
    return sorted(f for f in os.listdir(PUZZLE_DIR) if f.endswith('.xsb'))


class TestBuildInfrastructure:
    """Tests verifying the solver is properly compiled from source."""

    def test_solver_is_elf_binary(self):
        """The solver must be a compiled ELF binary, not an interpreted script."""
        assert os.path.isfile(SOLVER), (
            f"Solver not found at {SOLVER}."
        )
        with open(SOLVER, "rb") as f:
            magic = f.read(4)
        assert magic == b'\x7fELF', (
            f"Solver at {SOLVER} must be a compiled ELF binary (got magic: {magic!r}). "
            f"Use g++/gcc and cmake/make to compile C/C++ source code."
        )

    def test_build_system_present(self):
        """A build system (CMakeLists.txt or Makefile) must exist in /app/."""
        has_cmake = os.path.isfile("/app/CMakeLists.txt")
        has_makefile = os.path.isfile("/app/Makefile")
        assert has_cmake or has_makefile, (
            "No build system found in /app/. "
            "Create a CMakeLists.txt or Makefile to build the solver from source."
        )

    def test_source_code_present(self):
        """C/C++ source files must be present for reproducible builds."""
        sources = (
            glob.glob("/app/*.cpp") + glob.glob("/app/*.c") +
            glob.glob("/app/src/*.cpp") + glob.glob("/app/src/*.c")
        )
        assert len(sources) > 0, (
            "No C/C++ source files found in /app/ or /app/src/. "
            "The solver must be built from compilable source code."
        )

    def test_build_system_functional(self):
        """The build system can configure and compile without errors."""
        build_dir = "/app/_build_verify"
        try:
            if os.path.isfile("/app/CMakeLists.txt"):
                os.makedirs(build_dir, exist_ok=True)
                r = subprocess.run(
                    ["cmake", "-S", "/app", "-B", build_dir],
                    capture_output=True, text=True, timeout=60
                )
                assert r.returncode == 0, (
                    f"cmake configure failed: {r.stderr[:500]}"
                )
                r = subprocess.run(
                    ["cmake", "--build", build_dir, "--", "-j1"],
                    capture_output=True, text=True, timeout=120
                )
                assert r.returncode == 0, (
                    f"cmake build failed: {r.stderr[:500]}"
                )
            elif os.path.isfile("/app/Makefile"):
                r = subprocess.run(
                    ["make", "-C", "/app", "-n"],
                    capture_output=True, text=True, timeout=30
                )
                assert r.returncode == 0, (
                    f"make dry-run failed: {r.stderr[:500]}"
                )
        finally:
            shutil.rmtree(build_dir, ignore_errors=True)


class TestSolverCorrectness:
    """Tests verifying the solver produces valid solutions."""

    @pytest.fixture
    def solver_exists(self):
        """Check that the solver binary exists."""
        assert os.path.isfile(SOLVER), (
            f"Solver not found at {SOLVER}."
        )

    @pytest.mark.parametrize("puzzle_file", get_puzzle_files())
    def test_solve_puzzle(self, solver_exists, puzzle_file):
        """Run solver on a puzzle and verify the LURD solution."""
        puzzle_path = os.path.join(PUZZLE_DIR, puzzle_file)

        result = subprocess.run(
            [SOLVER, puzzle_path],
            capture_output=True,
            text=True,
            timeout=180,
        )

        assert result.returncode == 0, (
            f"Solver failed on {puzzle_file} with exit code {result.returncode}. "
            f"stderr: {result.stderr[:500]}"
        )

        solution = result.stdout.strip()
        assert len(solution) > 0, f"Empty solution output for {puzzle_file}"
        assert all(c in 'udlrUDLR' for c in solution), (
            f"Solution for {puzzle_file} contains invalid characters: "
            f"{set(solution) - set('udlrUDLR')}"
        )

        walls, player, boxes, goals = parse_puzzle(puzzle_path)
        valid, msg = verify_solution(walls, player, boxes, goals, solution)
        assert valid, f"Invalid solution for {puzzle_file}: {msg}"
