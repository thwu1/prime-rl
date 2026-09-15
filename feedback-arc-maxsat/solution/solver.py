#!/usr/bin/env python3
"""Solve Minimum Feedback Arc Set via Weighted Partial MaxSAT encoding.


Encoding:
  - Order variable x_{i,j} for each pair (i<j): true iff i precedes j
  - Hard clauses: two transitivity constraints per vertex triple
  - Soft clauses: one per directed edge, weight = edge weight,
    satisfied when the edge is forward in the ordering
  - Optimal cost = minimum feedback arc set weight
"""

import json
import os
from functools import cmp_to_key
from pysat.examples.rc2 import RC2
from pysat.formula import WCNF


def read_graph(filepath):
    with open(filepath) as f:
        n, m = map(int, f.readline().split())
        edges = []
        for _ in range(m):
            u, v, w = map(int, f.readline().split())
            edges.append((u, v, w))
    return n, edges


def write_wcnf_file(path, num_vars, hard_clauses, soft_clauses):
    """Write WCNF file in standard DIMACS format with proper p wcnf header."""
    total_clauses = len(hard_clauses) + len(soft_clauses)
    # top weight must exceed sum of all soft weights
    top_weight = sum(w for w, _ in soft_clauses) + 1

    with open(path, 'w') as f:
        f.write(f'c Weighted Partial MaxSAT encoding of Minimum FAS\n')
        f.write(f'p wcnf {num_vars} {total_clauses} {top_weight}\n')
        # Hard clauses: prefixed with top weight
        for clause in hard_clauses:
            f.write(f'{top_weight} {" ".join(str(l) for l in clause)} 0\n')
        # Soft clauses: prefixed with their own weight
        for weight, clause in soft_clauses:
            f.write(f'{weight} {" ".join(str(l) for l in clause)} 0\n')


def solve_fas(n, edges, wcnf_path=None):
    """Encode minimum FAS as Weighted Partial MaxSAT and solve."""
    wcnf = WCNF()

    # Variable mapping: x_{i,j} for i < j means "i precedes j"
    var_map = {}
    idx = 0
    for i in range(1, n + 1):
        for j in range(i + 1, n + 1):
            idx += 1
            var_map[(i, j)] = idx
    num_vars = idx

    # Collect hard and soft clauses for WCNF file writing
    hard_clauses = []
    soft_clauses = []

    # Hard clauses: transitivity constraints
    for i in range(1, n + 1):
        for j in range(i + 1, n + 1):
            for k in range(j + 1, n + 1):
                xij = var_map[(i, j)]
                xjk = var_map[(j, k)]
                xik = var_map[(i, k)]
                clause1 = [-xij, -xjk, xik]
                clause2 = [xij, xjk, -xik]
                wcnf.append(clause1)
                wcnf.append(clause2)
                hard_clauses.append(clause1)
                hard_clauses.append(clause2)

    # Soft clauses: prefer each directed edge to be forward
    for u, v, w in edges:
        if u < v:
            lit = var_map[(u, v)]   # u before v
        else:
            lit = -var_map[(v, u)]  # u before v means NOT (v before u)
        wcnf.append([lit], weight=w)
        soft_clauses.append((w, [lit]))

    # Write WCNF file in standard DIMACS format
    if wcnf_path:
        write_wcnf_file(wcnf_path, num_vars, hard_clauses, soft_clauses)

    # Solve
    with RC2(wcnf) as solver:
        model = solver.compute()
        if model is None:
            return None

    # Decode the linear ordering from the model
    model_set = set(model)

    def before(a, b):
        """Return True if a precedes b according to the model."""
        if a < b:
            return var_map[(a, b)] in model_set
        else:
            return var_map[(b, a)] not in model_set

    vertices = list(range(1, n + 1))
    vertices.sort(key=cmp_to_key(
        lambda a, b: -1 if before(a, b) else (1 if before(b, a) else 0)
    ))

    # Extract feedback arc set: edges that go backward in the ordering
    pos = {v: i for i, v in enumerate(vertices)}
    fas_edges = []
    fas_weight = 0
    for u, v, w in edges:
        if pos[u] > pos[v]:
            fas_edges.append([u, v])
            fas_weight += w

    return {
        'fas_edges': fas_edges,
        'fas_weight': fas_weight,
        'ordering': vertices,
    }


def main():
    os.makedirs('/app/wcnf', exist_ok=True)
    results = {}

    for fn in sorted(os.listdir('/app/instances')):
        if not fn.endswith('.txt'):
            continue
        name = fn[:-4]
        filepath = os.path.join('/app/instances', fn)
        wcnf_path = os.path.join('/app/wcnf', f'{name}.wcnf')

        n, edges = read_graph(filepath)
        print(f'Solving {name} (n={n}, m={len(edges)})...')
        res = solve_fas(n, edges, wcnf_path)
        if res:
            results[name] = res
            print(f'  FAS weight={res["fas_weight"]}, |FAS|={len(res["fas_edges"])}')
        else:
            print(f'  ERROR: could not solve')

    with open('/app/results.json', 'w') as f:
        json.dump(results, f, indent=2)
    print('Results written to /app/results.json')


if __name__ == '__main__':
    main()
