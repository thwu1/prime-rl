#!/usr/bin/env python3
"""Basic DPLL SAT solver for DIMACS CNF formulas.

Usage: python3 solve.py [--help] <formula.cnf>
"""
import sys


def parse_cnf(filename):
    """Parse a DIMACS CNF file. Returns (num_vars, list_of_clauses)."""
    clauses = []
    num_vars = 0
    current = []
    with open(filename) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("c") or line.startswith("%"):
                continue
            if line.startswith("p"):
                parts = line.split()
                num_vars = int(parts[2])
                continue
            for token in line.split():
                val = int(token)
                if val == 0:
                    if current:
                        clauses.append(current)
                    current = []
                else:
                    current.append(val)
    if current:
        clauses.append(current)
    return num_vars, clauses


def unit_propagate(clauses, assignment):
    """Perform unit propagation. Returns (conflict_found, assignment)."""
    changed = True
    while changed:
        changed = False
        for clause in clauses:
            unassigned = []
            satisfied = False
            for lit in clause:
                var = abs(lit)
                if var in assignment:
                    if (lit > 0) == assignment[var]:
                        satisfied = True
                        break
                else:
                    unassigned.append(lit)
            if satisfied:
                continue
            if len(unassigned) == 0:
                return True, assignment
            if len(unassigned) == 1:
                var = abs(unassigned[0])
                assignment[var] = unassigned[0] > 0
                changed = True
    return False, assignment


def all_satisfied(clauses, assignment):
    """Check if all clauses are satisfied under current assignment."""
    for clause in clauses:
        satisfied = False
        for lit in clause:
            var = abs(lit)
            if var in assignment and (lit > 0) == assignment[var]:
                satisfied = True
                break
        if not satisfied:
            return False
    return True


def dpll(clauses, assignment, num_vars):
    """DPLL recursive solver. Returns satisfying assignment or None."""
    conflict, assignment = unit_propagate(clauses, dict(assignment))
    if conflict:
        return None

    if all_satisfied(clauses, assignment):
        return assignment

    for v in range(1, num_vars + 1):
        if v not in assignment:
            for val in (True, False):
                new_assign = dict(assignment)
                new_assign[v] = val
                result = dpll(clauses, new_assign, num_vars)
                if result is not None:
                    return result
            return None

    return None


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print("DPLL SAT Solver")
        print("Usage: python3 solve.py <formula.cnf>")
        print()
        print("Reads a DIMACS CNF formula and determines satisfiability.")
        print("Output:")
        print("  First line: SAT or UNSAT")
        print("  If SAT, second line: satisfying assignment as")
        print("  space-separated literals terminated by 0")
        sys.exit(0 if len(sys.argv) > 1 else 1)

    num_vars, clauses = parse_cnf(sys.argv[1])
    result = dpll(clauses, {}, num_vars)

    if result is None:
        print("UNSAT")
    else:
        print("SAT")
        for v in range(1, num_vars + 1):
            if v not in result:
                result[v] = True
        lits = [str(v) if result[v] else str(-v) for v in range(1, num_vars + 1)]
        print(" ".join(lits) + " 0")


if __name__ == "__main__":
    main()
