Router `1.1.1.1` participates in a multi-area OSPFv2 network. The backbone area contains four routers interconnected through point-to-point links and a shared broadcast segment with a designated router. Two backbone routers are Area Border Routers providing reachability to non-backbone areas with additional routers and subnets.

Compute the RFC 2328-compliant routing table from `1.1.1.1`'s perspective, covering all reachable intra-area and inter-area destinations. Exclude the computing router's own directly connected networks from the output.

## Data Sources

The OSPF Link-State Database is split across two files:

1. **`/app/ospf.db`** — SQLite database containing the backbone area's Router-LSAs (Type 1) and Network-LSAs (Type 2) in normalized relational tables. Use SQL queries to discover the schema and extract the link-state data.

2. **`/app/summary_lsas.bin`** — Binary file containing Summary-LSAs (Type 3) in a compact encoding. The format specification is in `/app/FORMAT.md`.

The `metadata` table in the database identifies the computing router and backbone area.

## Output

Write the routing table to `/app/results/routing_table.json` as a JSON array:

```json
[{"destination": "x.x.x.x/n", "metric": 10, "route_type": "intra-area", "next_hops": ["10.0.1.2"]}]
```

- `destination`: CIDR notation
- `metric`: total path cost (integer)
- `route_type`: `"intra-area"` or `"inter-area"`
- `next_hops`: list of next-hop IP addresses, sorted ascending

Array entry order does not matter.