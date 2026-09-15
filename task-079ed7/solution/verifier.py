#!/usr/bin/env python3
"""
WCNF Solution Verifier for MaxSAT Evaluation format.
Verifies solver output against a WCNF instance.

Usage: python3 verifier.py <wcnf_file> <output_file>
Exit 0 if valid, 1 if any error detected.
"""

import sys


def parse_wcnf(filepath):
    """Parse a WCNF file in the new format (post-2022).
    Returns (num_vars, hard_clauses, soft_clauses).
    hard_clauses: list of lists of int literals
    soft_clauses: list of (weight, [literals])
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
                # Hard clause: h lit1 lit2 ... 0
                lits = []
                for t in tokens[1:]:
                    val = int(t)
                    if val == 0:
                        break
                    lits.append(val)
                    max_var = max(max_var, abs(val))
                hard_clauses.append(lits)
            else:
                # Soft clause: weight lit1 lit2 ... 0
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
    clause: list of int literals
    assignment: dict {var_index: 0 or 1}
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


def check_satisfiable(num_vars, hard_clauses):
    """Brute-force check if hard clauses are satisfiable."""
    if num_vars > 25:
        # Too many variables for brute force; skip this check
        return True

    for bits in range(2 ** num_vars):
        assignment = {}
        for i in range(num_vars):
            assignment[i + 1] = (bits >> i) & 1
        all_sat = True
        for clause in hard_clauses:
            if not eval_clause(clause, assignment):
                all_sat = False
                break
        if all_sat:
            return True
    return False


def parse_solver_output(filepath):
    """Parse MSE-format solver output.
    Returns (status, cost, assignment_list).
    """
    status = None
    cost = None
    v_values = []

    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if line.startswith("c "):
                continue
            if line.startswith("s "):
                status = line[2:].strip()
            elif line.startswith("o "):
                cost = int(line[2:].strip())
            elif line.startswith("v "):
                v_values.extend(line[2:].strip().split())

    assignment = [int(x) for x in v_values] if v_values else None
    return status, cost, assignment


def verify(wcnf_file, output_file):
    """Verify solver output against WCNF instance.
    Returns (valid, bugs) where bugs is a list of bug type strings.
    """
    bugs = []
    num_vars, hard_clauses, soft_clauses = parse_wcnf(wcnf_file)
    status, cost, assignment = parse_solver_output(output_file)

    if status == "UNSATISFIABLE":
        # Check if hard clauses are actually unsatisfiable
        if check_satisfiable(num_vars, hard_clauses):
            bugs.append("false_unsatisfiable")
        return len(bugs) == 0, bugs

    if status in ("OPTIMUM FOUND", "SATISFIABLE"):
        if assignment is None:
            bugs.append("missing_assignment")
            return False, bugs

        # Build assignment dict
        asgn_dict = {}
        for i, val in enumerate(assignment):
            asgn_dict[i + 1] = val

        # Check hard clauses
        for clause in hard_clauses:
            if not eval_clause(clause, asgn_dict):
                bugs.append("hard_clause_violation")
                break

        # Compute actual cost
        actual_cost = 0
        for weight, clause in soft_clauses:
            if not eval_clause(clause, asgn_dict):
                actual_cost += weight

        if cost is not None and actual_cost != cost:
            bugs.append("cost_mismatch")

        return len(bugs) == 0, bugs

    # Unknown or missing status
    bugs.append("invalid_status")
    return False, bugs


def main():
    if len(sys.argv) != 3:
        print("Usage: python3 verifier.py <wcnf_file> <output_file>", file=sys.stderr)
        sys.exit(1)

    wcnf_file = sys.argv[1]
    output_file = sys.argv[2]

    valid, bugs = verify(wcnf_file, output_file)

    if valid:
        print("VALID")
        sys.exit(0)
    else:
        print(f"INVALID: {', '.join(bugs)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
