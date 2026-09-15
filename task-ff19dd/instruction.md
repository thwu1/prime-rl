Five combinatorial optimization benchmark instances in TSPLIB95 format reside in `/app/instances/`:

| File | Problem Type | Nodes | Edge Weight Type | Format | Known Optimum |
|------|-------------|-------|------------------|--------|---------------|
| `berlin52.tsp` | Symmetric TSP | 52 | EUC_2D | coordinates | 7542 |
| `att48.tsp` | Symmetric TSP | 48 | ATT | coordinates | 10628 |
| `br17.atsp` | Asymmetric TSP | 17 | EXPLICIT | FULL_MATRIX | 39 |
| `eil22.vrp` | CVRP | 22 | EUC_2D | coordinates | — |
| `eil13.vrp` | CVRP | 13 | EXPLICIT | LOWER_COL | — |

Produce `/app/results.json` mapping each instance name (without file extension) to its solution.

**TSP / ATSP entries** must contain:
- `"tour"`: 1-indexed cities in visit order, each city appearing exactly once
- `"tour_length"`: integer total distance of the complete round-trip (including the return edge from the last city back to the first)

**CVRP entries** must contain:
- `"routes"`: list of vehicle routes, each a 1-indexed node sequence starting and ending at the depot
- `"total_distance"`: integer sum of all route edge distances

**Quality requirements:**
- `berlin52` and `att48`: tour length ≤ 105% of the known optimum
- `br17`: tour length must equal exactly 39
- `eil22` and `eil13`: every non-depot customer served exactly once across all routes; no single route's total demand may exceed the instance's stated vehicle capacity; reported `total_distance` must match actual computed route distances

All edge distances must conform to the TSPLIB95 specification's integer rounding conventions for each respective edge weight type.