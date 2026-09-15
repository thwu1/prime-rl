The `/app/data/` directory contains instances and candidate solutions for four combinatorial optimization problem classes from the QOBLIB (Quantum Optimization Benchmark Library):

- `market_split/` — Constraint-satisfaction instance, candidate solutions in varying encodings, and a Rust reference solution checker (Cargo project)
- `independent_set/` — Graph instance and candidate node subsets
- `cvrp/` — Capacitated Vehicle Routing Problem instance and candidate route sets
- `topology/verify/` — Graph topology specification and candidate graphs
- `topology/construct/` — Specification for constructing a new feasible graph

Produce the following artifacts:

**`/app/results.json`** conforming to the schema at `/app/schema.json`. The report must contain, for each problem class, parsed instance characteristics, per-candidate feasibility verdicts with supporting metrics, and for Market Split specifically: cross-validation against the compiled Rust reference checker's exit codes, plus the upper-triangular QUBO (Quadratic Unconstrained Binary Optimization) matrix properties and per-candidate QUBO objectives derived from the standard penalty-method reformulation of the constraint system. A feasible binary solution has QUBO objective zero; infeasible solutions have a positive objective equal to the sum of squared constraint violations.

**`/app/solutions/topo_25_3.gph`** — A connected graph in DIMACS edge format (`p edge <n> <m>` header followed by `e <u> <v>` lines, 1-indexed node IDs) satisfying the construction specification in `/app/data/topology/construct/instance.dat` with diameter at most 10.

## Feasibility Definitions

**Market Split**: Binary solution vector x satisfies Ax = b for every constraint row.

**Maximum Independent Set**: No two nodes in the proposed subset are adjacent in the instance graph.

**CVRP**: Every customer appears in exactly one route and no route exceeds vehicle capacity. `total_cost` is the sum of all EUC_2D route distances (depot to first customer, consecutive stops, last customer back to depot) using `nint(sqrt(dx² + dy²))` rounding. `max_route_load` is the highest total demand among all routes.

**Topology**: Graph has exactly the required node count, maximum degree within specification, and is connected. Diameter is the longest shortest-path distance between any pair of nodes (-1 if disconnected).