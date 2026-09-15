`/app/solvers/mcmf.py` is a buggy Python Min-Cost Max-Flow solver. `/app/solvers/mcmf.cpp` is a C++ MCMF solver that needs to be compiled using the Makefile in `/app/solvers/` (which also contains errors). The full problem specification is in `/app/problem.md`.

Three logistics network instances are in `/app/instances/`. For each instance, a proposed routing solution has been submitted in `/app/proposed/<instance_name>.json` as a list of edge flows. Your job is to build a working solver pipeline and evaluate whether each proposed solution is feasible and optimal.

**Required deliverables:**

1. A working Python MCMF solver (fix all bugs in `/app/solvers/mcmf.py`)
2. A compiled C++ MCMF binary at `/app/solvers/mcmf` (fix the Makefile and compile successfully)
3. `/app/instance_summary.json` — use `jq` to extract from each instance file a JSON array of objects with fields: `name`, `num_sources`, `num_sinks`, `num_hubs`, `num_edges`, `total_supply`, `total_demand`
4. `/app/results/<instance_name>.txt` — optimal solution for each instance as `<max_flow> <min_cost>` on a single line
5. `/app/evaluations/<instance_name>.json` — evaluation verdict for each proposed solution containing: `instance` (str), `feasible` (bool), `optimal_flow` (int), `optimal_cost` (int), `proposed_flow` (int), `proposed_cost` (int), `is_optimal` (bool), `cost_gap` (int — proposed cost minus optimal cost, or 0 if infeasible)
6. `/app/results.db` — SQLite database populated per the schema in `/app/schema.sql`

The C++ solver reads from stdin: first line `n m s t` (node count, edge count, source, sink), then `m` lines of `u v cap cost`. It writes `flow cost` to stdout.

Feasibility of a proposed solution requires: all edge flows within capacity, source outflows not exceeding supply, sink inflows not exceeding demand, and hub throughput (total flow entering a hub) not exceeding hub capacity.