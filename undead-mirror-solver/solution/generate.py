#!/usr/bin/env python3
"""
Undead puzzle generator with SAT-based uniqueness certification.

Pipeline:
  1. Random mirror placement at required density
  2. Random monster assignment (all three types present)
  3. Compute sight-line clues via ray-tracing
  4. Encode as CNF SAT; verify uniqueness with minisat + blocking clause
  5. Retry until a certified-unique puzzle is found
  6. Encode in .desc format and write solution JSON
"""

import json
import os
import random
import subprocess
import sys
import tempfile


# ── Puzzle specifications ────────────────────────────────────────────

SPECS = [
    ("puzzle_01", 5, 5, 2, 5),
    ("puzzle_02", 5, 5, 8, 12),
    ("puzzle_03", 7, 7, 4, 9),
    ("puzzle_04", 7, 7, 16, 22),
    ("puzzle_05", 9, 9, 6, 14),
    ("puzzle_06", 9, 9, 28, 36),
]


# ── Grid construction ───────────────────────────────────────────────


def place_mirrors(w, h, num):
    """Return dict (r,c)->mirror_char for num randomly placed mirrors."""
    positions = random.sample([(r, c) for r in range(h) for c in range(w)], num)
    return {pos: random.choice(["\\", "/"]) for pos in positions}


def assign_monsters(w, h, mirrors):
    """Assign a random monster to each non-mirror cell. All types present."""
    empties = [(r, c) for r in range(h) for c in range(w) if (r, c) not in mirrors]
    n = len(empties)
    if n < 3:
        return None, 0, 0, 0

    # Random partition of n into 3 positive parts
    dividers = sorted(random.sample(range(1, n), 2))
    gc = dividers[0]
    vc = dividers[1] - dividers[0]
    zc = n - dividers[1]

    types = ["G"] * gc + ["V"] * vc + ["Z"] * zc
    random.shuffle(types)
    return {cell: t for cell, t in zip(empties, types)}, gc, vc, zc


# ── Ray tracing ──────────────────────────────────────────────────────


def trace_sight(grid, h, w, sr, sc, dr, dc):
    """Count monsters visible along one sight line."""
    r, c = sr, sc
    reflected = False
    count = 0
    visited = set()

    while 0 <= r < h and 0 <= c < w:
        state = (r, c, dr, dc)
        if state in visited:
            break
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


def compute_clues(grid, h, w):
    """Compute all 2*(W+H) edge clues from a filled grid."""
    top = [trace_sight(grid, h, w, 0, c, 1, 0) for c in range(w)]
    bottom = [trace_sight(grid, h, w, h - 1, c, -1, 0) for c in range(w)]
    left = [trace_sight(grid, h, w, r, 0, 0, 1) for r in range(h)]
    right = [trace_sight(grid, h, w, r, w - 1, 0, -1) for r in range(h)]
    return top, bottom, left, right


# ── .desc format encoding ───────────────────────────────────────────


def encode_rle(mirrors, h, w):
    """Encode mirror layout as RLE string for .desc format."""
    parts = []
    run = 0
    for r in range(h):
        for c in range(w):
            if (r, c) in mirrors:
                while run > 0:
                    chunk = min(run, 26)
                    parts.append(chr(ord("a") + chunk - 1))
                    run -= chunk
                parts.append("L" if mirrors[(r, c)] == "\\" else "R")
            else:
                run += 1
    while run > 0:
        chunk = min(run, 26)
        parts.append(chr(ord("a") + chunk - 1))
        run -= chunk
    return "".join(parts)


def build_desc(w, h, top, bottom, left, right, gc, vc, zc, mirrors):
    """Build the complete .desc string."""
    clues = ",".join(str(x) for x in top + bottom + left + right)
    rle = encode_rle(mirrors, h, w)
    return f"{w}x{h}:{clues},{gc},{vc},{zc},{rle}"


# ── SAT-based uniqueness verification ───────────────────────────────


class _SATChecker:
    """Encode puzzle as CNF and verify uniqueness via minisat."""

    def __init__(self, w, h, mirrors, empties, top, bottom, left, right, gc, vc, zc):
        self.w, self.h = w, h
        self.mirrors = mirrors
        self.cells = empties
        self.n = len(empties)
        self.cidx = {c: i for i, c in enumerate(empties)}
        self._next = 3 * self.n + 1
        self._cls = []
        self.top, self.bottom = top, bottom
        self.left, self.right = left, right
        self.gc, self.vc, self.zc = gc, vc, zc

    def _cv(self, i, t):
        return 3 * i + t + 1

    def _nv(self):
        v = self._next
        self._next += 1
        return v

    def _trace(self, sr, sc, dr, dc):
        path = []
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
                path.append((self.cidx[(r, c)], refl))
            r += dr
            c += dc
        return path

    def _amk(self, vs, k):
        n = len(vs)
        if k >= n:
            return
        if k == 0:
            for v in vs:
                self._cls.append([-v])
            return
        s = [[self._nv() for _ in range(k)] for _ in range(n)]
        self._cls.append([-vs[0], s[0][0]])
        for j in range(1, k):
            self._cls.append([-s[0][j]])
        for i in range(1, n):
            self._cls.append([-vs[i], s[i][0]])
            self._cls.append([-s[i - 1][0], s[i][0]])
            for j in range(1, k):
                self._cls.append([-vs[i], -s[i - 1][j - 1], s[i][j]])
                self._cls.append([-s[i - 1][j], s[i][j]])
            self._cls.append([-vs[i], -s[i - 1][k - 1]])

    def _exk(self, vs, k):
        n = len(vs)
        if n == 0:
            if k != 0:
                self._cls.append([])
            return
        if k == 0:
            for v in vs:
                self._cls.append([-v])
            return
        if k == n:
            for v in vs:
                self._cls.append([v])
            return
        self._amk(vs, k)
        self._amk([-v for v in vs], n - k)

    def encode(self):
        # Exactly one type per cell
        for i in range(self.n):
            g, v, z = self._cv(i, 0), self._cv(i, 1), self._cv(i, 2)
            self._cls.append([g, v, z])
            self._cls.append([-g, -v])
            self._cls.append([-g, -z])
            self._cls.append([-v, -z])

        # Monster-type totals
        self._exk([self._cv(i, 0) for i in range(self.n)], self.gc)
        self._exk([self._cv(i, 1) for i in range(self.n)], self.vc)
        self._exk([self._cv(i, 2) for i in range(self.n)], self.zc)

        # Sight-line visibility constraints
        w, h = self.w, self.h
        lines = []
        for c in range(w):
            lines.append((self._trace(0, c, 1, 0), self.top[c]))
        for c in range(w):
            lines.append((self._trace(h - 1, c, -1, 0), self.bottom[c]))
        for r in range(h):
            lines.append((self._trace(r, 0, 0, 1), self.left[r]))
        for r in range(h):
            lines.append((self._trace(r, w - 1, 0, -1), self.right[r]))

        for path, clue in lines:
            if not path:
                if clue != 0:
                    self._cls.append([])
                continue
            vvs = []
            for ci, refl in path:
                vv = self._nv()
                vvs.append(vv)
                if refl:
                    va = self._cv(ci, 1)
                    zo = self._cv(ci, 2)
                    self._cls.append([-vv, va, zo])
                    self._cls.append([-va, vv])
                    self._cls.append([-zo, vv])
                else:
                    gh = self._cv(ci, 0)
                    zo = self._cv(ci, 2)
                    self._cls.append([-vv, gh, zo])
                    self._cls.append([-gh, vv])
                    self._cls.append([-zo, vv])
            self._exk(vvs, clue)

    def is_unique(self, assignment):
        """Return True iff the given assignment is the only valid solution."""
        blocking = []
        for i, (r, c) in enumerate(self.cells):
            t = {"G": 0, "V": 1, "Z": 2}[assignment[(r, c)]]
            blocking.append(-self._cv(i, t))

        nv = self._next - 1
        nc = len(self._cls) + 1

        fd, cnf = tempfile.mkstemp(suffix=".cnf")
        out = cnf + ".out"
        try:
            with os.fdopen(fd, "w") as f:
                f.write(f"p cnf {nv} {nc}\n")
                for cl in self._cls:
                    f.write(" ".join(str(l) for l in cl) + " 0\n")
                f.write(" ".join(str(l) for l in blocking) + " 0\n")

            subprocess.run(
                ["minisat", cnf, out],
                capture_output=True,
                timeout=60,
            )

            if not os.path.isfile(out):
                return False

            with open(out) as f:
                verdict = f.readline().strip()

            return verdict == "UNSAT"
        finally:
            for p in (cnf, out):
                if os.path.isfile(p):
                    os.remove(p)


# ── Main generation pipeline ────────────────────────────────────────


def generate_puzzle(name, w, h, min_mirrors, max_mirrors, max_attempts=1500):
    """Generate a single puzzle meeting all requirements."""
    for attempt in range(max_attempts):
        num_mirrors = random.randint(min_mirrors, max_mirrors)
        mirrors = place_mirrors(w, h, num_mirrors)

        result = assign_monsters(w, h, mirrors)
        assignment, gc, vc, zc = result
        if assignment is None:
            continue

        # Build the filled grid
        grid = [[None] * w for _ in range(h)]
        for (r, c), m in mirrors.items():
            grid[r][c] = m
        for (r, c), t in assignment.items():
            grid[r][c] = t

        # Compute clues
        top, bottom, left, right = compute_clues(grid, h, w)

        # Require each side to have at least one nonzero clue
        if (all(x == 0 for x in top) or all(x == 0 for x in bottom)
                or all(x == 0 for x in left) or all(x == 0 for x in right)):
            continue

        # SAT-based uniqueness check
        empties = sorted(assignment.keys())
        checker = _SATChecker(
            w, h, mirrors, empties,
            top, bottom, left, right, gc, vc, zc,
        )
        checker.encode()

        if checker.is_unique(assignment):
            desc = build_desc(w, h, top, bottom, left, right, gc, vc, zc, mirrors)
            sol_grid = [row[:] for row in grid]
            print(
                f"  {name}: unique puzzle found after {attempt + 1} attempts "
                f"({w}x{h}, {num_mirrors} mirrors, G={gc} V={vc} Z={zc})",
                flush=True,
            )
            return desc, {"grid": sol_grid}

    raise RuntimeError(
        f"Failed to generate unique puzzle for {name} "
        f"({w}x{h}, mirrors {min_mirrors}-{max_mirrors}) "
        f"after {max_attempts} attempts"
    )


def main():
    output_dir = "/app/generated"
    os.makedirs(output_dir, exist_ok=True)

    random.seed(42)

    for name, w, h, min_m, max_m in SPECS:
        print(f"Generating {name} ({w}x{h}, mirrors {min_m}-{max_m})...", flush=True)
        desc, solution = generate_puzzle(name, w, h, min_m, max_m)

        desc_path = os.path.join(output_dir, f"{name}.desc")
        sol_path = os.path.join(output_dir, f"{name}.json")

        with open(desc_path, "w") as f:
            f.write(desc)
        with open(sol_path, "w") as f:
            json.dump(solution, f, indent=2)

        print(f"  Written: {desc_path}", flush=True)

    print("\nAll 6 puzzles generated successfully.", flush=True)


if __name__ == "__main__":
    main()
