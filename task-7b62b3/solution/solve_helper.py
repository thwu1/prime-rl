#!/usr/bin/env python3
"""
Reference solver for DLX forensics task. Pure Python Algorithm X with MRV.

"""
import os


class AlgorithmX:
    """Algorithm X with MRV heuristic for exact cover problems.

    Primary items must be covered exactly once.
    Secondary items may be covered at most once.
    """

    def __init__(self, primary, secondary, options):
        self.primary = list(primary)
        self.secondary = list(secondary)
        self.primary_set = set(self.primary)
        self.options = options
        self.item_opts = {item: [] for item in self.primary + self.secondary}
        for i, opt in enumerate(self.options):
            for item in opt:
                if item in self.item_opts:
                    self.item_opts[item].append(i)

    def solve(self, count_only=True, max_solutions=0):
        self._count = 0
        self._solutions = []
        self._count_only = count_only
        self._max = max_solutions
        self._covered = set()
        self._disabled = set()
        self._search([])
        return self._count, self._solutions

    def _search(self, partial):
        if self._max > 0 and self._count >= self._max:
            return

        best_item = None
        best_cnt = float("inf")
        for item in self.primary:
            if item in self._covered:
                continue
            cnt = 0
            for oi in self.item_opts[item]:
                if oi not in self._disabled:
                    cnt += 1
            if cnt < best_cnt:
                best_cnt = cnt
                best_item = item
                if cnt == 0:
                    return

        if best_item is None:
            self._count += 1
            if not self._count_only:
                self._solutions.append([self.options[i] for i in partial])
            return

        for oi in self.item_opts[best_item]:
            if oi in self._disabled:
                continue
            if self._max > 0 and self._count >= self._max:
                return

            opt = self.options[oi]
            newly_covered = []
            newly_disabled = []

            for item in opt:
                if item not in self._covered:
                    self._covered.add(item)
                    newly_covered.append(item)
                    for other_oi in self.item_opts[item]:
                        if other_oi not in self._disabled:
                            self._disabled.add(other_oi)
                            newly_disabled.append(other_oi)

            partial.append(oi)
            self._search(partial)
            partial.pop()

            for item in newly_covered:
                self._covered.discard(item)
            for d_oi in newly_disabled:
                self._disabled.discard(d_oi)


def parse_dlx(content):
    """Parse Knuth's DLX input format into (primary, secondary, options)."""
    lines = []
    for line in content.strip().split("\n"):
        s = line.strip()
        if s and not s.startswith("|"):
            lines.append(s)
    if not lines:
        return [], [], []

    header = lines[0]
    if " | " in header:
        parts = header.split(" | ", 1)
        primary = parts[0].split()
        secondary = parts[1].split()
    else:
        primary = header.split()
        secondary = []

    options = [line.split() for line in lines[1:]]
    return primary, secondary, options


def solve_dlx_file(filepath):
    with open(filepath) as f:
        content = f.read()
    primary, secondary, options = parse_dlx(content)
    solver = AlgorithmX(primary, secondary, options)
    count, _ = solver.solve(count_only=True)
    return count


def solve_dlx_content(content, count_only=True, max_solutions=0):
    primary, secondary, options = parse_dlx(content)
    solver = AlgorithmX(primary, secondary, options)
    return solver.solve(count_only=count_only, max_solutions=max_solutions)


def generate_corrected_sudoku(puzzle):
    """Generate Sudoku DLX file with CORRECT block formula."""
    lines = ["| Sudoku exact cover problem (corrected)"]
    items = []
    for r in range(9):
        for c in range(9):
            items.append(f"p{r}{c}")
    for r in range(9):
        for v in range(9):
            items.append(f"r{r}{v}")
    for c in range(9):
        for v in range(9):
            items.append(f"k{c}{v}")
    for b in range(9):
        for v in range(9):
            items.append(f"b{b}{v}")
    lines.append(" ".join(items))

    for r in range(9):
        for c in range(9):
            val = int(puzzle[r * 9 + c])
            blk = (r // 3) * 3 + c // 3
            if val != 0:
                v = val - 1
                lines.append(f"p{r}{c} r{r}{v} k{c}{v} b{blk}{v}")
            else:
                for v in range(9):
                    lines.append(f"p{r}{c} r{r}{v} k{c}{v} b{blk}{v}")
    return "\n".join(lines) + "\n"


def extract_sudoku_solution(solution_options, puzzle):
    """Extract Sudoku answer string from Algorithm X solution options."""
    board = list(puzzle)
    for opt in solution_options:
        cell_r, cell_c, value = None, None, None
        for item in opt:
            if len(item) == 3 and item[0] == "p" and item[1:].isdigit():
                cell_r, cell_c = int(item[1]), int(item[2])
            elif len(item) == 3 and item[0] == "r" and item[1:].isdigit():
                value = int(item[2]) + 1
        if cell_r is not None and value is not None:
            board[cell_r * 9 + cell_c] = str(value)
    return "".join(board)


def diagnose_sudoku_bug():
    """Analyze sudoku.dlx to identify the block index transposition."""
    with open("/app/problems/sudoku.dlx") as f:
        lines = [l.strip() for l in f if l.strip() and not l.strip().startswith("|")]

    errors = []
    for line in lines[1:]:
        items = line.split()
        cell_r, cell_c, block_idx = None, None, None
        for item in items:
            if len(item) == 3 and item[0] == "p" and item[1:].isdigit():
                cell_r, cell_c = int(item[1]), int(item[2])
            elif len(item) == 3 and item[0] == "b" and item[1:].isdigit():
                block_idx = int(item[1])
        if cell_r is not None and block_idx is not None:
            expected = (cell_r // 3) * 3 + cell_c // 3
            if block_idx != expected:
                errors.append((cell_r, cell_c, block_idx, expected))

    seen = set()
    unique = []
    for r, c, actual, expected in errors:
        if (r, c) not in seen:
            seen.add((r, c))
            unique.append((r, c, actual, expected))

    report = """\
Bug Report: sudoku.dlx
=======================
File: /app/problems/sudoku.dlx
Issue: Incorrect 3x3 block (box) index formula in the Sudoku DLX encoding.

Root cause:
  The block index is computed using a transposed formula:
    Buggy:   block = (row // 3) + (col // 3) * 3
    Correct: block = (row // 3) * 3 + (col // 3)

  This transposes the 3x3 block grid layout. In standard Sudoku, blocks are
  numbered left-to-right then top-to-bottom:
    0 1 2
    3 4 5
    6 7 8
  The buggy formula numbers them top-to-bottom then left-to-right:
    0 3 6
    1 4 7
    2 5 8

  This swaps block pairs (1<->3), (2<->6), (5<->7), while blocks on the
  diagonal (0, 4, 8) are unaffected. The result is a different constraint
  satisfaction problem that does not correspond to standard Sudoku.

Fix: Change the block index formula to (row // 3) * 3 + (col // 3).

Sample mismatched cells:
"""
    for r, c, actual, expected in unique[:12]:
        report += f"  Cell ({r},{c}): block={actual} (buggy), expected={expected}\n"

    return report


def analyze_unknown():
    """Analyze the structure of unknown.dlx to identify the problem."""
    with open("/app/problems/unknown.dlx") as f:
        lines = [l.strip() for l in f if l.strip() and not l.strip().startswith("|")]

    item_line = lines[0]
    all_items = item_line.split()
    primary = all_items
    secondary = []
    options = [line.split() for line in lines[1:]]
    items_per_option = len(options[0]) if options else 0

    analysis = f"""\
Analysis of unknown.dlx
========================

Structure:
  - {len(primary)} primary items, {len(secondary)} secondary items
  - {len(options)} options
  - Each option covers {items_per_option} items: 1 cell item (s*) + 5 constraint items (t*)

Identification:
  The 25 cell items (s0-s24) represent a 5x5 grid. The 125 constraint items
  (t0-t124) represent 25 groups of 5 constraints each — one group per grid
  cell, one constraint per value (0-4).

  Each option assigns a value v to cell (r,c) and covers:
    - The cell item s(r*5+c)
    - Five constraint items t(center*5+v) for each of the 5 plus-shaped
      neighborhood centers that include this cell

  The five centers for cell (r,c) are: (r,c) itself and its four cardinal
  neighbors with toroidal (wraparound) boundary conditions on the 5x5 grid.

  This is a "Plus Noise" low-discrepancy grid problem: assign values from
  {{0,1,2,3,4}} to each cell of a 5x5 toroidal grid such that every
  plus-shaped neighborhood (center + 4 cardinal neighbors, wrapping at edges)
  contains all 5 distinct values exactly once.

Solution count: 240
"""
    return analysis


def main():
    os.makedirs("/app/results", exist_ok=True)

    # 1. Count solutions for all problem files
    print("Computing solution counts...")
    problem_dir = "/app/problems"
    problem_files = sorted(f for f in os.listdir(problem_dir) if f.endswith(".dlx"))
    counts = {}
    for pf in problem_files:
        count = solve_dlx_file(os.path.join(problem_dir, pf))
        counts[pf] = count
        print(f"  {pf}: {count}")

    with open("/app/results/solution_counts.txt", "w") as f:
        for pf in sorted(counts):
            f.write(f"{pf} {counts[pf]}\n")

    # 2. Diagnose sudoku.dlx bug
    print("Diagnosing sudoku.dlx...")
    report = diagnose_sudoku_bug()
    with open("/app/results/bug_report.txt", "w") as f:
        f.write(report)

    # 3. Generate corrected Sudoku DLX
    print("Generating corrected Sudoku DLX...")
    puzzle = open("/app/puzzle.txt").read().strip()
    corrected = generate_corrected_sudoku(puzzle)
    with open("/app/results/corrected.dlx", "w") as f:
        f.write(corrected)

    # 4. Solve corrected Sudoku
    print("Solving corrected Sudoku...")
    count, solutions = solve_dlx_content(corrected, count_only=False, max_solutions=1)
    print(f"  Corrected sudoku: {count} solution(s)")
    if solutions:
        solution = extract_sudoku_solution(solutions[0], puzzle)
    else:
        solution = puzzle
    with open("/app/results/sudoku_solution.txt", "w") as f:
        f.write(solution)
    print(f"  Solution: {solution}")

    # 5. Analyze unknown.dlx
    print("Analyzing unknown.dlx...")
    analysis = analyze_unknown()
    with open("/app/results/unknown_analysis.txt", "w") as f:
        f.write(analysis)

    print("Done.")


if __name__ == "__main__":
    main()
