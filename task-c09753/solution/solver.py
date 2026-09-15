
"""
SAT-based solver for the N-Queens Completion problem with
exact solution counting and minimal unsatisfiable core extraction.

Capabilities:
1. Decision: SAT/UNSAT classification with solution recovery via CDCL SAT
2. Counting: Exact solution counting for instances with count_solutions flag
3. MUS extraction: Minimal unsatisfiable core for UNSAT instances using
   deletion-based algorithm
"""

import json
import os
import glob
from pysat.solvers import Glucose3


def var(r, c, n):
    """Map (row, col) to SAT variable number (1-indexed)."""
    return r * n + c + 1


def encode_nqueens_completion(n, pre_placed):
    """
    Encode an n-Queens Completion instance as a CNF formula.
    Uses pairwise encoding for at-most-one constraints.
    """
    clauses = []
    pre_set = set()

    # Pre-placed queen constraints: unit clauses and exclusion
    for r, c in pre_placed:
        pre_set.add((r, c))
        # This cell must have a queen
        clauses.append([var(r, c, n)])
        # No other queen in this row
        for c2 in range(n):
            if c2 != c:
                clauses.append([-var(r, c2, n)])
        # No other queen in this column
        for r2 in range(n):
            if r2 != r:
                clauses.append([-var(r2, c, n)])
        # No other queen on positive diagonal (r+c constant)
        for r2 in range(n):
            if r2 != r:
                c2 = (r + c) - r2
                if 0 <= c2 < n:
                    clauses.append([-var(r2, c2, n)])
        # No other queen on negative diagonal (r-c constant)
        for r2 in range(n):
            if r2 != r:
                c2 = r2 - (r - c)
                if 0 <= c2 < n:
                    clauses.append([-var(r2, c2, n)])

    # At-least-one queen per non-pre-placed row
    pre_rows = {r for r, c in pre_placed}
    for r in range(n):
        if r not in pre_rows:
            clauses.append([var(r, c, n) for c in range(n)])

    # At-most-one queen per non-pre-placed row (pairwise)
    for r in range(n):
        if r in pre_rows:
            continue
        for c1 in range(n):
            for c2 in range(c1 + 1, n):
                clauses.append([-var(r, c1, n), -var(r, c2, n)])

    # At-least-one queen per non-pre-placed column
    pre_cols = {c for r, c in pre_placed}
    for c in range(n):
        if c not in pre_cols:
            clauses.append([var(r, c, n) for r in range(n)])

    # At-most-one queen per non-pre-placed column (pairwise)
    for c in range(n):
        if c in pre_cols:
            continue
        for r1 in range(n):
            for r2 in range(r1 + 1, n):
                clauses.append([-var(r1, c, n), -var(r2, c, n)])

    # At-most-one queen per positive diagonal (r + c = const)
    for diag_sum in range(2 * n - 1):
        cells = []
        for r in range(n):
            c = diag_sum - r
            if 0 <= c < n:
                cells.append((r, c))
        if len(cells) <= 1:
            continue
        pre_on_diag = [(r, c) for r, c in cells if (r, c) in pre_set]
        if pre_on_diag:
            continue  # unit clauses already exclude other cells
        for i in range(len(cells)):
            for j in range(i + 1, len(cells)):
                r1, c1 = cells[i]
                r2, c2 = cells[j]
                clauses.append([-var(r1, c1, n), -var(r2, c2, n)])

    # At-most-one queen per negative diagonal (r - c = const)
    for diag_diff in range(-(n - 1), n):
        cells = []
        for r in range(n):
            c = r - diag_diff
            if 0 <= c < n:
                cells.append((r, c))
        if len(cells) <= 1:
            continue
        pre_on_diag = [(r, c) for r, c in cells if (r, c) in pre_set]
        if pre_on_diag:
            continue
        for i in range(len(cells)):
            for j in range(i + 1, len(cells)):
                r1, c1 = cells[i]
                r2, c2 = cells[j]
                clauses.append([-var(r1, c1, n), -var(r2, c2, n)])

    return clauses


def solve_instance(n, pre_placed):
    """
    Solve the decision problem using a CDCL SAT solver.
    Returns (True, queens_list) if SAT, or (False, None) if UNSAT.
    """
    clauses = encode_nqueens_completion(n, pre_placed)

    solver = Glucose3()
    for clause in clauses:
        solver.add_clause(clause)

    if solver.solve():
        model = solver.get_model()
        positive_vars = set(v for v in model if v > 0)
        queens = [None] * n
        for r in range(n):
            for c in range(n):
                if var(r, c, n) in positive_vars:
                    queens[r] = c
                    break
        solver.delete()

        for r in range(n):
            if queens[r] is None:
                raise RuntimeError(f"Row {r} has no queen in SAT solution")

        return True, queens
    else:
        solver.delete()
        return False, None


def count_solutions_backtrack(n, pre_placed):
    """
    Count all valid n-queens completions using backtracking with
    column and diagonal constraint propagation.
    Used for counting instances (small n, typically <= 12).
    """
    queens = [None] * n
    used_cols = set()
    used_pos_diag = set()
    used_neg_diag = set()

    for r, c in pre_placed:
        queens[r] = c
        used_cols.add(c)
        used_pos_diag.add(r + c)
        used_neg_diag.add(r - c)

    empty_rows = sorted([r for r in range(n) if queens[r] is None])
    count = [0]

    def solve(idx):
        if idx == len(empty_rows):
            count[0] += 1
            return
        r = empty_rows[idx]
        for c in range(n):
            if c in used_cols:
                continue
            pd = r + c
            nd = r - c
            if pd in used_pos_diag or nd in used_neg_diag:
                continue
            queens[r] = c
            used_cols.add(c)
            used_pos_diag.add(pd)
            used_neg_diag.add(nd)
            solve(idx + 1)
            queens[r] = None
            used_cols.remove(c)
            used_pos_diag.remove(pd)
            used_neg_diag.remove(nd)

    solve(0)
    return count[0]


def extract_mus(n, pre_placed):
    """
    Extract a minimal unsatisfiable core (MUS) from the pre-placed queens
    using a deletion-based algorithm.

    Iteratively tries removing each queen from the candidate set.
    If the instance remains UNSAT without that queen, the queen is
    redundant and removed. If removing a queen makes the instance SAT,
    that queen is essential and kept.

    Returns the minimal subset of pre_placed queens that is UNSAT.
    """
    mus = [list(q) for q in pre_placed]
    i = 0
    while i < len(mus):
        candidate = mus[:i] + mus[i + 1:]
        if not candidate:
            # Cannot remove the last queen — single queen is always SAT for n>=4
            i += 1
            continue
        sat, _ = solve_instance(n, candidate)
        if not sat:
            # Still UNSAT without this queen — it's redundant
            mus = candidate
            # Don't increment i; the list shifted
        else:
            # Removing this queen restores SAT — it's essential
            i += 1
    return mus


def main():
    instances_dir = "/app/instances"
    results = {}

    instance_files = sorted(glob.glob(os.path.join(instances_dir, "*.json")))

    for fpath in instance_files:
        name = os.path.splitext(os.path.basename(fpath))[0]
        print(f"Processing {name}...")

        with open(fpath, "r") as f:
            instance = json.load(f)

        n = instance["n"]
        pre_placed = instance["pre_placed"]
        needs_count = instance.get("count_solutions", False)

        sat, queens = solve_instance(n, pre_placed)

        if sat:
            result = {"satisfiable": True, "queens": queens}
            if needs_count:
                print(f"  Counting all solutions for {name} (n={n})...")
                result["solution_count"] = count_solutions_backtrack(n, pre_placed)
                print(f"  {name}: SAT, {result['solution_count']} distinct completions")
            else:
                print(f"  {name}: SAT (n={n})")
        else:
            print(f"  {name}: UNSAT (n={n}), extracting minimal unsatisfiable core...")
            mus = extract_mus(n, pre_placed)
            print(f"  MUS: {len(mus)} queens out of {len(pre_placed)} pre-placed")
            result = {
                "satisfiable": False,
                "queens": None,
                "minimal_unsat_core": mus,
            }

        results[name] = result

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print(f"\nResults written to /app/results.json ({len(results)} instances)")


if __name__ == "__main__":
    main()
