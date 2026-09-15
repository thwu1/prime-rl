An FRRouting configuration dump at `/app/network_dump.conf` defines a 14-router single-area OSPF network with point-to-point /30 links. Analyze this network from R1's perspective to assess its IP fast-reroute readiness and resilience to individual link failures. Write all outputs to `/app/results/`.

## Required Outputs

### `ospf_rib.db` — SQLite routing database

Create with these exact tables:
- `routers(name TEXT PRIMARY KEY, router_id TEXT, loopback TEXT)`
- `links(router_a TEXT, router_b TEXT, cost INTEGER, subnet TEXT, PRIMARY KEY(router_a, router_b))` — one row per undirected link; router names in lexicographic order
- `spf_results(destination TEXT, distance INTEGER, next_hop TEXT, PRIMARY KEY(destination, next_hop))`
- `lfa_results(destination TEXT, next_hop TEXT, lfa_neighbor TEXT, protection_type TEXT, PRIMARY KEY(destination, next_hop))` — lfa_neighbor is NULL when no LFA exists

### `spf.json` — Shortest paths from R1

`{"<dest>": {"distance": <int>, "next_hops": ["<router>", ...]}, ...}` — include equal-cost multipaths; next-hops sorted alphabetically.

### `lfa.json` — Loop-free alternate analysis from R1

`{"<dest>": {"<nh>": {"lfa": "<neighbor_or_null>", "type": "node|link|none"}, ...}, ...}`

For each (destination, primary next-hop) pair, identify the best loop-free alternate among R1's directly connected neighbors (excluding the primary next-hop itself). Report the protection type achieved: `"node"`, `"link"`, or `"none"`. Report `null`/`"none"` when no qualifying alternate exists.

Tiebreaking when multiple alternates qualify at the same protection level: prefer node-protecting over link-protecting; among equal protection type, prefer shortest distance to destination; final tiebreak alphabetically by neighbor name.

### `coverage.json` — Protection coverage summary

```json
{"total_destinations": <int>, "fully_protected": <int>, "partially_protected": <int>, "unprotected": <int>, "unprotected_list": [...], "partially_protected_list": [...]}
```

Classification per destination:
- **fully_protected**: every next-hop has a node-protecting alternate (link-protecting counts as full when destination equals the next-hop)
- **partially_protected**: every next-hop has at least a link-protecting alternate, but not all qualify as fully protected
- **unprotected**: at least one next-hop has no alternate at all

Lists sorted alphabetically.

### `sensitivity.json` — Link-failure impact analysis

For each link in the network, determine the impact on reachability and protection coverage from R1 if that link were removed.

```json
{
  "<RA>-<RB>": {
    "unreachable": ["<router>", ...],
    "coverage": {"total_destinations": <int>, "fully_protected": <int>, "partially_protected": <int>, "unprotected": <int>}
  }, ...
}
```

Link keys: router names in lexicographic order, hyphen-separated. `unreachable`: destinations no longer reachable from R1 after removal. `coverage`: protection coverage over remaining reachable destinations only. Lists sorted alphabetically.

### `topology.svg` — Network topology diagram

Render all 14 routers and links with OSPF cost labels on edges. R1 must have a visually distinct fill color.