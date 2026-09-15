A web service cluster (`10.0.1.10`, `10.0.1.11`, `10.0.1.12`) experienced service degradation during a 2-hour monitoring window. Operations captured multi-source telemetry:

- `/app/captures/traffic.pcap` — Packet capture file containing sampled packets from the monitoring period. Packet-level features including TCP flags, window sizes, and TTL values are **only** available here. Use `tshark` to extract and analyze.
- `/app/network.db` — SQLite database with three tables. The `netflow` table has per-flow summaries (id, timestamp, IPs, ports, protocol, packet/byte counts, duration) but **does not include TCP flags**. The `server_stats` table has per-minute server health metrics. The `fw_events` table has firewall connection-tracking events. Use `sqlite3` to query.
- `/app/httpd_access.log` — Apache combined-format access logs from the web servers.

Three concurrent attack campaigns were active. You must correlate packet-level data from the pcap with flow records and auxiliary telemetry to classify attack traffic. Correlate pcap packets to flow records by matching 5-tuple (source IP, destination IP, source port, destination port, protocol) and timestamp proximity.

## Required output

Write three JSON files to `/app/output/`:

- `/app/output/syn_flood.json`
- `/app/output/slowloris.json`
- `/app/output/dns_amp.json`

Each file must contain a JSON object with a single `flow_ids` key mapping to a non-empty list of flow ID strings from the `netflow` table:

```json
{"flow_ids": ["f-000123", "f-000456"]}
```

## Acceptance criteria

- **Per-category precision** ≥ 85% and **recall** ≥ 80% for each of the three attack types.
- **Overall precision** across all categories combined ≥ 80%.
- Each flow ID must appear in **at most one** attack category (no cross-category overlap).
- The number of flow IDs predicted per category must not exceed **3 times** the actual attack count for that category.
- All three output files must be present, valid JSON, and contain non-empty `flow_ids` lists of strings.