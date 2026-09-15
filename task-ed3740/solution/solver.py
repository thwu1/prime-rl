"""

Sudoku Unavoidable Set Finder with database-driven pipeline and C solver integration.

Queries a SQLite database for grids with pending ua_mcn analysis tasks,
compiles and uses a C-based solution counter for fast verification,
then computes all minimal unavoidable sets of size 4 and 6 and the
Maximum Clique Number (MCN) on their disjointness graph.
"""

import json
import os
import sqlite3
import subprocess
from itertools import combinations

DB_PATH = "/app/sudoku_archive.db"
SOLVER_PATH = "/app/tools/sudoku_solver"
OUTPUT_PATH = "/app/results.json"


# ---------------------------------------------------------------------------
# Database access
# ---------------------------------------------------------------------------

def get_target_grids():
    """Query database for grids with pending ua_mcn analysis tasks."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("""
        SELECT g.grid_id, g.grid_string
        FROM completed_grids g
        JOIN analysis_queue q ON g.grid_id = q.grid_id
        WHERE q.analysis_type = 'ua_mcn' AND q.status = 'pending'
        ORDER BY g.grid_id
    """)
    rows = cur.fetchall()
    conn.close()
    return [(row['grid_id'], row['grid_string']) for row in rows]


# ---------------------------------------------------------------------------
# Grid utilities
# ---------------------------------------------------------------------------

def parse_grid(s):
    """Parse an 81-char string into a 9x9 grid (list of lists)."""
    s = s.strip()
    assert len(s) == 81
    return [[int(s[r * 9 + c]) for c in range(9)] for r in range(9)]


def cell_index(r, c):
    return r * 9 + c


def cell_rc(idx):
    return divmod(idx, 9)


def box_of(r, c):
    return (r // 3) * 3 + (c // 3)


# ---------------------------------------------------------------------------
# C solver integration
# ---------------------------------------------------------------------------

def count_solutions_c(puzzle_str):
    """Use the compiled C solver for fast solution counting (up to 2)."""
    result = subprocess.run(
        [SOLVER_PATH, puzzle_str, "2"],
        capture_output=True, text=True, timeout=30
    )
    return int(result.stdout.strip())


def is_unavoidable(grid_str, cell_set):
    """Check if removing cell_set from grid creates multiple completions."""
    puzzle = list(grid_str)
    for i in cell_set:
        puzzle[i] = '0'
    return count_solutions_c(''.join(puzzle)) >= 2


# ---------------------------------------------------------------------------
# Find all minimal unavoidable sets of size 4
# ---------------------------------------------------------------------------

def find_ua4(grid):
    """
    Find all minimal unavoidable sets of size exactly 4.

    A size-4 UA set is a rectangle (r1,c1),(r1,c2),(r2,c1),(r2,c2) where
    swapping the two digits preserves all Sudoku constraints. This requires
    the rows to be in the same band OR the columns in the same stack.
    """
    sets_found = []
    for r1 in range(9):
        for r2 in range(r1 + 1, 9):
            for c1 in range(9):
                for c2 in range(c1 + 1, 9):
                    if r1 // 3 != r2 // 3 and c1 // 3 != c2 // 3:
                        continue
                    a = grid[r1][c1]
                    b = grid[r1][c2]
                    if a == b:
                        continue
                    if grid[r2][c2] == a and grid[r2][c1] == b:
                        cells = sorted([cell_index(r1, c1), cell_index(r1, c2),
                                        cell_index(r2, c1), cell_index(r2, c2)])
                        sets_found.append(tuple(cells))
    return sorted(set(sets_found))


# ---------------------------------------------------------------------------
# Find all minimal unavoidable sets of size 6
# ---------------------------------------------------------------------------

def find_ua6(grid, grid_str, ua4_set_of_tuples):
    """
    Find all minimal unavoidable sets of size exactly 6.

    A size-6 set has exactly 3 distinct digits, each appearing exactly twice.
    Three possible cell geometries:
    - 2 rows x 3 columns
    - 3 rows x 2 columns
    - 3 rows x 3 columns (6 of 9 cells, 2 per row and 2 per column)
    """
    sets_found = set()

    def check_candidate(cells_list):
        cells_set = frozenset(cells_list)
        if len(cells_set) != 6:
            return None
        # Digit constraint: exactly 3 digits, each appearing twice
        digits = []
        for ci in cells_list:
            r, c = cell_rc(ci)
            digits.append(grid[r][c])
        digit_counts = {}
        for d in digits:
            digit_counts[d] = digit_counts.get(d, 0) + 1
        if len(digit_counts) != 3 or any(v != 2 for v in digit_counts.values()):
            return None
        # Box constraint: each occupied box has >= 2 cells
        box_counts = {}
        for ci in cells_list:
            r, c = cell_rc(ci)
            b = box_of(r, c)
            box_counts[b] = box_counts.get(b, 0) + 1
        if any(v < 2 for v in box_counts.values()):
            return None
        # Verify with solver
        if not is_unavoidable(grid_str, cells_set):
            return None
        # Check minimality: no 4-element subset is a UA4
        cells_tuple = tuple(sorted(cells_set))
        for combo in combinations(cells_tuple, 4):
            if combo in ua4_set_of_tuples:
                return None
        return cells_tuple

    # Geometry 1: 2 rows x 3 columns
    for r1, r2 in combinations(range(9), 2):
        for c1, c2, c3 in combinations(range(9), 3):
            cells = [cell_index(r1, c1), cell_index(r1, c2), cell_index(r1, c3),
                     cell_index(r2, c1), cell_index(r2, c2), cell_index(r2, c3)]
            result = check_candidate(cells)
            if result:
                sets_found.add(result)

    # Geometry 2: 3 rows x 2 columns
    for r1, r2, r3 in combinations(range(9), 3):
        for c1, c2 in combinations(range(9), 2):
            cells = [cell_index(r1, c1), cell_index(r1, c2),
                     cell_index(r2, c1), cell_index(r2, c2),
                     cell_index(r3, c1), cell_index(r3, c2)]
            result = check_candidate(cells)
            if result:
                sets_found.add(result)

    # Geometry 3: 3 rows x 3 columns, 2 per row and 2 per column
    perms_3 = [(0, 1, 2), (0, 2, 1), (1, 0, 2), (1, 2, 0), (2, 0, 1), (2, 1, 0)]
    for rows_triple in combinations(range(9), 3):
        for cols_triple in combinations(range(9), 3):
            for perm in perms_3:
                cells = []
                for i, r in enumerate(rows_triple):
                    for j, c in enumerate(cols_triple):
                        if j != perm[i]:
                            cells.append(cell_index(r, c))
                result = check_candidate(cells)
                if result:
                    sets_found.add(result)

    return sorted(sets_found)


# ---------------------------------------------------------------------------
# Maximum Clique on the disjointness graph
# ---------------------------------------------------------------------------

def compute_mcn(all_sets):
    """
    Compute the Maximum Clique Number: the maximum number of pairwise
    disjoint sets. Uses backtracking with pruning.
    """
    if not all_sets:
        return 0, []

    n = len(all_sets)
    set_cells = [set(s) for s in all_sets]
    disjoint = [[False] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            if set_cells[i].isdisjoint(set_cells[j]):
                disjoint[i][j] = True
                disjoint[j][i] = True

    best = [0]
    best_clique = [[]]

    def backtrack(candidates, current_clique):
        if len(current_clique) + len(candidates) <= best[0]:
            return
        if not candidates:
            if len(current_clique) > best[0]:
                best[0] = len(current_clique)
                best_clique[0] = list(current_clique)
            return
        for idx, v in enumerate(candidates):
            if len(current_clique) + len(candidates) - idx <= best[0]:
                return
            new_candidates = [u for u in candidates[idx + 1:] if disjoint[v][u]]
            current_clique.append(v)
            backtrack(new_candidates, current_clique)
            current_clique.pop()

    backtrack(list(range(n)), [])
    clique_sets = [list(all_sets[i]) for i in best_clique[0]]
    return best[0], clique_sets


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def analyze_grid(grid_id, grid_str):
    grid = parse_grid(grid_str)
    ua4 = find_ua4(grid)
    ua4_set = set(ua4)
    ua6 = find_ua6(grid, grid_str, ua4_set)
    all_sets = list(ua4) + list(ua6)
    mcn, max_clique = compute_mcn(all_sets)
    return {
        "grid_id": grid_id,
        "ua4_count": len(ua4),
        "ua6_count": len(ua6),
        "mcn": mcn,
        "max_clique": max_clique,
        "ua4_sets": [list(s) for s in ua4],
        "ua6_sets": [list(s) for s in ua6],
    }


def main():
    # Compile C solver if not already built
    if not os.path.exists(SOLVER_PATH):
        print("Compiling C solver...", flush=True)
        subprocess.run(["make", "-C", "/app/tools"], check=True)

    # Query database for target grids
    targets = get_target_grids()
    print(f"Found {len(targets)} grids for ua_mcn analysis", flush=True)
    for gid, gs in targets:
        print(f"  grid_id={gid}: {gs[:20]}...")

    # Analyze each target grid
    results = []
    for grid_id, grid_str in targets:
        print(f"\nAnalyzing grid {grid_id}...", flush=True)
        result = analyze_grid(grid_id, grid_str)
        print(f"  UA4: {result['ua4_count']}, UA6: {result['ua6_count']}, MCN: {result['mcn']}")
        results.append(result)

    # Write results
    with open(OUTPUT_PATH, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults written to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
