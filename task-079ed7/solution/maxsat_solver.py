#!/usr/bin/env python3
"""
Optimal Weighted Partial MaxSAT Solver using MiniSat as SAT oracle.
Supports both new-format (h-lines) and old-format (p-line) WCNF.

Usage: python3 maxsat_solver.py <wcnf_file>
Exit codes: 30 = OPTIMUM FOUND, 20 = UNSATISFIABLE
"""

import sys
import os
import subprocess
import tempfile


def parse_wcnf(filepath):
    """Parse WCNF file, auto-detecting format.
    Returns (num_vars, hard_clauses, soft_clauses).
    soft_clauses: list of (weight, [literals])
    """
    hard_clauses = []
    soft_clauses = []
    max_var = 0
    top = None

    # First pass: detect format by looking for p-line
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("c"):
                continue
            if line.startswith("p"):
                tokens = line.split()
                if len(tokens) >= 4 and tokens[1] == "wcnf":
                    top = int(tokens[3])
                break
            else:
                break

    # Second pass: parse clauses
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("c") or line.startswith("p"):
                continue
            tokens = line.split()

            if top is not None:
                # Old format: weight lit1 lit2 ... 0
                weight = int(tokens[0])
                lits = []
                for t in tokens[1:]:
                    val = int(t)
                    if val == 0:
                        break
                    lits.append(val)
                    max_var = max(max_var, abs(val))
                if weight >= top:
                    hard_clauses.append(lits)
                else:
                    soft_clauses.append((weight, lits))
            else:
                # New format
                if tokens[0] == "h":
                    lits = []
                    for t in tokens[1:]:
                        val = int(t)
                        if val == 0:
                            break
                        lits.append(val)
                        max_var = max(max_var, abs(val))
                    hard_clauses.append(lits)
                else:
                    weight = int(tokens[0])
                    lits = []
                    for t in tokens[1:]:
                        val = int(t)
                        if val == 0:
                            break
                        lits.append(val)
                        max_var = max(max_var, abs(val))
                    soft_clauses.append((weight, lits))

    return max_var, hard_clauses, soft_clauses


def call_minisat(clauses, num_vars):
    """Call minisat on a set of clauses.
    Returns (is_sat, model_dict) where model_dict maps var -> 0/1.
    """
    in_fd, in_path = tempfile.mkstemp(suffix='.cnf')
    out_path = in_path + ".out"

    try:
        with os.fdopen(in_fd, 'w') as f:
            f.write(f"p cnf {num_vars} {len(clauses)}\n")
            for clause in clauses:
                f.write(" ".join(str(l) for l in clause) + " 0\n")

        result = subprocess.run(
            ["minisat", in_path, out_path],
            capture_output=True, timeout=60
        )

        if result.returncode == 10:  # SAT
            model = {}
            with open(out_path) as f:
                lines = f.readlines()
            if len(lines) >= 2:
                for tok in lines[1].strip().split():
                    lit = int(tok)
                    if lit == 0:
                        break
                    model[abs(lit)] = 1 if lit > 0 else 0
            for v in range(1, num_vars + 1):
                if v not in model:
                    model[v] = 0
            return True, model
        else:
            return False, None
    finally:
        try:
            os.unlink(in_path)
        except OSError:
            pass
        try:
            os.unlink(out_path)
        except OSError:
            pass


def eval_clause(clause, assignment):
    """Check if clause is satisfied. Empty clause is always false."""
    if not clause:
        return False
    for lit in clause:
        var = abs(lit)
        val = assignment.get(var, 0)
        if (lit > 0 and val == 1) or (lit < 0 and val == 0):
            return True
    return False


def compute_cost(assignment, soft_clauses):
    """Compute total cost of violated soft clauses."""
    cost = 0
    for weight, clause in soft_clauses:
        if not eval_clause(clause, assignment):
            cost += weight
    return cost


def sequential_counter_atmost(relax_vars, k, start_var):
    """Encode at-most-k constraint using Sinz sequential counter.
    Returns (clauses, next_free_var).
    """
    n = len(relax_vars)
    if k >= n:
        return [], start_var
    if k == 0:
        return [[-r] for r in relax_vars], start_var

    # s[i][j] = "at least j+1 of relax_vars[0..i] are true"
    s = {}
    nv = start_var
    for i in range(n):
        for j in range(k):
            s[(i, j)] = nv
            nv += 1

    clauses = []

    # First variable
    clauses.append([-relax_vars[0], s[(0, 0)]])
    for j in range(1, k):
        clauses.append([-s[(0, j)]])

    for i in range(1, n):
        # If r_i true, count >= 1
        clauses.append([-relax_vars[i], s[(i, 0)]])
        # Monotonicity
        for j in range(k):
            clauses.append([-s[(i - 1, j)], s[(i, j)]])
        # Increment
        for j in range(k - 1):
            clauses.append([-relax_vars[i], -s[(i - 1, j)], s[(i, j + 1)]])
        # Overflow prevention
        clauses.append([-relax_vars[i], -s[(i - 1, k - 1)]])

    return clauses, nv


def solve_unit_weight(num_vars, hard_clauses, soft_clauses, weight_per_clause):
    """Solve MaxSAT with equal weights using binary search + sequential counter."""
    n_soft = len(soft_clauses)
    relax_start = num_vars + 1
    relax_vars = list(range(relax_start, relax_start + n_soft))
    total_vars = relax_start + n_soft - 1

    # Base clauses: hard + relaxed soft
    base_clauses = [list(c) for c in hard_clauses]
    for i, (w, clause) in enumerate(soft_clauses):
        base_clauses.append(list(clause) + [relax_vars[i]])

    # Check if cost 0 achievable
    zero_clauses = list(base_clauses) + [[-r] for r in relax_vars]
    sat, model = call_minisat(zero_clauses, total_vars)
    if sat:
        return 0, model

    # Get initial upper bound
    sat, model = call_minisat(base_clauses, total_vars)
    if not sat:
        return None, None
    hi = sum(1 for r in relax_vars if model.get(r, 0) == 1)
    best_cost = hi
    best_model = model

    lo = 1
    while lo < hi:
        mid = (lo + hi) // 2
        counter_clauses, next_var = sequential_counter_atmost(relax_vars, mid, total_vars + 1)
        all_clauses = base_clauses + counter_clauses
        sat, model = call_minisat(all_clauses, next_var - 1)
        if sat:
            actual = sum(1 for r in relax_vars if model.get(r, 0) == 1)
            if actual < hi:
                hi = actual
                best_cost = actual
                best_model = model
        else:
            lo = mid + 1

    return best_cost * weight_per_clause, best_model


def solve_weighted(num_vars, hard_clauses, soft_clauses):
    """Solve weighted MaxSAT using model enumeration with blocking clauses."""
    n_soft = len(soft_clauses)
    relax_start = num_vars + 1
    relax_vars = list(range(relax_start, relax_start + n_soft))
    total_vars = relax_start + n_soft - 1

    base_clauses = [list(c) for c in hard_clauses]
    for i, (w, clause) in enumerate(soft_clauses):
        base_clauses.append(list(clause) + [relax_vars[i]])

    best_cost = None
    best_model = None
    clauses = list(base_clauses)
    max_iter = min(2 ** n_soft, 100000)

    for _ in range(max_iter):
        sat, model = call_minisat(clauses, total_vars)
        if not sat:
            break

        cost = sum(w for i, (w, _) in enumerate(soft_clauses) if model.get(relax_vars[i], 0) == 1)
        if best_cost is None or cost < best_cost:
            best_cost = cost
            best_model = model
        if cost == 0:
            break

        # Block this relaxation pattern
        blocking = []
        for r in relax_vars:
            if model.get(r, 0) == 1:
                blocking.append(-r)
            else:
                blocking.append(r)
        clauses.append(blocking)

    return best_cost, best_model


def main():
    if len(sys.argv) != 2:
        print("Usage: maxsat_solver <wcnf_file>", file=sys.stderr)
        sys.exit(1)

    wcnf_file = sys.argv[1]
    num_vars, hard_clauses, soft_clauses = parse_wcnf(wcnf_file)

    # Check for empty hard clauses
    for clause in hard_clauses:
        if not clause:
            print("s UNSATISFIABLE")
            sys.exit(20)

    # Check hard clause feasibility with minisat
    if hard_clauses:
        sat, _ = call_minisat([list(c) for c in hard_clauses], num_vars)
        if not sat:
            print("s UNSATISFIABLE")
            sys.exit(20)

    if not soft_clauses:
        sat, model = call_minisat([list(c) for c in hard_clauses], num_vars)
        if sat:
            print("o 0")
            print("s OPTIMUM FOUND")
            v_line = " ".join(str(model.get(i + 1, 0)) for i in range(num_vars))
            print(f"v {v_line}")
            sys.exit(30)
        else:
            print("s UNSATISFIABLE")
            sys.exit(20)

    # Choose algorithm based on weight structure
    weights = [w for w, _ in soft_clauses]
    all_same = len(set(weights)) == 1

    if all_same:
        cost, model = solve_unit_weight(num_vars, hard_clauses, soft_clauses, weights[0])
    else:
        cost, model = solve_weighted(num_vars, hard_clauses, soft_clauses)

    if cost is None or model is None:
        print("s UNSATISFIABLE")
        sys.exit(20)

    print(f"o {cost}")
    print("s OPTIMUM FOUND")
    v_line = " ".join(str(model.get(i + 1, 0)) for i in range(num_vars))
    print(f"v {v_line}")
    sys.exit(30)


if __name__ == "__main__":
    main()
