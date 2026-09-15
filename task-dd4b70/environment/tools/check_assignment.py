#!/usr/bin/env python3
"""Verify a satisfying assignment against a DIMACS CNF formula.

Usage: python3 check_assignment.py [--help] <formula.cnf> <assignment.txt>
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


def parse_assignment(filename):
    """Parse an assignment file. Returns dict {var: bool}."""
    assignment = {}
    with open(filename) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("c"):
                continue
            if line.startswith("v"):
                line = line[1:].strip()
            for token in line.split():
                val = int(token)
                if val == 0:
                    break
                var = abs(val)
                assignment[var] = val > 0
    return assignment


def main():
    if len(sys.argv) < 3 or sys.argv[1] in ("-h", "--help"):
        print("SAT Assignment Verifier")
        print("Usage: python3 check_assignment.py <formula.cnf> <assignment.txt>")
        print()
        print("Checks whether an assignment satisfies all clauses in a")
        print("DIMACS CNF formula. The assignment file should contain")
        print("space-separated literals (positive=true, negative=false)")
        print("optionally terminated by 0. Lines starting with 'v' or 'c'")
        print("follow SAT competition output format.")
        print()
        print("Output: VALID or INVALID with the failing clause.")
        sys.exit(0 if sys.argv[1] in ("-h", "--help") else 1)

    num_vars, clauses = parse_cnf(sys.argv[1])
    assignment = parse_assignment(sys.argv[2])

    for i, clause in enumerate(clauses, 1):
        satisfied = False
        for lit in clause:
            var = abs(lit)
            if var in assignment and (lit > 0) == assignment[var]:
                satisfied = True
                break
        if not satisfied:
            print(f"INVALID: clause {i} not satisfied: {clause}")
            sys.exit(1)

    print("VALID")


if __name__ == "__main__":
    main()
