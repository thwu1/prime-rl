A multi-area OSPF network with 8 routers across 3 areas (Area 0 backbone, Area 1, Area 2) is partially defined in `/app/network/topology.json`. Three link costs are `null` — the actual OSPF metrics for these links must be recovered by decoding the Router LSA packets in `/app/network/ospf_capture.pcap`. External routes redistributed by the ASBR are in `/app/network/external_routes.json`.

The topology includes two ABRs (R1 spanning Areas 0/1, R2 spanning Areas 0/2), a tri-area ABR (R3 spanning Areas 0/1/2), and an ASBR (R4 in Area 0). R4 advertises routes with both E1 and E2 metrics, one with a non-null forwarding address targeting R6's loopback. The pcap also contains OSPF Hello packets with varying timer configurations and DR/BDR election data across different areas.

After recovering the complete topology from the pcap, compute OSPF routing tables for **R7** (Area 2) and **R5** (Area 1) following standard OSPF inter-area routing rules per RFC 2328. Include only loopback /32 destinations and external prefixes. Also perform routing analysis including a link-failure convergence scenario and packet capture analysis.

Write output to:

- `/app/results/routing_table_R7.json`
- `/app/results/routing_table_R5.json`
- `/app/results/analysis.json`

## Output Formats

Each routing table is a JSON array of route entries sorted by destination:

```json
[
  {
    "destination": "10.X.X.X/32",
    "route_type": "intra-area|inter-area|external-type1|external-type2",
    "cost": <int>,
    "next_hop_router": "RX"
  }
]
```

- For `external-type2` routes, include `"forwarding_cost": <int>` (internal cost to ASBR or resolved forwarding address).
- For `external-type1`, `cost` is the total metric (internal cost to ASBR + external metric).
- Use `"self"` as `next_hop_router` for a router's own connected loopback.

`analysis.json` must contain:

```json
{
  "r7_cost_to_10_5_5_5": <int>,
  "r7_next_hop_to_10_5_5_5": "RX",
  "r7_forwarding_cost_172_16": <int>,
  "r7_failover_cost_to_10_5_5_5": <int>,
  "r7_failover_next_hop_to_10_4_4_4": "RX",
  "r7_192_168_2_route_via": "forwarding_address|asbr",
  "e2_tiebreaker_preferred": "<prefix>",
  "pcap_hello_count": <int>,
  "pcap_area0_dr": "<router-id>",
  "pcap_r8_dead_interval": <int>,
  "pcap_r3_area0_lsa_link_count": <int>
}
```

Where:

1. `r7_cost_to_10_5_5_5`: R7's inter-area cost to 10.5.5.5/32
2. `r7_next_hop_to_10_5_5_5`: R7's next-hop router for 10.5.5.5/32
3. `r7_forwarding_cost_172_16`: R7's internal forwarding cost to the ASBR for 172.16.0.0/16
4. `r7_failover_cost_to_10_5_5_5`: R7's cost to 10.5.5.5/32 if the R8–R3 link in Area 2 fails
5. `r7_failover_next_hop_to_10_4_4_4`: R7's next-hop for 10.4.4.4/32 after R8–R3 link failure
6. `r7_192_168_2_route_via`: Whether R7 routes 192.168.2.0/24 via `"forwarding_address"` or `"asbr"`
7. `e2_tiebreaker_preferred`: Between 172.16.0.0/16 and 192.168.2.0/24 (both E2 with equal external metric), which prefix R7 prefers based on the E2 forwarding-cost tiebreaker
8. `pcap_hello_count`: Total number of OSPF Hello packets in the capture file
9. `pcap_area0_dr`: Designated Router ID (as dotted-quad) from Area 0 Hello packets
10. `pcap_r8_dead_interval`: RouterDeadInterval (seconds) from R8's Hello packet in Area 2
11. `pcap_r3_area0_lsa_link_count`: Number of links in R3's Router LSA for Area 0 (including stub networks)