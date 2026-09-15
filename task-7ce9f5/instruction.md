A sensor network connectivity study stored its graph data across multiple heterogeneous systems under `/opt/graphdata/`. A README file is included but its description of the data is incomplete and partially inaccurate.

Reconstruct the complete undirected graph by discovering and integrating edge data from all sources in `/opt/graphdata/`, resolving format differences, indexing inconsistencies, duplicate entries, and self-loops. Then perform comprehensive structural analysis of the reconstructed graph.

Write your results to `/app/results.json` as a JSON object with these fields:

- `num_nodes` (int): number of unique nodes
- `num_edges` (int): number of unique undirected edges, excluding self-loops
- `triangle_count` (int): total number of triangles
- `max_trussness` (int): largest k for which the k-truss is non-empty
- `trussness_histogram` (object): maps each trussness value (string key) to count of edges with that trussness
- `degeneracy` (int): maximum coreness value across all nodes (the graph's degeneracy)
- `core_histogram` (object): maps each coreness value (string key) to count of nodes with that coreness
- `clique_number` (int): size of the largest maximal clique
- `num_maximal_cliques` (int): number of maximal cliques of size >= 3
- `diameter` (int): length of the longest shortest path (over all connected components)
- `num_articulation_points` (int): number of articulation points (cut vertices)
- `num_bridges` (int): number of bridge edges
- `num_connected_components` (int): number of connected components
- `ktruss_components` (object): for each k from 2 through `max_trussness` (string keys), the number of connected components in the k-truss subgraph
- `densest_subgraph_nodes` (array of int): sorted list of node IDs belonging to edges with maximum trussness

All node IDs in output must be 1-indexed.