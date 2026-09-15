A production Linux router running an HTB qdisc hierarchy is experiencing multiple service-level violations. Three distinct complaints have been filed:

1. VoIP calls are suffering unacceptable packet loss, even though bandwidth is reserved for voice traffic in the QoS design.
2. Web application throughput never exceeds 15 Mbps, even during off-peak periods when significant spare bandwidth is available in the hierarchy.
3. Bulk file transfers are far slower than expected, while lower-priority scavenger traffic appears to consume a disproportionate share of bandwidth.

Diagnostic captures are available in `/app/`:

- `/app/captures/` — 20 snapshots of raw `tc -s class show dev eth0` output taken at 5-second intervals
- `/app/filters.txt` — Raw `tc -s filter show dev eth0` output showing u32 classification rules with per-rule hit statistics
- `/app/flows.csv` — Network flow records: flow_id, src_ip, dst_ip, src_port, dst_port, proto, dscp, bytes_sent, packets_sent, expected_class
- `/app/sla.json` — Per-class bandwidth SLAs
- `/app/hierarchy.json` — The intended (design-spec) class hierarchy with correct rate/ceil parameters

Identify the root cause of each reported issue and produce:

1. `/app/diagnosis.json` — JSON with an `"issues"` array. Each element must have `"affected_class"` (the tc class ID) and `"root_cause"` (a technical explanation of the misconfiguration found). Include supporting evidence such as affected flow IDs where relevant.

2. `/app/fix.sh` — An executable shell script containing `tc` commands that remediate each issue in-place, without tearing down and rebuilding the entire qdisc tree.