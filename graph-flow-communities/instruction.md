`/app/network.db` is a SQLite database containing a 20-node directed weighted network. The `metadata` table has rows with TEXT key and INTEGER value for `num_nodes`, `source`, and `sink`. The `edges` table has columns `from_node`, `to_node`, `capacity`, and `cost` (all INTEGER). The graph has four densely-connected clusters linked by sparse inter-cluster directed edges, with bidirectional intra-cluster connections and a handful of reverse inter-cluster edges.

Using only Python standard library for algorithm implementation (no networkx, igraph, graph-tool, or scipy graph modules), build an analysis pipeline that combines network flow, community detection, and shortest-path algorithms. Produce three output artifacts:

## `/app/results.json`

```json
{
  "mcmf": {
    "max_flow": <int>,
    "min_cost": <int>,
    "edge_flows": [[from, to, flow], ...]
  },
  "communities": {
    "assignment": {"0": <community_id>, ...},
    "modularity": <float>,
    "num_communities": <int>
  },
  "shortest_paths": [
    {"path": [node_ids...], "cost": <int>},
    ...
  ],
  "cross_community_flow_fraction": <float>,
  "bottleneck_edge": {"from": <int>, "to": <int>, "flow": <int>, "capacity": <int>}
}
```

**mcmf**: Minimum-cost maximum flow from source to sink. `edge_flows` lists every directed edge carrying positive flow as `[from_node, to_node, flow_amount]`. Find the true maximum flow and, among all maximum flows, the one with minimum total cost.

**communities**: Louvain modularity-based community detection on the undirected projection. Treat each directed edge as undirected using capacity as weight; merge parallel edges by summing. Report string-keyed node-to-community mapping, modularity Q, and community count.

**shortest_paths**: The 5 shortest simple paths from source to sink by non-decreasing total edge cost.

**cross_community_flow_fraction**: Flow on inter-community edges divided by total flow across all edges with positive flow.

**bottleneck_edge**: The inter-community edge carrying highest flow in the MCMF solution.

## `/app/flow_graph.dot`

A Graphviz DOT digraph representing the MCMF solution. Each of the 20 nodes must be declared with `label="{id}\nC{community_id}"` and a `fillcolor` attribute that differs per community. Only edges carrying positive MCMF flow appear, each labeled `"{flow}/{capacity}"`. Must render correctly with `dot -Tsvg`.

## `/app/analysis.db`

A SQLite database with tables:
- `community_assignments(node_id INTEGER PRIMARY KEY, community_id INTEGER)` — all 20 node-to-community mappings
- `shortest_paths(rank INTEGER PRIMARY KEY, path TEXT, cost INTEGER)` — the 5 shortest paths ranked 1-5, `path` as comma-separated node IDs (e.g. `"0,2,3,5,7,9,15,17,19"`)
- `edge_flows(from_node INTEGER, to_node INTEGER, flow INTEGER, capacity INTEGER)` — all edges with positive MCMF flow
- `metrics(key TEXT PRIMARY KEY, value REAL)` — entries for `max_flow`, `min_cost`, `modularity`, `num_communities`, `cross_community_flow_fraction`

All three outputs must be mutually consistent.