A VyOS-style zone-based firewall's nftables configuration is deployed on this system. The security team suspects the ruleset contains misconfigurations allowing unauthorized traffic and has captured diagnostic data during a suspected breach window:

- `/app/trace.log` -- packet trace capture from the firewall
- `/app/conntrack.dump` -- connection tracking state table snapshot
- `/app/policy.yaml` -- the organization's declared inter-zone security policy
- `/app/nft_ruleset.conf` -- the active nftables configuration with rule handle annotations

Create `/app/audit.py` that cross-references all four data sources and writes `/app/audit_report.json` containing:

- `flows`: array of reconstructed packet flows from the trace capture. Each flow object must include: `trace_id`, `protocol`, `src_addr`, `dst_addr`, `src_port` (null for ICMP), `dst_port` (null for ICMP), `ingress_interface`, `egress_interface`, `from_zone`, `to_zone`, `verdict` ("accept"/"drop"), `chain_path` (ordered list of "table/chain" strings), `nat_type` (null/"snat"/"dnat"), `policy_compliant` (boolean)
- `policy_violations`: flows whose observed outcome contradicts the declared policy. Each: `trace_id`, `from_zone`, `to_zone`, `expected_action`, `actual_verdict`
- `stale_rules`: forwarding and NAT chain rules in the nftables configuration that no traced packet ever matched. Each: `handle` (integer), `table`, `chain`
- `conntrack_anomalies`: tracked connections in the conntrack snapshot that have no corresponding trace flow. Each: `protocol`, `src`, `dst`, `sport` (integer), `dport` (integer)
- `summary`: object with integer counts: `total_flows`, `accepted_flows`, `dropped_flows`, `snat_flows`, `dnat_flows`, `policy_violations`, `stale_rules`, `conntrack_anomalies`