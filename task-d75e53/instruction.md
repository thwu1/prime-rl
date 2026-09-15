A 6-router BGP network has been flagged for routing anomalies during a security audit. Network operational data is distributed across multiple backend systems in heterogeneous formats:

- `/data/bgp_monitor.db` — SQLite database containing BGP routing table snapshots
- `/data/network_topology.xml` — Inter-AS topology and relationship metadata (namespaced XML)
- `/data/rpki/validated_roas.json` — RPKI Validated ROA Payloads from the network's RPKI cache
- `/data/configs/bgp_policy.conf` — Cisco IOS-style BGP configuration defining routing policies

Produce a complete anomaly report identifying all instances of:

1. **Route leaks** — routes propagated in violation of inter-AS business relationships
2. **RPKI violations** — routes failing origin validation against the ROA database
3. **Policy violations** — routes with LOCAL_PREF values inconsistent with the configured routing policy

Write JSON results to `/app/output/`:

- `route_leaks.json` — array of objects with at minimum: `prefix`, `leaker_as`, `violation`
- `rpki_violations.json` — array of objects with at minimum: `prefix`, `origin_as`, `violation` (value: `invalid_origin` or `invalid_length`)
- `policy_violations.json` — array of objects with at minimum: `router_as`, `prefix`, `expected_local_pref`, `actual_local_pref`
- `summary.json` — object with keys `total_route_leaks`, `total_rpki_violations`, `total_policy_violations`, `total_issues`