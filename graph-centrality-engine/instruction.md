A directed-graph analytics tool is partially built at `/app/`. It includes a graph loader (`graph.h`, `graph.c`) that reads edge-list files into a Compressed Sparse Row representation storing outgoing edges, a CLI driver (`main.c`), a `Makefile`, and test graphs under `/app/data/`.

The driver references functions declared in a missing `analytics.h` header and calls their implementations from a missing `analytics.c`. Create both files to complete the tool. Read `main.c` for exact function signatures, argument conventions, and output formatting.

The tool must support three commands:

**`bfs <source>`** — For every vertex, output the minimum number of edges on any directed path from the source vertex. Output -1 for vertices not reachable from the source.

**`bc`** — For each vertex v, output its unnormalized betweenness centrality: the sum over all ordered vertex pairs (s, t) with s ≠ v ≠ t of σ\_st(v) / σ\_st, where σ\_st is the total number of shortest directed paths from s to t and σ\_st(v) is the count of those shortest paths that include v as an interior vertex.

**`pagerank <damping> <epsilon> <max_iter>`** — Output the stationary probability distribution of a random walk on the directed graph. At each step, the walker follows a uniformly chosen outgoing edge with probability equal to the damping factor, or jumps to a uniformly random vertex otherwise. A vertex with no outgoing edges distributes its full probability mass uniformly across all vertices. Stop when the sum of absolute per-vertex rank changes between consecutive steps falls below epsilon, or after max\_iter steps.

Build with `make` in `/app/`. The resulting executable must be `/app/graph_analytics`.