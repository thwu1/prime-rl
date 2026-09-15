# Supply Chain Flow Optimization

## Problem

A logistics company operates a supply chain network consisting of warehouses,
distribution hubs, and retail stores connected by directed transport routes.

- **Warehouses** (sources): Each produces a fixed supply of goods.
- **Retail stores** (sinks): Each has a demand that should be maximally satisfied.
- **Distribution hubs**: Each has a maximum throughput capacity — the total number
  of units passing through the hub cannot exceed this limit.
- **Routes**: Each directed route has a maximum bandwidth (capacity) and a per-unit
  transport cost.

Find the routing that **maximizes total flow** (goods delivered to stores) and,
among all maximum-flow solutions, **minimizes the total transport cost**.

## Input Format

Each instance is a JSON file in `instances/` with the following structure:

```json
{
  "sources": [{"id": "name", "supply": N}, ...],
  "sinks": [{"id": "name", "demand": N}, ...],
  "hubs": [{"id": "name", "capacity": N}, ...],
  "edges": [{"from": "name", "to": "name", "capacity": N, "cost": N}, ...]
}
```

- `sources`: Warehouses that produce goods. Each has a maximum supply.
- `sinks`: Stores that consume goods. Each has a maximum demand.
- `hubs`: Distribution centers with throughput limits. The total flow entering
  and leaving a hub is bounded by its capacity.
- `edges`: Directed transport routes. `from` and `to` reference source, sink,
  or hub IDs.

## Output Format

For each instance `instances/<name>.json`, write a file `results/<name>.txt`
containing a single line with two space-separated integers:

```
<max_flow> <min_cost>
```

where `max_flow` is the maximum total goods delivered and `min_cost` is the
minimum transport cost to achieve that flow.

## Proposed Solutions

For each instance, a proposed routing is provided in `proposed/<name>.json` as
a list of edge flows. Evaluate each proposed solution for feasibility and
optimality, and write the evaluation results.

## Solvers

Two MCMF solvers are provided in `solvers/`:

- `mcmf.py` — Python implementation (may contain bugs)
- `mcmf.cpp` — C++ implementation (needs compilation via Makefile)

## Database Schema

The SQLite schema for storing results is in `schema.sql`.
