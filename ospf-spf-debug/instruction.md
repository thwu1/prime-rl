The OSPF SPF route calculator at `/app/ospf_spf.py` implements RFC 2328 Section 16 (Shortest Path First) for multi-area OSPF topologies. It reads a JSON-encoded link-state database (`/app/topology.json`) describing 5 routers across 2 OSPF areas — with transit networks, stub networks, and an AS-external route — and computes a routing table for the root router (1.1.1.1).

The implementation has bugs that cause incorrect routing table output: missing routes, wrong path costs, and incomplete ECMP next-hop sets. Fix all bugs so the routing table matches the correct RFC 2328 SPF computation.

Run `python3 /app/ospf_spf.py /app/topology.json` to see the current (incorrect) output.