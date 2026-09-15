An enterprise network topology at `/app/topology.json` defines 4 routers (R1-R4), 7 hosts across multiple subnets, static routes, interface-level access control lists (ACLs), and source NAT (masquerade) rules.

Build a reachability analysis engine at `/app/engine.py` that loads this topology and determines, for every ordered pair of distinct hosts, whether a packet from source can reach destination. The analysis must model:

- **Routing**: Forwarding tables derived from connected interfaces and static routes. Route selection via longest-prefix match. Connected routes are implicitly generated from each router interface's IP and prefix length.
- **ACLs**: Per-interface inbound ACLs evaluated in ascending rule-ID order (first match wins). Implicit permit if no rule matches.
- **Source NAT**: Masquerade applied on the specified egress interface when the source IP matches the configured prefix.
- **Hop-by-hop forwarding**: Packets traverse routers sequentially. At each router: check ingress ACL, determine egress interface via routing, apply egress NAT, forward to next hop. If two hosts share the same subnet (same gateway and network), delivery is direct.

The topology contains exactly **2 misconfigurations** that cause unexpected unreachability. Detect them programmatically by analyzing the routing tables and ACL rule sets.

Write results to `/app/report.json`:
```json
{
  "reachability": [
    {"src": "<ip>", "dst": "<ip>", "reachable": true, "reason": "<explanation>"}
  ],
  "misconfigurations": [
    {"router": "<name>", "type": "<descriptive_type>", "description": "<explanation>"}
  ]
}
```

The `reachability` array must contain one entry for every ordered pair of distinct hosts (42 entries for 7 hosts). The `misconfigurations` array must contain exactly 2 entries.

Run via `python3 /app/engine.py`. Standard library only.