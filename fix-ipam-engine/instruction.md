A multi-VRF enterprise network with dual-stack IPv4/IPv6 prefix hierarchies is defined in `/data/network_state.json`. An IPAM library at `/data/ipam/` provides VRF, Prefix, and IPAddress models along with a hierarchy engine.

A datacenter expansion project requires allocating new subnets across multiple VRFs. The requirements are specified in `/data/expansion.json` — each request defines a target VRF, parent container prefix, number and length of subnets needed, and optional constraints including contiguous block allocation, address range exclusion zones, and pool designation.

Implement `/app/allocator.py` that reads the network state and expansion requirements, computes valid subnet placements for all seven requests, and writes the result to `/app/allocation_plan.json`.

Output format — a JSON object with an `allocations` key mapping each request ID (e.g. `REQ-001`) to a list of allocation objects. Each allocation object must include at minimum: `prefix` (CIDR notation), `vrf` (VRF name), `site`, and `is_pool` (boolean).

Correctness requirements:
- Allocated prefixes must occupy currently available address space within their designated parent container in the specified VRF
- VRF isolation must be maintained — identical CIDR ranges in different VRFs are fully independent address spaces
- All prefixes must be properly CIDR-aligned (canonical network address)
- Requests marked contiguous must yield prefixes that merge into a single CIDR-aligned supernet
- Address range exclusion zones specified in requirements must be avoided
- When multiple valid placements exist, prefer lower addresses (first-fit-lowest)
- Requests are processed in order; earlier allocations consume space visible to later requests