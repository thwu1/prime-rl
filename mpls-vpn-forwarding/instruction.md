A service provider backbone network with 7 routers (PE and P roles), IS-IS, LDP, and MPLS L3VPNs serving three customers is described across multiple data sources in `/app/`.

**Data sources:**

- `/app/network.db` -- SQLite database with `routers` and `links` tables containing the IGP topology, IS-IS metrics, and link bandwidths. Query the schema to discover the table structure and foreign key relationships.
- `/app/configs/` -- JunOS-style configuration files for each PE router defining VRF routing instances, route-target import/export policies, and community definitions. Import/export route-targets are specified indirectly through policy-statement and community references that must be cross-referenced.
- `/app/captures/` -- PCAP files (one per router, named `<RouterName>.pcap`) containing MPLS-labeled packets that encode each router's LDP label-to-FEC bindings. Each packet's MPLS label field holds the advertised label value and the inner IP destination holds the FEC address. Use a packet analysis tool to decode these files.
- `/app/vpn_routes.csv` -- BGP VPNv4 route advertisements with VPN labels, route-targets (semicolon-delimited when multiple), originator identifiers, and associated VRFs.
- `/app/queries.json` -- Ten queries to answer, with expected output schemas and essential protocol reference notes.

Analyze all data sources, compute the answers to the 10 queries, and write the results to `/app/results.json` as a JSON object keyed by query id (`"q1"` through `"q10"`). The exact output structure for each query type is specified in the `output_format` and `action_schemas` sections of `/app/queries.json`.