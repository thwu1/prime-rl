You are given a wide-area network topology in `/app/topology.json` where each link consists of multiple optical wavelengths that can independently fail. Traffic demands are in `/app/demands.json` and the global availability parameter is in `/app/config.json`.

For each link, the available capacity is a random variable: the sum of capacities of surviving wavelengths. Each wavelength survives independently with probability `(1 - failure_prob)`. The **safe capacity** of a link at availability `α` is the largest value `f` such that `P(available_capacity >= f) >= α`. Since wavelength capacities are heterogeneous, this requires computing the Poisson binomial distribution exactly -- Gaussian approximation is insufficient for the small number of wavelengths per link.

Compute multi-path routing allocations that maximize total throughput. The total flow from all demands on any link (in either direction, as links are undirected with shared capacity) must not exceed that link's safe capacity. Each demand's total routed flow must not exceed its requested volume.

Write your solution to `/app/solution.json` in this format:

```json
{
  "allocations": [
    {
      "demand_id": "d0",
      "paths": [
        {"nodes": ["n0", "n1", "n3", "n7"], "flow": 200.0},
        {"nodes": ["n0", "n5", "n4", "n7"], "flow": 150.0}
      ]
    }
  ]
}
```

Each path must be a valid simple path in the topology graph. All six demands from `/app/demands.json` must appear in the output. The total allocated flow must be at least 85% of the optimal achievable under the chance-constrained multi-commodity flow formulation.