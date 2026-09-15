Build a BGP route analysis engine at `/app/bgp_analyzer.py` that determines the optimal path for each query stored in the routing database at `/app/bgp_rib.db`.

Route data is distributed across multiple heterogeneous sources that must be integrated:

- **SQLite database** (`/app/bgp_rib.db`): Contains route advertisements, AS-path segments, configuration profile references, and queries across normalized tables. Some routes carry additional attributes encoded as binary BLOBs. The `pcap_routes` table identifies routes whose path attributes must be extracted from the packet capture rather than the database.

- **Packet capture** (`/app/bgp_capture.pcap`): Contains raw BGP UPDATE messages carrying path attributes for routes referenced in `pcap_routes`. You must figure out how to correlate captured messages to database routes.

- **Policy configuration** (`/app/policies/selection.json`): A nested JSON document containing selection profile flags referenced by queries. The `config_profiles` table in the database contains only profile IDs and names; the actual boolean flags live in this file.

Reference documentation at `/app/REFERENCE.md` and `/app/SPEC.md` describes the database schema, binary encoding formats, the required module interface, and the selection algorithm. Explore these files and the data sources thoroughly before implementing.

For each row in the `queries` table, select the best route under the associated config profile and write results to `/app/results.json` as `{"<query_id>": <best_route_id>, ...}`.