A legacy monolith's package dependency enforcement system has accumulated drift between declared enforcement levels and actual dependency constraints. The static dependency graph is stored in a SQLite database at `/app/monolith.db`. The enforcement ratchet policy is documented at `/app/ratchet_policy.yaml`. A CLI tool for querying the graph is available at `/app/bin/depgraph`.

A runtime dependency scan at `/app/runtime_scan.csv` has detected import relationships not captured in the static dependency graph. Several packages were recently promoted to higher enforcement levels as part of a batch migration, but some of those promotions may be invalid given the complete (static + runtime) dependency picture.

Perform a comprehensive audit: reconcile the runtime scan data with the static graph to identify undeclared dependencies, detect packages whose current enforcement level produces violations on the complete graph, determine the highest valid enforcement level for every package, and produce a forward migration plan from the corrected baseline.

Write:

- `/app/output/report.json` -- conforming to the schema at `/app/output_schema.json`
- `/app/output/graph.svg` -- graphviz-rendered dependency graph of the complete (static + runtime) dependency picture, with cycle-participating edges in red and nodes grouped by layer