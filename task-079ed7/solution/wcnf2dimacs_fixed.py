#!/usr/bin/env python3
"""
Fixed WCNF-to-DIMACS CNF converter.
Handles both new-format (h-lines) and old-format (p-line with top weight).

Usage: python3 wcnf2dimacs_fixed.py [-hards] <wcnf_file>
"""
import sys


def convert(wcnf_file, hards_only=False):
    hard_clauses = []
    soft_clauses = []
    max_var = 0
    top = None

    # First pass: detect format
    with open(wcnf_file) as f:
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
    with open(wcnf_file) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("c") or line.startswith("p"):
                continue
            tokens = line.split()

            if top is not None:
                # Old format
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
                    soft_clauses.append(lits)
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
                    lits = []
                    for t in tokens[1:]:
                        val = int(t)
                        if val == 0:
                            break
                        lits.append(val)
                        max_var = max(max_var, abs(val))
                    soft_clauses.append(lits)

    if hards_only:
        clauses = hard_clauses
    else:
        clauses = hard_clauses + soft_clauses

    print(f"p cnf {max_var} {len(clauses)}")
    for clause in clauses:
        print(" ".join(str(l) for l in clause) + " 0")


if __name__ == "__main__":
    hards = "-hards" in sys.argv
    args = [a for a in sys.argv[1:] if a != "-hards"]
    if not args:
        print("Usage: wcnf2dimacs_fixed.py [-hards] <wcnf_file>", file=sys.stderr)
        sys.exit(1)
    convert(args[0], hards)
