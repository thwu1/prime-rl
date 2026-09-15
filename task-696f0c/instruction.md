Three undirected graphs are provided as edge-list files in `/app/instances/` (`graph_a.edgelist`, `graph_b.edgelist`, `graph_c.edgelist`). Each file begins with `n_vertices n_edges` on the first line, followed by one `u v` edge per line (0-indexed vertices).

For each graph, determine its exact chromatic number χ(G). Produce machine-verifiable certificates of optimality — both that χ(G) colors suffice and that χ(G)−1 colors do not.

Write results for each graph to `/app/results/<graph_name>/`:

- `chromatic_number.txt` — single integer, the chromatic number
- `coloring.json` — valid proper vertex coloring: `{"<vertex_id>": <color>, ...}` (0-indexed colors)
- `unsat.cnf` — the (χ(G)−1)-coloring problem for this graph as a refutable formula
- `proof.drat` — refutation certificate for `unsat.cnf`
- `proof_verified.txt` — must contain the string `VERIFIED` after independent verification of the refutation