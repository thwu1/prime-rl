Weighted directed graph instances are in `/app/instances/`. Each file uses:

```
n m
u v w
...
```

(`n` vertices, `m` directed edges, 1-indexed vertices, positive integer weights.)

For each instance, find an optimal **minimum weight feedback arc set** — a minimum-weight subset of edges whose removal makes the directed graph acyclic. Equivalently, find a linear ordering of vertices that maximizes the total weight of forward edges (those going from earlier to later in the ordering).

Encode each instance as a **Weighted Partial MaxSAT** problem in standard DIMACS WCNF format and solve it to provable optimality. Write the WCNF files to `/app/wcnf/` (one per instance, named `graph_XX.wcnf`).

Write final results to `/app/results.json`:

```json
{
  "graph_01": {
    "fas_edges": [[u1, v1], [u2, v2], ...],
    "fas_weight": 42,
    "ordering": [3, 1, 4, 2, ...]
  },
  ...
}
```

- `fas_edges`: directed edges in the minimum feedback arc set (as `[source, target]` pairs)
- `fas_weight`: total weight of removed edges (integer)
- `ordering`: a vertex permutation giving a topological order of the remaining DAG

All solutions must be optimal (minimum possible FAS weight).