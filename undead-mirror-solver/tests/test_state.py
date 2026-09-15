
"""
Independent verification of generated Undead puzzle instances.
Checks format, solution correctness, uniqueness (via SAT), and structural constraints.
"""

import json
import os
import subprocess
import tempfile

import pytest

GENERATED_DIR = "/app/generated"

PUZZLE_SPECS = {
    "puzzle_01": {"w": 5, "h": 5, "min_mirrors": 2, "max_mirrors": 5},
    "puzzle_02": {"w": 5, "h": 5, "min_mirrors": 8, "max_mirrors": 12},
    "puzzle_03": {"w": 7, "h": 7, "min_mirrors": 4, "max_mirrors": 9},
    "puzzle_04": {"w": 7, "h": 7, "min_mirrors": 16, "max_mirrors": 22},
    "puzzle_05": {"w": 9, "h": 9, "min_mirrors": 6, "max_mirrors": 14},
    "puzzle_06": {"w": 9, "h": 9, "min_mirrors": 28, "max_mirrors": 36},
}

PUZZLE_NAMES = list(PUZZLE_SPECS.keys())


# ── Parsing ──────────────────────────────────────────────────────────


def parse_desc(path):
    """Parse a .desc puzzle description file (independent implementation)."""
    with open(path) as f:
        raw = f.read().strip()

    header, body = raw.split(":")
    w, h = map(int, header.split("x"))
    tokens = body.split(",")

    num_clues = 2 * (w + h)
    top = [int(tokens[i]) for i in range(w)]
    bottom = [int(tokens[w + i]) for i in range(w)]
    left = [int(tokens[2 * w + i]) for i in range(h)]
    right = [int(tokens[2 * w + h + i]) for i in range(h)]

    g_count = int(tokens[num_clues])
    v_count = int(tokens[num_clues + 1])
    z_count = int(tokens[num_clues + 2])

    rle = tokens[num_clues + 3]
    flat = []
    for ch in rle:
        if ch == "L":
            flat.append("\\")
        elif ch == "R":
            flat.append("/")
        elif "a" <= ch <= "z":
            flat.extend(["."] * (ord(ch) - ord("a") + 1))
        else:
            raise ValueError(f"Bad RLE character: {ch!r}")

    assert len(flat) == w * h, f"RLE decoded to {len(flat)} cells, expected {w * h}"

    mirrors = {}
    empties = []
    for idx, cell in enumerate(flat):
        r, c = idx // w, idx % w
        if cell in ("\\", "/"):
            mirrors[(r, c)] = cell
        else:
            empties.append((r, c))

    return {
        "w": w,
        "h": h,
        "top": top,
        "bottom": bottom,
        "left": left,
        "right": right,
        "g_count": g_count,
        "v_count": v_count,
        "z_count": z_count,
        "mirrors": mirrors,
        "empties": empties,
    }


# ── Sight-line tracing ──────────────────────────────────────────────


def trace_line(grid, h, w, sr, sc, dr, dc):
    """Trace a line of sight and count visible monsters."""
    r, c = sr, sc
    reflected = False
    count = 0
    visited = set()

    while 0 <= r < h and 0 <= c < w:
        state = (r, c, dr, dc)
        if state in visited:
            raise ValueError(f"Infinite loop at ({r},{c}) dir ({dr},{dc})")
        visited.add(state)

        cell = grid[r][c]
        if cell == "\\":
            dr, dc = dc, dr
            reflected = True
        elif cell == "/":
            dr, dc = -dc, -dr
            reflected = True
        else:
            if cell == "Z":
                count += 1
            elif cell == "G" and not reflected:
                count += 1
            elif cell == "V" and reflected:
                count += 1

        r += dr
        c += dc

    return count


# ── Solution verification ───────────────────────────────────────────


def verify_solution(puzzle, grid):
    """Return list of error strings; empty means valid."""
    errors = []
    w, h = puzzle["w"], puzzle["h"]

    if len(grid) != h:
        return [f"Expected {h} rows, got {len(grid)}"]
    for ri, row in enumerate(grid):
        if len(row) != w:
            return [f"Row {ri}: expected {w} cols, got {len(row)}"]

    # Mirrors must match
    for (r, c), m in puzzle["mirrors"].items():
        if grid[r][c] != m:
            errors.append(f"({r},{c}): expected mirror {m!r}, got {grid[r][c]!r}")

    # Monster cells
    counts = {"G": 0, "V": 0, "Z": 0}
    for r in range(h):
        for c in range(w):
            cell = grid[r][c]
            if (r, c) not in puzzle["mirrors"]:
                if cell not in ("G", "V", "Z"):
                    errors.append(f"({r},{c}): invalid cell {cell!r}")
                else:
                    counts[cell] += 1

    if counts["G"] != puzzle["g_count"]:
        errors.append(f"Ghost count {counts['G']} != {puzzle['g_count']}")
    if counts["V"] != puzzle["v_count"]:
        errors.append(f"Vampire count {counts['V']} != {puzzle['v_count']}")
    if counts["Z"] != puzzle["z_count"]:
        errors.append(f"Zombie count {counts['Z']} != {puzzle['z_count']}")

    if errors:
        return errors

    # Sight-line clues
    for c in range(w):
        vis = trace_line(grid, h, w, 0, c, 1, 0)
        if vis != puzzle["top"][c]:
            errors.append(f"top[{c}]: {vis} != {puzzle['top'][c]}")
    for c in range(w):
        vis = trace_line(grid, h, w, h - 1, c, -1, 0)
        if vis != puzzle["bottom"][c]:
            errors.append(f"bottom[{c}]: {vis} != {puzzle['bottom'][c]}")
    for r in range(h):
        vis = trace_line(grid, h, w, r, 0, 0, 1)
        if vis != puzzle["left"][r]:
            errors.append(f"left[{r}]: {vis} != {puzzle['left'][r]}")
    for r in range(h):
        vis = trace_line(grid, h, w, r, w - 1, 0, -1)
        if vis != puzzle["right"][r]:
            errors.append(f"right[{r}]: {vis} != {puzzle['right'][r]}")

    return errors


# ── SAT-based uniqueness checker ────────────────────────────────────


class _SATUniqueness:
    """Encode an Undead puzzle as CNF and check uniqueness via minisat."""

    def __init__(self, puzzle):
        self.w = puzzle["w"]
        self.h = puzzle["h"]
        self.mirrors = puzzle["mirrors"]
        self.cells = puzzle["empties"]
        self.n = len(self.cells)
        self.cidx = {c: i for i, c in enumerate(self.cells)}
        self._next = 3 * self.n + 1
        self._cls = []
        self._gc = puzzle["g_count"]
        self._vc = puzzle["v_count"]
        self._zc = puzzle["z_count"]
        self._top = puzzle["top"]
        self._bot = puzzle["bottom"]
        self._lft = puzzle["left"]
        self._rgt = puzzle["right"]

    # Variable for cell i, type t (0=G, 1=V, 2=Z)
    def _cv(self, i, t):
        return 3 * i + t + 1

    def _fresh(self):
        v = self._next
        self._next += 1
        return v

    def _add(self, lits):
        self._cls.append(list(lits))

    # ── Path tracing ──

    def _path(self, sr, sc, dr, dc):
        """Return [(cell_index, is_reflected)] for non-mirror cells on path."""
        out = []
        r, c = sr, sc
        refl = False
        seen = set()
        while 0 <= r < self.h and 0 <= c < self.w:
            s = (r, c, dr, dc)
            if s in seen:
                break
            seen.add(s)
            if (r, c) in self.mirrors:
                m = self.mirrors[(r, c)]
                if m == "\\":
                    dr, dc = dc, dr
                else:
                    dr, dc = -dc, -dr
                refl = True
            else:
                out.append((self.cidx[(r, c)], refl))
            r += dr
            c += dc
        return out

    # ── Cardinality encoding (Sinz sequential counter) ──

    def _at_most_k(self, vs, k):
        n = len(vs)
        if k >= n:
            return
        if k == 0:
            for v in vs:
                self._add([-v])
            return
        s = [[self._fresh() for _ in range(k)] for _ in range(n)]
        self._add([-vs[0], s[0][0]])
        for j in range(1, k):
            self._add([-s[0][j]])
        for i in range(1, n):
            self._add([-vs[i], s[i][0]])
            self._add([-s[i - 1][0], s[i][0]])
            for j in range(1, k):
                self._add([-vs[i], -s[i - 1][j - 1], s[i][j]])
                self._add([-s[i - 1][j], s[i][j]])
            self._add([-vs[i], -s[i - 1][k - 1]])

    def _exactly_k(self, vs, k):
        n = len(vs)
        if n == 0:
            if k != 0:
                self._add([])
            return
        if k == 0:
            for v in vs:
                self._add([-v])
            return
        if k == n:
            for v in vs:
                self._add([v])
            return
        self._at_most_k(vs, k)
        self._at_most_k([-v for v in vs], n - k)

    # ── Full encoding ──

    def encode(self):
        # One type per cell
        for i in range(self.n):
            g, v, z = self._cv(i, 0), self._cv(i, 1), self._cv(i, 2)
            self._add([g, v, z])
            self._add([-g, -v])
            self._add([-g, -z])
            self._add([-v, -z])

        # Global counts
        self._exactly_k([self._cv(i, 0) for i in range(self.n)], self._gc)
        self._exactly_k([self._cv(i, 1) for i in range(self.n)], self._vc)
        self._exactly_k([self._cv(i, 2) for i in range(self.n)], self._zc)

        # Sight-line constraints
        w, h = self.w, self.h
        lines = []
        for c in range(w):
            lines.append((self._path(0, c, 1, 0), self._top[c]))
        for c in range(w):
            lines.append((self._path(h - 1, c, -1, 0), self._bot[c]))
        for r in range(h):
            lines.append((self._path(r, 0, 0, 1), self._lft[r]))
        for r in range(h):
            lines.append((self._path(r, w - 1, 0, -1), self._rgt[r]))

        for path, clue in lines:
            if not path:
                if clue != 0:
                    self._add([])  # unsatisfiable
                continue
            vis = []
            for ci, refl in path:
                vv = self._fresh()
                vis.append(vv)
                if refl:
                    va = self._cv(ci, 1)
                    zo = self._cv(ci, 2)
                    self._add([-vv, va, zo])
                    self._add([-va, vv])
                    self._add([-zo, vv])
                else:
                    gh = self._cv(ci, 0)
                    zo = self._cv(ci, 2)
                    self._add([-vv, gh, zo])
                    self._add([-gh, vv])
                    self._add([-zo, vv])
            self._exactly_k(vis, clue)

    def check_unique(self, solution_grid):
        """Return True iff the provided solution is the ONLY valid one."""
        # Build blocking clause: at least one cell must differ from solution
        blocking = []
        for i, (r, c) in enumerate(self.cells):
            cell = solution_grid[r][c]
            t = {"G": 0, "V": 1, "Z": 2}[cell]
            blocking.append(-self._cv(i, t))

        num_vars = self._next - 1
        num_cls = len(self._cls) + 1

        fd, cnf_path = tempfile.mkstemp(suffix=".cnf")
        out_path = cnf_path + ".out"
        try:
            with os.fdopen(fd, "w") as f:
                f.write(f"p cnf {num_vars} {num_cls}\n")
                for cl in self._cls:
                    f.write(" ".join(str(l) for l in cl) + " 0\n")
                f.write(" ".join(str(l) for l in blocking) + " 0\n")

            subprocess.run(
                ["minisat", cnf_path, out_path],
                capture_output=True,
                timeout=120,
            )

            if not os.path.isfile(out_path):
                raise RuntimeError("minisat produced no output file")

            with open(out_path) as f:
                verdict = f.readline().strip()

            return verdict == "UNSAT"
        finally:
            for p in (cnf_path, out_path):
                if os.path.isfile(p):
                    os.remove(p)


# ── Test cases ──────────────────────────────────────────────────────


@pytest.mark.parametrize("name", PUZZLE_NAMES)
def test_files_exist(name):
    """Both .desc and .json files must be present."""
    desc = os.path.join(GENERATED_DIR, f"{name}.desc")
    sol = os.path.join(GENERATED_DIR, f"{name}.json")
    assert os.path.isfile(desc), f"Missing {desc}"
    assert os.path.isfile(sol), f"Missing {sol}"


@pytest.mark.parametrize("name", PUZZLE_NAMES)
def test_desc_parseable(name):
    """The .desc file must parse correctly with the expected grid size."""
    puzzle = parse_desc(os.path.join(GENERATED_DIR, f"{name}.desc"))
    spec = PUZZLE_SPECS[name]
    assert puzzle["w"] == spec["w"], f"Width {puzzle['w']} != {spec['w']}"
    assert puzzle["h"] == spec["h"], f"Height {puzzle['h']} != {spec['h']}"


@pytest.mark.parametrize("name", PUZZLE_NAMES)
def test_solution_valid_json(name):
    """Solution JSON has the expected structure."""
    sol_path = os.path.join(GENERATED_DIR, f"{name}.json")
    with open(sol_path) as f:
        sol = json.load(f)
    assert "grid" in sol, "Missing 'grid' key"
    assert isinstance(sol["grid"], list), "'grid' must be a list"
    assert len(sol["grid"]) > 0, "'grid' must not be empty"
    for row in sol["grid"]:
        assert isinstance(row, list), "Each row must be a list"


@pytest.mark.parametrize("name", PUZZLE_NAMES)
def test_solution_correct(name):
    """Solution satisfies all puzzle constraints (clues, counts, mirrors)."""
    puzzle = parse_desc(os.path.join(GENERATED_DIR, f"{name}.desc"))
    with open(os.path.join(GENERATED_DIR, f"{name}.json")) as f:
        sol = json.load(f)
    errors = verify_solution(puzzle, sol["grid"])
    assert not errors, "Solution verification failed:\n" + "\n".join(errors)


@pytest.mark.parametrize("name", PUZZLE_NAMES)
def test_unique_solution(name):
    """Puzzle has exactly one valid solution (SAT-based uniqueness check)."""
    puzzle = parse_desc(os.path.join(GENERATED_DIR, f"{name}.desc"))
    with open(os.path.join(GENERATED_DIR, f"{name}.json")) as f:
        sol = json.load(f)

    checker = _SATUniqueness(puzzle)
    checker.encode()
    is_unique = checker.check_unique(sol["grid"])
    assert is_unique, (
        "Puzzle does not have a unique solution — "
        "minisat found an alternative valid assignment"
    )


@pytest.mark.parametrize("name", PUZZLE_NAMES)
def test_mirror_count_in_range(name):
    """Number of mirrors must fall within the specified range."""
    puzzle = parse_desc(os.path.join(GENERATED_DIR, f"{name}.desc"))
    spec = PUZZLE_SPECS[name]
    n_mirrors = len(puzzle["mirrors"])
    assert spec["min_mirrors"] <= n_mirrors <= spec["max_mirrors"], (
        f"Mirror count {n_mirrors} outside [{spec['min_mirrors']}, {spec['max_mirrors']}]"
    )


@pytest.mark.parametrize("name", PUZZLE_NAMES)
def test_all_monster_types_present(name):
    """Each of Ghost, Vampire, Zombie must have count >= 1."""
    puzzle = parse_desc(os.path.join(GENERATED_DIR, f"{name}.desc"))
    assert puzzle["g_count"] >= 1, f"Ghost count is {puzzle['g_count']}, must be >= 1"
    assert puzzle["v_count"] >= 1, f"Vampire count is {puzzle['v_count']}, must be >= 1"
    assert puzzle["z_count"] >= 1, f"Zombie count is {puzzle['z_count']}, must be >= 1"


@pytest.mark.parametrize("name", PUZZLE_NAMES)
def test_nonzero_clues_each_side(name):
    """At least one non-zero clue on each of the four sides."""
    puzzle = parse_desc(os.path.join(GENERATED_DIR, f"{name}.desc"))
    assert any(c > 0 for c in puzzle["top"]), "All top clues are 0"
    assert any(c > 0 for c in puzzle["bottom"]), "All bottom clues are 0"
    assert any(c > 0 for c in puzzle["left"]), "All left clues are 0"
    assert any(c > 0 for c in puzzle["right"]), "All right clues are 0"


def test_all_six_puzzles_generated():
    """All 6 puzzle pairs must exist and be non-empty."""
    for name in PUZZLE_NAMES:
        desc_path = os.path.join(GENERATED_DIR, f"{name}.desc")
        sol_path = os.path.join(GENERATED_DIR, f"{name}.json")
        assert os.path.isfile(desc_path), f"Missing {desc_path}"
        assert os.path.isfile(sol_path), f"Missing {sol_path}"
        assert os.path.getsize(desc_path) > 0, f"Empty {desc_path}"
        assert os.path.getsize(sol_path) > 0, f"Empty {sol_path}"
