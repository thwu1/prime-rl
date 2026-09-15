#!/usr/bin/env python3
"""
SAT-based graph chromatic number determination with DRAT proof verification.

Encodes k-vertex-coloring as a DIMACS CNF formula, uses CaDiCaL to solve,
and generates/verifies DRAT proofs of unsatisfiability for optimality.
"""

import json
import os
import subprocess
import sys


def read_graph(filepath):
    """Read graph from edge list file (first line: n m, then m lines of u v)."""
    with open(filepath) as f:
        n, m = map(int, f.readline().split())
        edges = []
        for _ in range(m):
            u, v = map(int, f.readline().split())
            edges.append((u, v))
    return n, edges


def var(v, c, k):
    """Boolean variable index for 'vertex v has color c' (1-indexed for DIMACS)."""
    return v * k + c + 1


def encode_coloring(n, edges, k):
    """Encode k-coloring of graph as DIMACS CNF.

    Variables: x_{v,c} = v*k + c + 1  for v in [0..n), c in [0..k)

    Clauses:
      (1) At least one color per vertex:
            (x_{v,0} OR x_{v,1} OR ... OR x_{v,k-1})  for each v
      (2) At most one color per vertex:
            (NOT x_{v,c1} OR NOT x_{v,c2})  for each v, c1 < c2
      (3) Adjacent vertices differ:
            (NOT x_{u,c} OR NOT x_{w,c})  for each edge (u,w), each color c
    """
    clauses = []

    for v in range(n):
        clauses.append([var(v, c, k) for c in range(k)])

    for v in range(n):
        for c1 in range(k):
            for c2 in range(c1 + 1, k):
                clauses.append([-var(v, c1, k), -var(v, c2, k)])

    for u, w in edges:
        for c in range(k):
            clauses.append([-var(u, c, k), -var(w, c, k)])

    num_vars = n * k
    return num_vars, clauses


def write_cnf(filepath, num_vars, clauses):
    """Write clauses in DIMACS CNF format."""
    with open(filepath, "w") as f:
        f.write(f"p cnf {num_vars} {len(clauses)}\n")
        for clause in clauses:
            f.write(" ".join(map(str, clause)) + " 0\n")


def run_cadical(cnf_path, proof_path=None):
    """Invoke CaDiCaL on a CNF file. Returns (is_sat, model_set_or_None)."""
    cmd = ["cadical", cnf_path]
    if proof_path:
        cmd.append(proof_path)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)

    if result.returncode == 10:  # SATISFIABLE
        model = set()
        for line in result.stdout.splitlines():
            if line.startswith("v "):
                for tok in line[2:].split():
                    val = int(tok)
                    if val != 0:
                        model.add(val)
        return True, model
    elif result.returncode == 20:  # UNSATISFIABLE
        return False, None
    else:
        raise RuntimeError(
            f"CaDiCaL returned unexpected code {result.returncode}.\n"
            f"stderr: {result.stderr[:500]}"
        )


def verify_drat(cnf_path, proof_path):
    """Verify a DRAT proof with drat-trim. Returns True if verified."""
    result = subprocess.run(
        ["drat-trim", cnf_path, proof_path],
        capture_output=True,
        text=True,
        timeout=300,
    )
    combined = result.stdout + result.stderr
    return "VERIFIED" in combined


def decode_coloring(model, n, k):
    """Extract vertex coloring from a SAT model."""
    coloring = {}
    for v in range(n):
        for c in range(k):
            if var(v, c, k) in model:
                coloring[str(v)] = c
                break
    return coloring


def validate_coloring(coloring, n, edges):
    """Check that a coloring is a valid proper coloring."""
    for v in range(n):
        if str(v) not in coloring:
            return False, f"vertex {v} uncolored"
    for u, v in edges:
        if coloring[str(u)] == coloring[str(v)]:
            return False, f"conflict on edge ({u},{v})"
    return True, "ok"


def find_chromatic_number(n, edges, result_dir):
    """Determine exact chromatic number by binary search on k-colorability."""
    os.makedirs(result_dir, exist_ok=True)

    lo, hi = 1, n
    best_k = n
    best_coloring = None

    while lo <= hi:
        mid = (lo + hi) // 2
        num_vars, clauses = encode_coloring(n, edges, mid)
        cnf_path = os.path.join(result_dir, f"_tmp_{mid}.cnf")
        write_cnf(cnf_path, num_vars, clauses)

        sat, model = run_cadical(cnf_path)
        os.remove(cnf_path)

        if sat:
            coloring = decode_coloring(model, n, mid)
            ok, msg = validate_coloring(coloring, n, edges)
            if not ok:
                raise RuntimeError(f"Invalid coloring for k={mid}: {msg}")
            best_k = mid
            best_coloring = coloring
            hi = mid - 1
        else:
            lo = mid + 1

    chi = best_k

    # Write chromatic number
    with open(os.path.join(result_dir, "chromatic_number.txt"), "w") as f:
        f.write(str(chi))

    # Write valid coloring
    with open(os.path.join(result_dir, "coloring.json"), "w") as f:
        json.dump(best_coloring, f, indent=2)

    # Generate and verify DRAT proof for (chi-1)-coloring being UNSAT
    k_unsat = chi - 1
    num_vars, clauses = encode_coloring(n, edges, k_unsat)
    cnf_path = os.path.join(result_dir, "unsat.cnf")
    proof_path = os.path.join(result_dir, "proof.drat")
    write_cnf(cnf_path, num_vars, clauses)

    sat, _ = run_cadical(cnf_path, proof_path)
    if sat:
        raise RuntimeError(f"Expected UNSAT for k={k_unsat} but got SAT")

    verified = verify_drat(cnf_path, proof_path)
    with open(os.path.join(result_dir, "proof_verified.txt"), "w") as f:
        f.write("VERIFIED" if verified else "FAILED")

    if not verified:
        print(f"WARNING: DRAT proof verification failed for k={k_unsat}",
              file=sys.stderr)

    return chi


def main():
    instances_dir = "/app/instances"
    results_base = "/app/results"

    for graph_file in sorted(os.listdir(instances_dir)):
        if not graph_file.endswith(".edgelist"):
            continue
        graph_name = graph_file.replace(".edgelist", "")
        graph_path = os.path.join(instances_dir, graph_file)
        result_dir = os.path.join(results_base, graph_name)

        print(f"Processing {graph_name}...")
        n, edges = read_graph(graph_path)
        print(f"  vertices={n}, edges={len(edges)}")

        chi = find_chromatic_number(n, edges, result_dir)
        print(f"  chromatic number = {chi}")
        print(f"  results -> {result_dir}/")


if __name__ == "__main__":
    main()
