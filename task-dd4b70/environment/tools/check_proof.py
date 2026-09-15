#!/usr/bin/env python3
"""DRAT proof checker for unsatisfiability certificates.

Usage: python3 check_proof.py [--help] <formula.cnf> <proof.drat>
"""
import json
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


def parse_proof(filename):
    """Parse a DRAT proof file into addition steps.

    Returns list of clause literal lists for each addition line.
    Lines beginning with 'c' or 'd' are informational and skipped.
    """
    steps = []
    with open(filename) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("c") or line.startswith("d"):
                continue
            lits = []
            for token in line.split():
                val = int(token)
                if val == 0:
                    break
                lits.append(val)
            steps.append(lits)
    return steps


def unit_propagate(clauses, assignment):
    """Perform unit propagation. Returns True if conflict found."""
    changed = True
    while changed:
        changed = False
        for clause in clauses:
            unassigned = []
            satisfied = False
            for lit in clause:
                var = abs(lit)
                if var in assignment:
                    val = assignment[var]
                    if (lit > 0 and val) or (lit < 0 and not val):
                        satisfied = True
                        break
                else:
                    unassigned.append(lit)
            if satisfied:
                continue
            if len(unassigned) == 0:
                return True
            if len(unassigned) == 1:
                lit = unassigned[0]
                var = abs(lit)
                assignment[var] = lit > 0
                changed = True
    return False


def check_rup(clauses, candidate):
    """Check if candidate clause has RUP w.r.t. clauses.

    Negate each literal in candidate, add as unit, propagate.
    Conflict means RUP holds.
    """
    assignment = {}
    for lit in candidate:
        var = abs(lit)
        assignment[var] = lit < 0
    return unit_propagate(clauses, assignment)


def check_rat(clauses, candidate):
    """Check if candidate has RAT property for some pivot literal.

    For pivot l in candidate: for every clause D containing -l,
    the resolvent must have RUP w.r.t. clauses.
    Tautological resolvents are trivially valid.
    """
    if not candidate:
        return False

    for pivot in candidate:
        neg_pivot = -pivot
        all_ok = True

        for clause in clauses:
            if neg_pivot not in clause:
                continue

            resolvent = set()
            for lit in candidate:
                if lit != pivot:
                    resolvent.add(lit)
            for lit in clause:
                if lit != neg_pivot:
                    resolvent.add(lit)

            if any(-lit in resolvent for lit in resolvent):
                continue

            if not check_rup(clauses, list(resolvent)):
                all_ok = False
                break

        if all_ok:
            return True

    return False


def main():
    if len(sys.argv) < 3 or sys.argv[1] in ("-h", "--help"):
        print("DRAT Proof Checker")
        print("Usage: python3 check_proof.py <formula.cnf> <proof.drat>")
        print()
        print("Verifies a DRAT (Deletion Resolution Asymmetric Tautology)")
        print("proof of unsatisfiability against a DIMACS CNF formula.")
        print("Each addition step is checked first for RUP, then RAT.")
        print()
        print("Output: JSON object with fields:")
        print('  {"valid": true/false, "first_invalid_step": null/int}')
        sys.exit(0 if sys.argv[1] in ("-h", "--help") else 1)

    _num_vars, clauses = parse_cnf(sys.argv[1])
    steps = parse_proof(sys.argv[2])

    clause_db = [list(c) for c in clauses]

    for i, lits in enumerate(steps, 1):
        if check_rup(clause_db, lits):
            clause_db.append(list(lits))
        elif check_rat(clause_db, lits):
            clause_db.append(list(lits))
        else:
            print(json.dumps({"valid": False, "first_invalid_step": i}))
            return

    print(json.dumps({"valid": True, "first_invalid_step": None}))


if __name__ == "__main__":
    main()
