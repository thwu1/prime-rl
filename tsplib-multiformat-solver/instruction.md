`/app/instances/` contains TSPLIB95 benchmark files spanning symmetric TSP, asymmetric TSP, and capacitated vehicle routing problems. At least one instance file has a metadata header that does not accurately describe its data layout — you must detect and work around this to produce correct results.

Write `/app/results.json` with these keys (all integer values, 1-based node indices):

```
{
  "br17_optimal_cost": <provably minimum-cost directed round-trip visiting all 17 cities>,
  "br17_optimal_tour": [<node permutation of an optimal tour>],
  "berlin52_tour_cost": <cost of the tour specified in berlin52.opt.tour>,
  "att48_distance_1_2": <distance between nodes 1 and 2>,
  "att48_distance_2_3": <distance between nodes 2 and 3>,
  "att48_distance_6_7": <distance between nodes 6 and 7>,
  "att48_nn_cost": <greedy nearest-unvisited-city tour cost from node 1; ties broken by lower node index>,
  "eil13_distance_1_2": <distance between nodes 1 and 2>,
  "eil13_distance_1_13": <distance between nodes 1 and 13>,
  "eil13_distance_6_7": <distance between nodes 6 and 7>,
  "eil13_distance_7_8": <distance between nodes 7 and 8>,
  "eil13_min_vehicles": <fewest vehicles serving all customer demands without exceeding capacity>,
  "eil13_tsp_optimal": <minimum-cost round-trip visiting all 13 nodes, ignoring capacity>
}
```

`br17_optimal_tour` is a permutation of [1..17]; the return to the starting city is implicit. All distance computations must conform to the TSPLIB95 specification for the edge weight type declared in each instance file. The environment has `glpsol` (GLPK) and internet access available.