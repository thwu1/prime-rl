#!/usr/bin/env python3
"""
Optimal Weighted Partial MaxSAT Solver.
Reads WCNF in new format (post-2022), outputs MSE format.

Usage: python3 solver.py <wcnf_file>
Exit codes: 30 = OPTIMUM FOUND, 20 = UNSATISFIABLE
"""

import sys


def parse_wcnf(filepath):
    """Parse a WCNF file in the new format.
    Returns (num_vars, hard_clauses, soft_clauses).
    """
    hard_clauses = []
    soft_clauses = []
    max_var = 0

    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("c"):
                continue
            tokens = line.split()
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


def eval_clause(clause, assignment):
    """Evaluate whether a clause is satisfied.
    Empty clause is always false.
    """
    if not clause:
        return False
    for lit in clause:
        var = abs(lit)
        val = assignment.get(var, 0)
        if (lit > 0 and val == 1) or (lit < 0 and val == 0):
            return True
    return False


def solve_bruteforce(num_vars, hard_clauses, soft_clauses):
    """Brute-force solver: enumerate all assignments.
    Returns (status, cost, assignment_dict) or ('UNSAT', None, None).
    """
    best_cost = None
    best_assignment = None

    for bits in range(2 ** num_vars):
        assignment = {}
        for i in range(num_vars):
            assignment[i + 1] = (bits >> i) & 1

        # Check hard clauses
        all_hard_sat = True
        for clause in hard_clauses:
            if not eval_clause(clause, assignment):
                all_hard_sat = False
                break
        if not all_hard_sat:
            continue

        # Compute cost
        cost = 0
        for weight, clause in soft_clauses:
            if not eval_clause(clause, assignment):
                cost += weight

        if best_cost is None or cost < best_cost:
            best_cost = cost
            best_assignment = dict(assignment)

    if best_cost is None:
        return "UNSATISFIABLE", None, None
    return "OPTIMUM FOUND", best_cost, best_assignment


def solve_branch_and_bound(num_vars, hard_clauses, soft_clauses):
    """Branch-and-bound solver for larger instances.
    Uses unit propagation and cost lower-bounding for pruning.
    """
    best = [None, None]  # [cost, assignment]

    def unit_propagate(assignment, remaining_hard):
        """Simple unit propagation on hard clauses."""
        changed = True
        forced = dict(assignment)
        while changed:
            changed = False
            for clause in remaining_hard:
                unset = []
                satisfied = False
                for lit in clause:
                    var = abs(lit)
                    if var in forced:
                        val = forced[var]
                        if (lit > 0 and val == 1) or (lit < 0 and val == 0):
                            satisfied = True
                            break
                    else:
                        unset.append(lit)
                if satisfied:
                    continue
                if len(unset) == 0:
                    return None  # Conflict
                if len(unset) == 1:
                    lit = unset[0]
                    var = abs(lit)
                    val = 1 if lit > 0 else 0
                    if var in forced:
                        if forced[var] != val:
                            return None
                    else:
                        forced[var] = val
                        changed = True
        return forced

    def lower_bound(assignment, num_vars, soft_clauses):
        """Compute a lower bound on the cost from already-determined variables."""
        cost = 0
        for weight, clause in soft_clauses:
            if not clause:
                cost += weight
                continue
            can_satisfy = False
            already_satisfied = False
            for lit in clause:
                var = abs(lit)
                if var in assignment:
                    val = assignment[var]
                    if (lit > 0 and val == 1) or (lit < 0 and val == 0):
                        already_satisfied = True
                        break
                else:
                    can_satisfy = True
            if already_satisfied:
                continue
            if not can_satisfy:
                cost += weight
        return cost

    def branch(assignment, var_idx):
        if best[0] is not None:
            lb = lower_bound(assignment, num_vars, soft_clauses)
            if lb >= best[0]:
                return

        if var_idx > num_vars:
            # All variables assigned
            all_hard_sat = True
            for clause in hard_clauses:
                if not eval_clause(clause, assignment):
                    all_hard_sat = False
                    break
            if not all_hard_sat:
                return
            cost = 0
            for weight, clause in soft_clauses:
                if not eval_clause(clause, assignment):
                    cost += weight
            if best[0] is None or cost < best[0]:
                best[0] = cost
                best[1] = dict(assignment)
            return

        # Skip if already assigned (by unit propagation)
        if var_idx in assignment:
            branch(assignment, var_idx + 1)
            return

        for val in (0, 1):
            new_assignment = dict(assignment)
            new_assignment[var_idx] = val

            propagated = unit_propagate(new_assignment, hard_clauses)
            if propagated is None:
                continue

            lb = lower_bound(propagated, num_vars, soft_clauses)
            if best[0] is not None and lb >= best[0]:
                continue

            branch(propagated, var_idx + 1)

    # Check for empty hard clauses first
    for clause in hard_clauses:
        if not clause:
            return "UNSATISFIABLE", None, None

    branch({}, 1)

    if best[0] is None:
        return "UNSATISFIABLE", None, None
    return "OPTIMUM FOUND", best[0], best[1]


def main():
    if len(sys.argv) != 2:
        print("Usage: python3 solver.py <wcnf_file>", file=sys.stderr)
        sys.exit(1)

    wcnf_file = sys.argv[1]
    num_vars, hard_clauses, soft_clauses = parse_wcnf(wcnf_file)

    # Check for empty hard clauses (always UNSAT)
    for clause in hard_clauses:
        if not clause:
            print("s UNSATISFIABLE")
            sys.exit(20)

    # Choose solver based on instance size
    if num_vars <= 20:
        status, cost, assignment = solve_bruteforce(num_vars, hard_clauses, soft_clauses)
    else:
        status, cost, assignment = solve_branch_and_bound(
            num_vars, hard_clauses, soft_clauses
        )

    if status == "UNSATISFIABLE":
        print("s UNSATISFIABLE")
        sys.exit(20)
    else:
        print(f"o {cost}")
        print(f"s OPTIMUM FOUND")
        v_line = " ".join(str(assignment.get(i + 1, 0)) for i in range(num_vars))
        print(f"v {v_line}")
        sys.exit(30)


if __name__ == "__main__":
    main()
