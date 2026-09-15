A six-router enterprise network (AS 65000) has its routing configuration distributed across two heterogeneous data sources that must both be consulted to reconstruct the complete routing state.

## Data Sources

**`/app/network.db`** — SQLite database containing the OSPF topology (link costs, area assignments, IP addressing), BGP session parameters, received BGP route advertisements, iBGP mesh configuration, connected subnets, and administrative distance values. BGP sessions reference route-map names whose definitions exist only in the configuration files below. Use `sqlite3` to explore the schema and extract data.

**`/app/configs/R1.cfg` through `R6.cfg`** — Cisco IOS-format router configuration files. These contain routing policy definitions (route-maps that set BGP path attributes), static routes, and OSPF redistribution configuration with metric and metric-type settings. This policy information is not duplicated in the database.

Both sources must be cross-referenced — the database alone does not contain the local-preference values applied to BGP routes (those are in the route-maps), and the config files alone do not contain the BGP route advertisements or OSPF link topology.

## Required Outputs

Produce four JSON files in `/app/output/`:

**`/app/output/ospf_costs.json`** — Shortest OSPF path cost from every internal router to every other router's loopback address. Format: `{"R1": {"R2": <cost>, ...}, ...}`. The network uses multi-area OSPF with area border routers; inter-area path computation must be handled correctly.

**`/app/output/bgp_best_paths.json`** — For each BGP-speaking router and each prefix in its BGP table, the selected best path after applying standard selection rules. Each entry: `{"selected_via": "ebgp"|"ibgp", "selected_from": "<peer>", "as_path": [<ints>], "local_pref": <int>, "origin": "igp"|"egp"|"incomplete", "med": <int>, "next_hop": "<ip>", "decision_reason": "<criterion>"}`. The `decision_reason` is a concise snake_case label for the tie-breaking criterion that determined the selection (e.g. `"local_pref"` when local preference was decisive, `"only_path"` when no alternatives existed).

**`/app/output/rib.json`** — Per-router Routing Information Base. For each reachable prefix: `{"protocol": "<type>", "admin_distance": <int>, "metric": <int>, "next_hop": "<ip>"|"connected"|"null0"}`. Protocol types: `"connected"`, `"static"`, `"ospf"`, `"ospf_e2"`, `"ebgp"`, `"ibgp"`.

**`/app/output/issues.json`** — Detected routing anomalies where routing policy produces unexpected or suboptimal forwarding behavior. Each entry: `{"type": "<category>", "router": "<name>", "prefix": "<cidr>", "description": "<explanation>"}`.