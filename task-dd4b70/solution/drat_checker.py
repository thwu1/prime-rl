#!/usr/bin/env python3
"""DRAT (Delete Resolution Asymmetric Tautology) proof checker.

Usage: python3 checker.py <formula.cnf> <proof.drat>
Output: JSON line {"valid": bool, "first_bad_step": int|null}
"""

import json
import sys


def parse_cnf(filename):
    """Parse a DIMACS CNF file into (num_vars, list_of_clauses)."""
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
                    clauses.append(current)
                    current = []
                else:
                    current.append(val)
    if current:
        clauses.append(current)
    return num_vars, clauses


def parse_proof(filename):
    """Parse a DRAT proof file into list of (type, literals) steps.

    type is 'a' (addition) or 'd' (deletion).
    """
    steps = []
    with open(filename) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("c"):
                continue
            is_delete = False
            if line.startswith("d ") or line.startswith("d\t"):
                is_delete = True
                line = line[1:].strip()
            lits = []
            for token in line.split():
                val = int(token)
                if val == 0:
                    break
                lits.append(val)
            steps.append(("d" if is_delete else "a", lits))
    return steps


def unit_propagate(clauses, assignment):
    """Perform unit propagation. Return True if conflict found.

    Modifies assignment dict in-place: {var: bool_value}.
    """
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
                return True  # conflict: all lits false
            if len(unassigned) == 1:
                lit = unassigned[0]
                var = abs(lit)
                assignment[var] = lit > 0
                changed = True
    return False


def check_rup(clauses, candidate):
    """Check if candidate clause has the RUP property w.r.t. clauses.

    RUP: negate each literal in candidate, add as unit, propagate.
    If conflict -> RUP holds.
    """
    assignment = {}
    for lit in candidate:
        var = abs(lit)
        # Negate the literal: if lit is positive, set var=False; if negative, set var=True
        assignment[var] = lit < 0
    return unit_propagate(clauses, assignment)


def check_rat(clauses, candidate):
    """Check if candidate has the RAT property for some pivot literal.

    For pivot l in candidate: for every clause D in clauses containing -l,
    the resolvent (candidate\\{l}) union (D\\{-l}) must have RUP w.r.t. clauses.
    Tautological resolvents (containing both x and -x) are trivially valid.
    """
    if not candidate:
        return False  # empty clause has no pivot

    for pivot in candidate:
        neg_pivot = -pivot
        all_ok = True

        for clause in clauses:
            if neg_pivot not in clause:
                continue

            # Compute resolvent
            resolvent = set()
            for lit in candidate:
                if lit != pivot:
                    resolvent.add(lit)
            for lit in clause:
                if lit != neg_pivot:
                    resolvent.add(lit)

            # Skip tautological resolvents
            is_taut = any(-lit in resolvent for lit in resolvent)
            if is_taut:
                continue

            # Check RUP of resolvent
            if not check_rup(clauses, list(resolvent)):
                all_ok = False
                break

        if all_ok:
            return True  # RAT holds for this pivot (vacuously if no partners)

    return False


def check_drat(formula_file, proof_file):
    """Run the DRAT proof checker. Return {valid, first_bad_step}."""
    _num_vars, clauses = parse_cnf(formula_file)
    steps = parse_proof(proof_file)

    # Clause database: list of lists
    clause_db = [list(c) for c in clauses]

    for i, (step_type, lits) in enumerate(steps, 1):
        if step_type == "d":
            # Deletion: remove first matching clause (by content, order-independent)
            target = sorted(lits)
            for j, c in enumerate(clause_db):
                if sorted(c) == target:
                    clause_db.pop(j)
                    break
            # If clause not found, deletion is a no-op (valid per spec)
        else:
            # Addition: try RUP first, then RAT
            if check_rup(clause_db, lits):
                clause_db.append(list(lits))
            elif check_rat(clause_db, lits):
                clause_db.append(list(lits))
            else:
                return {"valid": False, "first_bad_step": i}

    return {"valid": True, "first_bad_step": None}


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <formula.cnf> <proof.drat>", file=sys.stderr)
        sys.exit(1)
    result = check_drat(sys.argv[1], sys.argv[2])
    print(json.dumps(result))
