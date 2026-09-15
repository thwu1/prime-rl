#!/usr/bin/env python3
"""Create DRAT proof checker instance files during Docker build."""
import os

INSTANCES = {
    "basic_rup": {
        "formula.cnf": (
            "c SAT Competition example formula\n"
            "c 4 variables, 8 clauses, UNSATISFIABLE\n"
            "p cnf 4 8\n"
            "1 2 -3 0\n"
            "-1 -2 3 0\n"
            "2 3 -4 0\n"
            "-2 -3 4 0\n"
            "1 3 4 0\n"
            "-1 -3 -4 0\n"
            "-1 2 4 0\n"
            "1 -2 -4 0\n"
        ),
        "proof.drat": (
            "1 2 0\n"
            "1 0\n"
            "2 0\n"
            "0\n"
        ),
    },
    "php32": {
        "formula.cnf": (
            "c Pigeonhole Principle PHP(3,2)\n"
            "c 3 pigeons, 2 holes - UNSATISFIABLE\n"
            "c Variables: p_{i,j} = pigeon i in hole j\n"
            "c p_{1,1}=1, p_{1,2}=2, p_{2,1}=3, p_{2,2}=4, p_{3,1}=5, p_{3,2}=6\n"
            "p cnf 6 9\n"
            "1 2 0\n"
            "3 4 0\n"
            "5 6 0\n"
            "-1 -3 0\n"
            "-1 -5 0\n"
            "-3 -5 0\n"
            "-2 -4 0\n"
            "-2 -6 0\n"
            "-4 -6 0\n"
        ),
        "proof.drat": (
            "2 4 0\n"
            "2 6 0\n"
            "4 6 0\n"
            "2 0\n"
            "4 0\n"
            "6 0\n"
            "0\n"
        ),
    },
    "drup_delete": {
        "formula.cnf": (
            "c SAT Competition example formula (same as basic_rup)\n"
            "c 4 variables, 8 clauses, UNSATISFIABLE\n"
            "p cnf 4 8\n"
            "1 2 -3 0\n"
            "-1 -2 3 0\n"
            "2 3 -4 0\n"
            "-2 -3 4 0\n"
            "1 3 4 0\n"
            "-1 -3 -4 0\n"
            "-1 2 4 0\n"
            "1 -2 -4 0\n"
        ),
        "proof.drat": (
            "1 2 0\n"
            "d 1 2 -3 0\n"
            "1 0\n"
            "d 1 2 0\n"
            "d 1 3 4 0\n"
            "d 1 -2 -4 0\n"
            "2 0\n"
            "0\n"
        ),
    },
    "rat_proof": {
        "formula.cnf": (
            "c All 8 possible 3-literal clauses on 3 variables\n"
            "c UNSATISFIABLE (every assignment falsifies exactly one clause)\n"
            "p cnf 3 8\n"
            "1 2 3 0\n"
            "1 2 -3 0\n"
            "1 -2 3 0\n"
            "1 -2 -3 0\n"
            "-1 2 3 0\n"
            "-1 2 -3 0\n"
            "-1 -2 3 0\n"
            "-1 -2 -3 0\n"
        ),
        "proof.drat": (
            "1 0\n"
            "2 0\n"
            "-1 0\n"
            "-2 0\n"
            "0\n"
        ),
    },
    "invalid_sat": {
        "formula.cnf": (
            "c A satisfiable formula - no valid UNSAT proof exists\n"
            "c SAT: e.g. x1=T, x2=T, x3=F\n"
            "p cnf 3 2\n"
            "1 2 3 0\n"
            "-1 -2 -3 0\n"
        ),
        "proof.drat": (
            "1 0\n"
            "-1 0\n"
            "0\n"
        ),
    },
    "invalid_deletion": {
        "formula.cnf": (
            "c Complete binary clauses on 2 variables - UNSATISFIABLE\n"
            "p cnf 2 4\n"
            "1 2 0\n"
            "-1 2 0\n"
            "1 -2 0\n"
            "-1 -2 0\n"
        ),
        "proof.drat": (
            "d 1 2 0\n"
            "d -1 2 0\n"
            "d 1 -2 0\n"
            "1 0\n"
            "0\n"
        ),
    },
}


def main():
    for name, files in INSTANCES.items():
        dirpath = os.path.join("/app/instances", name)
        os.makedirs(dirpath, exist_ok=True)
        for filename, content in files.items():
            filepath = os.path.join(dirpath, filename)
            with open(filepath, "w") as f:
                f.write(content)
    print(f"Created {len(INSTANCES)} instances in /app/instances/")


if __name__ == "__main__":
    main()
