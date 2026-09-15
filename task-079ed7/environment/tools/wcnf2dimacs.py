#!/usr/bin/env python3
"""Convert WCNF to DIMACS CNF format.
Extracts clauses from a WCNF file and outputs standard DIMACS CNF.
"""
import sys


def convert(wcnf_file, hards_only=False):
    clauses = []
    max_var = 0

    with open(wcnf_file) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("c") or line.startswith("p"):
                continue
            tokens = line.split()
            if tokens[0] == "h":
                # Hard clause in new format
                lits = [int(t) for t in tokens[1:] if t != "0"]
                clauses.append(lits)
                for l in lits:
                    max_var = max(max_var, abs(l))
            else:
                # Soft clause — skip in hards-only mode
                if hards_only:
                    continue
                # Strip weight, collect literals
                lits = [int(t) for t in tokens[1:] if t != "0"]
                clauses.append(lits)
                for l in lits:
                    max_var = max(max_var, abs(l))

    print(f"p cnf {max_var} {len(clauses)}")
    for clause in clauses:
        print(" ".join(str(l) for l in clause) + " 0")


if __name__ == "__main__":
    hards = "-hards" in sys.argv
    args = [a for a in sys.argv[1:] if a != "-hards"]
    if not args:
        print("Usage: wcnf2dimacs.py [-hards] <wcnf_file>", file=sys.stderr)
        sys.exit(1)
    convert(args[0], hards)
