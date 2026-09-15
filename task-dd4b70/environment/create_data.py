#!/usr/bin/env python3
"""Generate SAT competition audit data files during Docker build."""
import json
import os

# ---------- Benchmark CNF formulas ----------

BENCHMARKS = {
    "simple_unsat": (
        "c 4-variable unsatisfiable formula\n"
        "c From SAT competition benchmark collection\n"
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
    "random_sat": (
        "c Random 3-SAT instance, 5 variables, 6 clauses\n"
        "c Generated with clause/variable ratio 1.2\n"
        "p cnf 5 6\n"
        "1 2 3 0\n"
        "-1 -2 4 0\n"
        "2 -3 5 0\n"
        "-2 3 -4 0\n"
        "1 -4 -5 0\n"
        "-1 3 5 0\n"
    ),
    "pigeon_hole": (
        "c Pigeonhole Principle PHP(3,2)\n"
        "c 3 pigeons into 2 holes - classic UNSAT\n"
        "c Variables: p_{i,j} = pigeon i in hole j\n"
        "c p_{1,1}=1 p_{1,2}=2 p_{2,1}=3 p_{2,2}=4 p_{3,1}=5 p_{3,2}=6\n"
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
    "graph_color": (
        "c 3-coloring of path graph P4 (4 vertices, edges 1-2, 2-3, 3-4)\n"
        "c Variables: v_{i,c} for vertex i in {1..4}, color c in {1..3}\n"
        "c v_{1,1}=1 v_{1,2}=2 v_{1,3}=3 v_{2,1}=4 ... v_{4,3}=12\n"
        "p cnf 12 25\n"
        "1 2 3 0\n"
        "4 5 6 0\n"
        "7 8 9 0\n"
        "10 11 12 0\n"
        "-1 -2 0\n"
        "-1 -3 0\n"
        "-2 -3 0\n"
        "-4 -5 0\n"
        "-4 -6 0\n"
        "-5 -6 0\n"
        "-7 -8 0\n"
        "-7 -9 0\n"
        "-8 -9 0\n"
        "-10 -11 0\n"
        "-10 -12 0\n"
        "-11 -12 0\n"
        "-1 -4 0\n"
        "-2 -5 0\n"
        "-3 -6 0\n"
        "-4 -7 0\n"
        "-5 -8 0\n"
        "-6 -9 0\n"
        "-7 -10 0\n"
        "-8 -11 0\n"
        "-9 -12 0\n"
    ),
    "parity_chain": (
        "c Parity chain: XOR(x1,x2)=1 AND XOR(x2,x3)=1 AND XOR(x1,x3)=1\n"
        "c This system is unsatisfiable over Boolean domain\n"
        "p cnf 3 6\n"
        "1 2 0\n"
        "-1 -2 0\n"
        "2 3 0\n"
        "-2 -3 0\n"
        "1 3 0\n"
        "-1 -3 0\n"
    ),
    "planning": (
        "c Implication chain planning formula\n"
        "c Models causal dependencies between state variables\n"
        "p cnf 4 5\n"
        "1 2 0\n"
        "-1 3 0\n"
        "-2 3 0\n"
        "-3 4 0\n"
        "1 -4 0\n"
    ),
    "mutex": (
        "c Mutual exclusion: all 4 binary clauses on 2 variables\n"
        "c Every truth assignment falsifies at least one clause\n"
        "p cnf 2 4\n"
        "1 2 0\n"
        "-1 2 0\n"
        "1 -2 0\n"
        "-1 -2 0\n"
    ),
    "horn": (
        "c Horn-like formula with unit propagation chain\n"
        "c Satisfiable by forward chaining from unit clause\n"
        "p cnf 4 5\n"
        "1 -2 0\n"
        "2 -3 0\n"
        "3 -4 0\n"
        "4 0\n"
        "-1 3 0\n"
    ),
}

# ---------- DRAT proofs for claimed-UNSAT instances ----------

PROOFS = {
    # Valid RUP proof for simple_unsat
    "simple_unsat": (
        "1 2 0\n"
        "1 0\n"
        "2 0\n"
        "0\n"
    ),
    # Valid RUP proof for pigeon_hole
    "pigeon_hole": (
        "2 4 0\n"
        "2 6 0\n"
        "4 6 0\n"
        "2 0\n"
        "4 0\n"
        "6 0\n"
        "0\n"
    ),
    # Fabricated proof for graph_color (formula is actually SAT)
    "graph_color": (
        "1 4 0\n"
        "0\n"
    ),
    # Proof with deletion steps for mutex
    # INVALID when deletions are applied correctly:
    #   after deleting (-1 2) and (-1 -2), adding (-1) fails RUP
    # APPEARS VALID when deletions are ignored (check_proof.py bug)
    "mutex": (
        "d -1 2 0\n"
        "d -1 -2 0\n"
        "-1 0\n"
        "0\n"
    ),
}

# ---------- Assignments for claimed-SAT instances ----------

ASSIGNMENTS = {
    # Valid assignment for random_sat: x1=T x2=T x3=T x4=T x5=T
    "random_sat": "1 2 3 4 5 0\n",
    # Invalid assignment for parity_chain (formula is UNSAT)
    # Clause 6 (-1 -3) is violated: x1=T, x3=T -> -1=F, -3=F
    "parity_chain": "1 -2 3 0\n",
    # Invalid assignment for planning (formula IS SAT but this assignment is wrong)
    # Clause 2 (-1 3) is violated: x1=T, x3=F -> -1=F, 3=F
    "planning": "1 2 -3 4 0\n",
    # Valid assignment for horn: x1=T x2=T x3=T x4=T
    "horn": "1 2 3 4 0\n",
}

# ---------- Claimed results ----------

CLAIMED_RESULTS = {
    "simple_unsat": {
        "verdict": "UNSAT",
        "certificate": "proofs/simple_unsat.drat",
    },
    "random_sat": {
        "verdict": "SAT",
        "certificate": "assignments/random_sat.txt",
    },
    "pigeon_hole": {
        "verdict": "UNSAT",
        "certificate": "proofs/pigeon_hole.drat",
    },
    "graph_color": {
        "verdict": "UNSAT",
        "certificate": "proofs/graph_color.drat",
    },
    "parity_chain": {
        "verdict": "SAT",
        "certificate": "assignments/parity_chain.txt",
    },
    "planning": {
        "verdict": "SAT",
        "certificate": "assignments/planning.txt",
    },
    "mutex": {
        "verdict": "UNSAT",
        "certificate": "proofs/mutex.drat",
    },
    "horn": {
        "verdict": "SAT",
        "certificate": "assignments/horn.txt",
    },
}


def main():
    base = "/app"

    # Create directories
    for d in ["benchmarks", "claimed/assignments", "claimed/proofs"]:
        os.makedirs(os.path.join(base, d), exist_ok=True)

    # Write benchmark files
    for name, content in BENCHMARKS.items():
        path = os.path.join(base, "benchmarks", f"{name}.cnf")
        with open(path, "w") as f:
            f.write(content)

    # Write proof files
    for name, content in PROOFS.items():
        path = os.path.join(base, "claimed", "proofs", f"{name}.drat")
        with open(path, "w") as f:
            f.write(content)

    # Write assignment files
    for name, content in ASSIGNMENTS.items():
        path = os.path.join(base, "claimed", "assignments", f"{name}.txt")
        with open(path, "w") as f:
            f.write(content)

    # Write claimed results
    path = os.path.join(base, "claimed", "results.json")
    with open(path, "w") as f:
        json.dump(CLAIMED_RESULTS, f, indent=2)

    print(f"Created {len(BENCHMARKS)} benchmarks, "
          f"{len(PROOFS)} proofs, {len(ASSIGNMENTS)} assignments")


if __name__ == "__main__":
    main()
