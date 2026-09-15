You are given a collection of combinatorial optimization problems in `/app/` that span three categories, all connected through the Weighted Partial MaxSAT framework. You must solve each one optimally and produce the required output files.

`/app/format_spec.txt` documents the WCNF file format used throughout.

## Graph Vertex Cover (`/app/graphs/`)

JSON files describe weighted undirected graphs (0-indexed vertices, integer per-vertex costs). For each graph `{name}.json`, produce:

- `/app/encodings/{name}.wcnf` -- a valid Weighted Partial MaxSAT encoding of the weighted minimum vertex cover problem for that graph.
- `/app/solutions/{name}.json` -- `{"vertices": [0-indexed IDs], "weight": <total weight>}` with an optimal minimum-weight cover.

## Opaque WCNF Instances (`/app/instances/`)

Standalone WCNF files encoding arbitrary combinatorial problems (not vertex cover). For each `{name}.wcnf`, produce:

- `/app/solutions/{name}.json` -- `{"cost": <optimal cost>, "assignment": [signed DIMACS literals, one per variable]}`

The cost is the minimum total weight of unsatisfied soft clauses. The assignment must satisfy all hard clauses.

## Mystery Instances (`/app/mystery_instances/`)

WCNF files that each encode a weighted minimum vertex cover instance over a hidden graph. The underlying graph structure is obfuscated within the clause encoding. For each `{name}.wcnf`, produce:

- `/app/solutions/{name}.json` -- `{"vertices": [...], "weight": <int>, "graph": {"num_vertices": N, "edges": [[u,v], ...], "weights": [w0, w1, ...]}}`

The `graph` field must recover the original graph (0-indexed, sorted edges). The vertex cover must be optimal over the recovered graph.

All solutions must be globally optimal.