Build `/app/hydrofabric_tool.py`, a Python CLI analyzing a NOAA-OWP NextGen hydrofabric network. Input data: `/app/hydrofabric.sql` (GeoPackage-compatible SQLite SQL dump), `/app/models.json` (BMI multi-module formulation template). Output schemas for all commands are in `/app/output_schemas.md`.

Six subcommands, all output to stdout. Subcommands accepting a `<nexus_id>` must exit non-zero if the nexus is not found.

**validate** `python3 /app/hydrofabric_tool.py validate /app/hydrofabric.sql`
JSON: `{"is_valid": bool, "violations": [...]}`. Each violation has `type` (string), `feature_id` (string) or `feature_ids` (array), and `message` (non-empty string). Detect four types: `dangling_reference` (flowpath `toid` references non-existent nexus), `orphan_nexus` (nexus with no upstream flowpaths whose `toid` references non-existent divide), `cycle` (bipartite catchment-nexus routing cycle; use `feature_ids`), `missing_divide` (flowpath `divide_id` references non-existent divide). The dataset has intentional errors of all four types.

**drainage** `python3 /app/hydrofabric_tool.py drainage /app/hydrofabric.sql`
JSON object: flowpath id to total accumulated upstream drainage area in sq km (float, 2 decimal places). Each value equals the flowpath's divide `areasqkm` plus the sum of all upstream accumulated areas via bipartite routing. Exclude flowpaths involved in any topology violation.

**subset** `python3 /app/hydrofabric_tool.py subset /app/hydrofabric.sql <nexus_id>`
JSON: `{"flowpaths": [...], "divides": [...], "nexuses": [...]}`. Each array contains complete database records (all columns from the source table) for features upstream of the given nexus, including the nexus itself. Traverse upstream through the bipartite nexus-to-catchment-to-flowpath topology.

**realize** `python3 /app/hydrofabric_tool.py realize /app/hydrofabric.sql <nexus_id> --model-config /app/models.json`
JSON ngen realization config: `{"global": ..., "time": ..., "catchments": {...}}`. `time` is copied from the template. `global` contains `formulations` (preserving module order, all parameters, variable name maps, model params, registration functions, and `{{id}}` placeholders from the template) and `forcing`. `catchments` is keyed by divide id; each has `formulations` with `{{id}}` resolved to that divide id in all `init_config` paths (producing distinct paths per catchment) and its own `forcing` section. Full schema in `/app/output_schemas.md`.

**route-config** `python3 /app/hydrofabric_tool.py route-config /app/hydrofabric.sql <nexus_id>`
YAML t-route config with keys: `supernetwork_parameters`, `segments`, `compute_parameters`, `output_parameters`. `supernetwork_parameters` includes `title`, `geo_file_type`, `terminal_nexus`, and a `columns` alias map. Each segment carries all `flowpath_attributes` table columns plus a resolved `downstream` field (next flowpath within subset via bipartite nexus-to-catchment resolution; empty string at pour point) and `hydroseq`. Segments ordered by `hydroseq` descending. Fixed parameter values specified in `/app/output_schemas.md`.

**graph** `python3 /app/hydrofabric_tool.py graph /app/hydrofabric.sql <nexus_id> --format dot`
Graphviz DOT digraph. Flowpath nodes: `shape=box`. Nexus nodes: `shape=diamond`. Pour-point nexus: `style=bold`. Directed edges: flowpath to its downstream nexus, nexus to its downstream flowpath (within subset only). Terminal nexus has no outgoing edges. Must render with `dot -Tsvg`.
