A directed flow network specification is provided at `/app/network_data.json`. Each test case defines a directed graph with 0-indexed nodes, a source, a sink, directed edges with integer capacities and per-unit costs, and **node capacity constraints** limiting total throughput at specified internal nodes.

For each test case, determine:
- The maximum total flow achievable from source to sink
- Among all solutions achieving that maximum flow, the assignment with minimum total cost
- The per-edge flow values for that optimal solution

All constraints — edge capacities, node capacities, and flow conservation — must be satisfied simultaneously.

Solutions must be computed using the GLPK solver (`glpsol`, installed at `/usr/bin/glpsol`). All `.mod` and `.sol` files must be preserved under `/app/lp_artifacts/`. For each test case named `<name>`, there must be at least one `.mod` file and at least one `.sol` file whose filename starts with `<name>`.

Write results to `/app/results.json`:

```json
{
  "test_cases": [
    {
      "name": "<test case name from input>",
      "max_flow": <integer>,
      "min_cost": <integer>,
      "edge_flows": {"<u>,<v>": <integer flow>, ...}
    }
  ]
}
```

The `edge_flows` dictionary maps `"u,v"` string keys (using original node numbering) to their integer flow values. Include only edges carrying positive flow.