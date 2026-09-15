A 12-router OSPF network topology is stored across multiple data sources:

- `/app/topology.db` — SQLite database with routers, areas, link records, and external route advertisements. Some link records have NULL cost values that must be recovered from elsewhere.
- `/app/router_logs.pcap` — Packet capture of syslog messages (UDP/514) from OSPF routers reporting adjacency state changes. The missing link costs can only be recovered from `OSPF-ADJ` messages with `state=FULL` in this capture. Messages with `state=INIT` contain placeholder costs and must be ignored.
- `/app/raw_queries.xml` — Routing queries in a namespaced XML format (`urn:ietf:params:xml:ns:ospf-routing`), grouped by area, with disabled entries mixed in. Must be transformed using the XSLT stylesheet at `/app/transform.xsl` to produce the usable flat query list.
- `/app/result_schema.json` — JSON schema for output validation.

Reconstruct the complete topology by merging database records with link costs extracted from the packet capture. Compute the correct OSPF routing decision for each enabled query and write results to `/app/results.json` as a JSON array of objects (one per query, preserving transformed document order). Each object must include: `router` (string), `destination` (string), `next_hop` (router ID, e.g. `"R2"`), `cost` (integer), and `route_type`. Include `forward_cost` (integer) where applicable per OSPF external route conventions.

The output must validate against the JSON schema at `/app/result_schema.json`.