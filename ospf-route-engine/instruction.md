A packet capture file at `/app/ospf_capture.pcap` contains OSPF protocol exchanges as observed on the interfaces of router R1 (router ID `1.1.1.1`) in a multi-area OSPF network. The capture includes the complete set of Link State Advertisements that R1 has received and would store in its Link State Database.

Analyze the captured OSPF data to determine the complete IP routing table that R1 would install per the OSPF protocol specification (RFC 2328). The network contains multiple OSPF areas with Area Border Routers and Autonomous System Boundary Routers performing route redistribution.

Write the routing table to `/app/routing_table.json` as a JSON array of objects, each with:
```json
{
  "destination": "<prefix in CIDR notation>",
  "cost": <integer>,
  "route_type": "<intra-area|inter-area|type-1-external|type-2-external>",
  "next_hops": ["<sorted list of next-hop IPs or 'connected'>"]
}
```

Sort the array by network address, then prefix length. For directly connected networks (computing router's own stubs), use `"connected"` as the next-hop.