#!/usr/bin/env python3

"""
Solves all MaxSAT instances using PySAT's RC2 solver.
Handles graph encoding, opaque WCNF solving, and mystery reverse-engineering.
"""

import json
import os
from pysat.formula import WCNF
from pysat.examples.rc2 import RC2


def load_graph(filepath):
    with open(filepath) as f:
        return json.load(f)


def encode_vertex_cover_wcnf(graph, output_path):
    """Encode weighted minimum vertex cover as WCNF and write to file."""
    n = graph["num_vertices"]
    weights = graph["weights"]
    edges = graph["edges"]

    wcnf = WCNF()

    # Hard clauses: for each edge (u, v), at least one endpoint in cover
    for u, v in edges:
        wcnf.append([u + 1, v + 1])

    # Soft clauses: penalize including each vertex (minimize cover weight)
    for i in range(n):
        wcnf.append([-(i + 1)], weight=weights[i])

    # Also write raw WCNF file
    top = sum(weights) + 1
    num_clauses = len(edges) + n
    lines = [f"p wcnf {n} {num_clauses} {top}"]
    for u, v in edges:
        lines.append(f"{top} {u + 1} {v + 1} 0")
    for i in range(n):
        lines.append(f"{weights[i]} -{i + 1} 0")

    with open(output_path, "w") as f:
        f.write("\n".join(lines) + "\n")

    return wcnf


def solve_wcnf(wcnf):
    """Solve a WCNF instance using RC2, return (cost, model)."""
    with RC2(wcnf) as solver:
        model = solver.compute()
        cost = solver.cost
    return cost, model


def parse_wcnf_file(filepath):
    """Parse a WCNF file into a PySAT WCNF object and raw components."""
    wcnf = WCNF(from_file=filepath)

    # Also parse raw for analysis
    num_vars = 0
    top = 0
    hard_clauses = []
    soft_clauses = []
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("c"):
                continue
            if line.startswith("p"):
                parts = line.split()
                num_vars = int(parts[2])
                top = int(parts[4])
                continue
            tokens = list(map(int, line.split()))
            weight = tokens[0]
            lits = tokens[1:-1]
            if weight >= top:
                hard_clauses.append(lits)
            else:
                soft_clauses.append((weight, lits))

    return wcnf, num_vars, top, hard_clauses, soft_clauses


def reverse_engineer_vc(num_vars, hard_clauses, soft_clauses):
    """Extract graph structure from a vertex cover WCNF encoding."""
    edges = []
    for clause in hard_clauses:
        if len(clause) == 2 and all(l > 0 for l in clause):
            u, v = clause[0] - 1, clause[1] - 1
            edges.append([min(u, v), max(u, v)])

    weights = [0] * num_vars
    for weight, clause in soft_clauses:
        if len(clause) == 1 and clause[0] < 0:
            var_idx = -clause[0] - 1
            weights[var_idx] = weight

    return {
        "num_vertices": num_vars,
        "edges": sorted(edges),
        "weights": weights,
    }


def model_to_vc(model, weights):
    """Convert SAT model to vertex cover solution."""
    vertices = sorted(abs(lit) - 1 for lit in model if lit > 0)
    weight = sum(weights[v] for v in vertices)
    return vertices, weight


def main():
    os.makedirs("/app/encodings", exist_ok=True)
    os.makedirs("/app/solutions", exist_ok=True)

    # ---- Process graph instances ----
    graph_dir = "/app/graphs"
    for fname in sorted(os.listdir(graph_dir)):
        if not fname.endswith(".json"):
            continue
        name = fname[:-5]
        print(f"Processing graph: {name}")

        graph = load_graph(os.path.join(graph_dir, fname))
        wcnf_path = f"/app/encodings/{name}.wcnf"
        wcnf = encode_vertex_cover_wcnf(graph, wcnf_path)

        cost, model = solve_wcnf(wcnf)
        vertices, weight = model_to_vc(model, graph["weights"])

        solution = {"vertices": vertices, "weight": weight}
        with open(f"/app/solutions/{name}.json", "w") as f:
            json.dump(solution, f, indent=2)
        print(f"  weight={weight}, vertices={vertices}")

    # ---- Process opaque WCNF instances ----
    instance_dir = "/app/instances"
    for fname in sorted(os.listdir(instance_dir)):
        if not fname.endswith(".wcnf"):
            continue
        name = fname[:-5]
        print(f"Processing instance: {name}")

        wcnf, num_vars, top, hard, soft = parse_wcnf_file(
            os.path.join(instance_dir, fname)
        )
        cost, model = solve_wcnf(wcnf)

        # Build full assignment covering all variables
        model_set = set(model)
        assignment = []
        for v in range(1, num_vars + 1):
            if v in model_set:
                assignment.append(v)
            elif -v in model_set:
                assignment.append(-v)
            else:
                assignment.append(-v)

        solution = {"cost": cost, "assignment": assignment}
        with open(f"/app/solutions/{name}.json", "w") as f:
            json.dump(solution, f, indent=2)
        print(f"  cost={cost}")

    # ---- Process mystery instances ----
    mystery_dir = "/app/mystery_instances"
    for fname in sorted(os.listdir(mystery_dir)):
        if not fname.endswith(".wcnf"):
            continue
        name = fname[:-5]
        print(f"Processing mystery: {name}")

        wcnf, num_vars, top, hard, soft = parse_wcnf_file(
            os.path.join(mystery_dir, fname)
        )

        graph = reverse_engineer_vc(num_vars, hard, soft)
        print(f"  decoded: {graph['num_vertices']} verts, {len(graph['edges'])} edges")

        cost, model = solve_wcnf(wcnf)
        vertices, weight = model_to_vc(model, graph["weights"])

        solution = {"vertices": vertices, "weight": weight, "graph": graph}
        with open(f"/app/solutions/{name}.json", "w") as f:
            json.dump(solution, f, indent=2)
        print(f"  weight={weight}, vertices={vertices}")

    print("\nAll instances processed.")


if __name__ == "__main__":
    main()
