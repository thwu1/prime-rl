During USGv6 conformance testing of an IPv6 network protection device, automated monitoring flagged anomalous traffic. Ten packet captures from a passive tap upstream of the device are at `/app/captures/` (`capture_01.pcap` through `capture_10.pcap`). The incident summary is at `/app/incident.md`.

Perform a thorough security analysis of every capture and produce two deliverables:

## 1. `/app/audit.json`

A JSON document conforming to the schema at `/app/schema.json`. Read the schema carefully — it defines the required structure, allowed values, and field semantics for both per-flow analysis and the aggregate summary.

## 2. `/app/rules.nft`

A production-quality nftables ruleset for an IPv6 firewall that mitigates every threat category you identified in the audit while preserving legitimate IPv6 connectivity.