A two-stage stochastic capacitated facility location problem instance is provided at `/app/instance.json`. The instance has 8 candidate facility locations, 15 customers, and 8 demand scenarios.

**Stage 1 (here-and-now):** Decide which facilities to open. Each facility has a fixed opening cost and a maximum service capacity.

**Stage 2 (recourse):** After demand is realized for a given scenario, each customer must be assigned to exactly one open facility. The transportation cost for assigning customer `j` to facility `i` equals `unit_transport_cost * euclidean_distance(facility_i, customer_j) * demand_j`. A facility's total assigned demand across all customers must not exceed its capacity.

**Objective:** Minimize total expected cost = sum of fixed opening costs for opened facilities + probability-weighted sum of optimal transportation costs across all scenarios.

Write a solver at `/app/solver.py` that finds the optimal set of facilities to open. Your implementation must NOT construct and solve the full deterministic equivalent (extensive form) as a single monolithic mixed-integer program. Run the solver to produce `/app/solution.json` containing:

```json
{
  "opened_facilities": [<list of 0-indexed facility indices>],
  "objective_value": <float: total expected cost>
}
```

The solution must be feasible for all demand scenarios and within 1% of the true optimum.