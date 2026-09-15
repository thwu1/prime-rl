A datacenter fabric topology is at `/app/topology.dot` (Graphviz DOT, edges have `id` and `capacity` Mbps attributes). Traffic flow definitions are at `/app/flows.csv` (columns: `flow_id`, `path` as colon-separated link IDs, `weight`). The CSIG congestion signaling protocol is described at `/app/csig_protocol.md`.

The topology has 7 links (4 bottleneck + 3 high-capacity connectors) with 10 weighted flows. Flows traverse connector links to reach their bottleneck links, and the progressive filling order across the 4 bottleneck groups is non-trivial.

Build two general-purpose tools that work with any valid DOT topology and CSV flow definition conforming to these formats:

**`/app/simulate.sh`** — CSIG-AIMD iterative congestion control simulator per the protocol spec. Runs the simulation and computes time-averaged per-flow sending rates.

**`/app/analyze.sh`** — Weighted max-min fair rate solver using the progressive filling algorithm. Iteratively identifies the link with the minimum per-weight fair share among all remaining (unsettled) flows, fixes rates of every flow traversing that link at the weighted share, subtracts consumed bandwidth from all other links those flows also traverse, and repeats until all flows are assigned.

Running both tools must produce the following files in `/app/output/`:

- `simulation_rates.json` — per-flow time-averaged sending rates from CSIG-AIMD (keyed by flow_id, values in Mbps)
- `analytical_rates.json` — per-flow exact fair rates from progressive filling (same format)
- `link_utilization.json` — per-link utilization ratio at the final simulation round (keyed by link_id)
- `summary.json` — containing `bottleneck_links` (flow_id→link_id mapping from progressive filling), `filling_order` (list of `[link_id, per_weight_fair_rate]` entries in bottleneck saturation order), `total_rounds` (int), `converged` (bool)
- `comparison.json` — list of per-flow objects with `flow_id`, `simulated`, `analytical`, `relative_error`
- `convergence.dat` — tab-separated simulation convergence data with header row (`round` followed by flow IDs) and sampled rate snapshots
- `convergence.png` — gnuplot-generated plot of per-flow rate evolution over simulation rounds

Run both tools against the provided topology and flows. All JSON must be valid (verifiable with `jq`).