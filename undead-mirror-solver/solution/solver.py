#!/usr/bin/env python3
"""
SAT-based Undead puzzle solver.

Encodes the Undead (Haunted Mirror Maze) puzzle as a CNF SAT problem using
sequential counter encoding (Sinz 2005) for cardinality constraints, writes
DIMACS format, solves with minisat, and decodes the solution.
"""

import json
import os
import subprocess
import sys


def parse_desc(path):
    """Parse a .desc game description file into puzzle parameters."""
    with open(path) as f:
        desc = f.read().strip()

    params_part, data_part = desc.split(":")
    w, h = map(int, params_part.split("x"))

    tokens = data_part.split(",")
    num_clues = 2 * (w + h)

    top = [int(tokens[i]) for i in range(w)]
    bottom = [int(tokens[w + i]) for i in range(w)]
    left = [int(tokens[2 * w + i]) for i in range(h)]
    right = [int(tokens[2 * w + h + i]) for i in range(h)]

    total_g = int(tokens[num_clues])
    total_v = int(tokens[num_clues + 1])
    total_z = int(tokens[num_clues + 2])

    grid_rle = tokens[num_clues + 3]

    # Decode RLE grid
    flat = []
    for ch in grid_rle:
        if ch == "L":
            flat.append("\\")
        elif ch == "R":
            flat.append("/")
        elif "a" <= ch <= "z":
            flat.extend(["."] * (ord(ch) - ord("a") + 1))
        else:
            raise ValueError(f"Unknown grid RLE character: {ch}")

    if len(flat) != w * h:
        raise ValueError(f"Grid size mismatch: {len(flat)} vs {w * h}")

    mirror_map = {}
    empty_cells = []
    for idx, cell in enumerate(flat):
        r = idx // w
        c = idx % w
        if cell in ("\\", "/"):
            mirror_map[(r, c)] = cell
        else:
            empty_cells.append((r, c))

    return {
        "width": w,
        "height": h,
        "total_ghosts": total_g,
        "total_vampires": total_v,
        "total_zombies": total_z,
        "top": top,
        "bottom": bottom,
        "left": left,
        "right": right,
        "mirror_map": mirror_map,
        "empty_cells": empty_cells,
    }


class SATEncoder:
    """Encode Undead puzzle as CNF using sequential counter cardinality encoding."""

    # Monster type indices
    GHOST = 0
    VAMPIRE = 1
    ZOMBIE = 2

    def __init__(self, puzzle):
        self.puzzle = puzzle
        self.w = puzzle["width"]
        self.h = puzzle["height"]
        self.cells = puzzle["empty_cells"]
        self.n_cells = len(self.cells)
        self.cell_idx = {cell: i for i, cell in enumerate(self.cells)}
        self.mirror_map = puzzle["mirror_map"]

        # Primary variables: 3 per cell (one per monster type), 1-indexed
        self.next_var = 3 * self.n_cells + 1
        self.clauses = []

        # Trace all paths from edges
        self.paths = []
        self.clues_list = []
        self._trace_all_paths()

    def cell_var(self, cell_idx, monster_type):
        """DIMACS variable for cell_idx being monster_type (0=G, 1=V, 2=Z)."""
        return 3 * cell_idx + monster_type + 1

    def new_var(self):
        """Allocate a fresh auxiliary variable."""
        v = self.next_var
        self.next_var += 1
        return v

    def add_clause(self, lits):
        """Add a clause (disjunction of literals)."""
        self.clauses.append(list(lits))

    def _trace_path(self, start_r, start_c, dr, dc):
        """Trace line of sight from an edge, returning [(cell_idx, is_reflected)]."""
        path = []
        r, c = start_r, start_c
        reflected = False
        visited = set()

        while 0 <= r < self.h and 0 <= c < self.w:
            state = (r, c, dr, dc)
            if state in visited:
                break
            visited.add(state)

            if (r, c) in self.mirror_map:
                m = self.mirror_map[(r, c)]
                if m == "\\":
                    dr, dc = dc, dr
                elif m == "/":
                    dr, dc = -dc, -dr
                reflected = True
            else:
                ci = self.cell_idx[(r, c)]
                path.append((ci, reflected))

            r += dr
            c += dc

        return path

    def _trace_all_paths(self):
        """Trace lines of sight from all 2*(W+H) edge positions."""
        w, h = self.w, self.h
        p = self.puzzle

        # Top clues: entering from row 0, going south (dr=1, dc=0)
        for c in range(w):
            self.paths.append(self._trace_path(0, c, 1, 0))
            self.clues_list.append(p["top"][c])

        # Bottom clues: entering from row h-1, going north (dr=-1, dc=0)
        for c in range(w):
            self.paths.append(self._trace_path(h - 1, c, -1, 0))
            self.clues_list.append(p["bottom"][c])

        # Left clues: entering from col 0, going east (dr=0, dc=1)
        for r in range(h):
            self.paths.append(self._trace_path(r, 0, 0, 1))
            self.clues_list.append(p["left"][r])

        # Right clues: entering from col w-1, going west (dr=0, dc=-1)
        for r in range(h):
            self.paths.append(self._trace_path(r, w - 1, 0, -1))
            self.clues_list.append(p["right"][r])

    def encode(self):
        """Encode all puzzle constraints as CNF clauses."""
        self._encode_exactly_one_per_cell()
        self._encode_monster_counts()
        self._encode_path_constraints()

    def _encode_exactly_one_per_cell(self):
        """Each empty cell must have exactly one monster type."""
        for i in range(self.n_cells):
            g = self.cell_var(i, self.GHOST)
            v = self.cell_var(i, self.VAMPIRE)
            z = self.cell_var(i, self.ZOMBIE)
            # At-least-one (ALO)
            self.add_clause([g, v, z])
            # At-most-one (AMO) pairwise
            self.add_clause([-g, -v])
            self.add_clause([-g, -z])
            self.add_clause([-v, -z])

    def _encode_at_most_k(self, variables, k):
        """Sinz sequential counter encoding for at-most-K constraint.

        Creates auxiliary counter variables s[i][j] where s[i][j]=True means
        "at least j+1 of variables[0..i] are true". The overflow clause prevents
        more than K variables from being true simultaneously.

        Reference: Sinz, C. "Towards an Optimal CNF Encoding of Boolean
        Cardinality Constraints" (CP 2005).
        """
        n = len(variables)
        if k >= n:
            return  # trivially satisfied
        if k == 0:
            for v in variables:
                self.add_clause([-v])
            return

        # Counter variables: s[i][j] for i in 0..n-1, j in 0..k-1
        s = [[self.new_var() for _ in range(k)] for _ in range(n)]

        # Base case (i=0)
        self.add_clause([-variables[0], s[0][0]])
        for j in range(1, k):
            self.add_clause([-s[0][j]])

        # Inductive case (i=1..n-1)
        for i in range(1, n):
            x = variables[i]
            # x_i => s[i][0] (if x_i is true, count is at least 1)
            self.add_clause([-x, s[i][0]])
            # s[i-1][0] => s[i][0] (monotonicity)
            self.add_clause([-s[i - 1][0], s[i][0]])

            for j in range(1, k):
                # x_i AND s[i-1][j-1] => s[i][j]
                self.add_clause([-x, -s[i - 1][j - 1], s[i][j]])
                # s[i-1][j] => s[i][j] (monotonicity)
                self.add_clause([-s[i - 1][j], s[i][j]])

            # Overflow prevention: NOT (x_i AND s[i-1][k-1])
            self.add_clause([-x, -s[i - 1][k - 1]])

    def _encode_exactly_k(self, variables, k):
        """Encode exactly-K constraint using dual sequential counters.

        Combines at-most-K (on positive literals) with at-most-(N-K)
        (on negated literals) to achieve exactly-K.
        """
        n = len(variables)
        if n == 0:
            if k != 0:
                self.add_clause([])  # empty clause = UNSAT
            return
        if k == 0:
            for v in variables:
                self.add_clause([-v])
            return
        if k == n:
            for v in variables:
                self.add_clause([v])
            return

        # At-most-K: at most K of the variables are true
        self._encode_at_most_k(variables, k)

        # At-least-K: at most (N-K) of the negated variables are true
        # (i.e., at most N-K variables are false, so at least K are true)
        neg_vars = [-v for v in variables]
        self._encode_at_most_k(neg_vars, n - k)

    def _encode_monster_counts(self):
        """Total count of each monster type across all cells must match."""
        p = self.puzzle
        totals = [p["total_ghosts"], p["total_vampires"], p["total_zombies"]]
        for t, total in enumerate(totals):
            type_vars = [self.cell_var(i, t) for i in range(self.n_cells)]
            self._encode_exactly_k(type_vars, total)

    def _encode_path_constraints(self):
        """For each sight line, visible monster count must equal the clue.

        For each cell on a path, creates a visibility auxiliary variable:
        - Unreflected position: visible iff Ghost or Zombie
        - Reflected position: visible iff Vampire or Zombie
        Then constrains exactly clue-many visibility variables to be true.
        """
        for path, clue in zip(self.paths, self.clues_list):
            if not path:
                if clue != 0:
                    self.add_clause([])  # UNSAT
                continue

            vis_vars = []
            for ci, reflected in path:
                v = self.new_var()
                vis_vars.append(v)

                if reflected:
                    # Visible iff Vampire or Zombie
                    vamp = self.cell_var(ci, self.VAMPIRE)
                    zomb = self.cell_var(ci, self.ZOMBIE)
                    # v -> (vamp OR zomb)
                    self.add_clause([-v, vamp, zomb])
                    # vamp -> v
                    self.add_clause([-vamp, v])
                    # zomb -> v
                    self.add_clause([-zomb, v])
                else:
                    # Visible iff Ghost or Zombie
                    ghost = self.cell_var(ci, self.GHOST)
                    zomb = self.cell_var(ci, self.ZOMBIE)
                    # v -> (ghost OR zomb)
                    self.add_clause([-v, ghost, zomb])
                    # ghost -> v
                    self.add_clause([-ghost, v])
                    # zomb -> v
                    self.add_clause([-zomb, v])

            self._encode_exactly_k(vis_vars, clue)

    def write_dimacs(self, path):
        """Write the CNF formula in DIMACS format."""
        num_vars = self.next_var - 1
        num_clauses = len(self.clauses)
        with open(path, "w") as f:
            f.write(f"c Undead puzzle SAT encoding\n")
            f.write(f"c {self.n_cells} empty cells, "
                    f"{num_vars} total variables, "
                    f"{num_clauses} clauses\n")
            f.write(f"p cnf {num_vars} {num_clauses}\n")
            for clause in self.clauses:
                f.write(" ".join(str(lit) for lit in clause) + " 0\n")

    def solve_with_minisat(self, cnf_path):
        """Run minisat on the CNF file and parse the result."""
        out_path = cnf_path + ".result"
        try:
            subprocess.run(
                ["minisat", cnf_path, out_path],
                capture_output=True,
                text=True,
                timeout=120,
            )
        except FileNotFoundError:
            print("ERROR: minisat not found at /usr/bin/minisat", file=sys.stderr)
            sys.exit(1)

        if not os.path.isfile(out_path):
            print("ERROR: minisat did not produce output file", file=sys.stderr)
            sys.exit(1)

        with open(out_path) as f:
            lines = f.readlines()

        if not lines or lines[0].strip() != "SAT":
            return None

        # Parse variable assignments from remaining lines
        assignments = {}
        for line in lines[1:]:
            for token in line.split():
                val = int(token)
                if val == 0:
                    break
                assignments[abs(val)] = val > 0

        # Clean up result file
        os.remove(out_path)
        return assignments

    def extract_solution(self, assignments):
        """Convert SAT variable assignments to solution grid."""
        w, h = self.w, self.h
        grid = [[None] * w for _ in range(h)]

        # Place mirrors
        for (r, c), m in self.mirror_map.items():
            grid[r][c] = m

        # Place monsters based on SAT assignments
        type_names = ["G", "V", "Z"]
        for i, (r, c) in enumerate(self.cells):
            assigned = False
            for t in range(3):
                var = self.cell_var(i, t)
                if assignments.get(var, False):
                    grid[r][c] = type_names[t]
                    assigned = True
                    break
            if not assigned:
                raise ValueError(
                    f"Cell ({r},{c}) has no monster assigned in SAT solution"
                )

        return {"grid": grid}


def main():
    puzzle_dir = "/app/puzzles"
    solution_dir = "/app/solutions"
    dimacs_dir = "/app/dimacs"

    os.makedirs(solution_dir, exist_ok=True)
    os.makedirs(dimacs_dir, exist_ok=True)

    desc_files = sorted(f for f in os.listdir(puzzle_dir) if f.endswith(".desc"))
    if not desc_files:
        print("No .desc puzzle files found in " + puzzle_dir, file=sys.stderr)
        sys.exit(1)

    for fname in desc_files:
        base = os.path.splitext(fname)[0]
        desc_path = os.path.join(puzzle_dir, fname)
        cnf_path = os.path.join(dimacs_dir, f"{base}.cnf")
        sol_path = os.path.join(solution_dir, f"{base}.json")

        print(f"Processing {fname}...", flush=True)

        puzzle = parse_desc(desc_path)
        n = len(puzzle["empty_cells"])
        print(f"  Grid: {puzzle['width']}x{puzzle['height']}, "
              f"{n} empty cells, "
              f"{len(puzzle['mirror_map'])} mirrors", flush=True)

        encoder = SATEncoder(puzzle)
        encoder.encode()
        encoder.write_dimacs(cnf_path)
        print(f"  CNF: {encoder.next_var - 1} variables, "
              f"{len(encoder.clauses)} clauses", flush=True)

        assignments = encoder.solve_with_minisat(cnf_path)
        if assignments is None:
            print(f"  UNSATISFIABLE — no valid assignment exists",
                  file=sys.stderr)
            sys.exit(1)

        solution = encoder.extract_solution(assignments)

        with open(sol_path, "w") as f:
            json.dump(solution, f, indent=2)
        print(f"  Solution written to {sol_path}", flush=True)

    print("All puzzles solved successfully.")


if __name__ == "__main__":
    main()
