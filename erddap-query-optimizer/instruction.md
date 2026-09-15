Build `/app/fusion_planner.py` that generates ERDDAP REST API execution plans for federated, multi-dataset scientific data requests with automatic unit harmonization, CF-conventions quality variable detection, spatial coverage analysis, and temporal resolution alignment.

## Problem

NOAA ERDDAP servers host heterogeneous scientific datasets across multiple servers: gridded arrays vs. tabular observation records, different longitude conventions (0-360 vs -180/180), different units for the same physical quantity (kelvin vs degree_C for SST), varying spatial resolutions, distinct dimensional structures (some with altitude/depth dimensions, some without), and different spatial extents. Variables may declare associated quality or error fields via CF-conventions `ancillary_variables` attributes.

Your planner must reconcile all these differences by parsing ERDDAP DAS/DDS metadata: infer each dataset's coordinate system and type from its metadata structure, detect unit mismatches across datasets measuring the same quantity by matching CF `standard_name` attributes, automatically discover and include ancillary quality variables declared via the CF `ancillary_variables` attribute, compute spatial coverage overlap fractions between query regions and dataset extents, report temporal resolution alignment across heterogeneous sources, handle antimeridian-crossing coordinate transforms with correct query splitting, and generate valid dataset-specific ERDDAP REST API URLs with proper griddap bracket syntax or tabledap filter syntax.

## Environment

- `/app/metadata/*.das` — ERDDAP DAS metadata per dataset (variable attributes including CF standard_name, units, ancillary_variables; coordinate ranges; time spacing)
- `/app/metadata/*.dds` — ERDDAP DDS metadata per dataset (dimensional structure, variable types, dimension ordering)
- `/app/server_registry.json` — Dataset-to-server base URL mapping (datasets span multiple servers)
- `/app/queries.json` — Federated query specifications with target regions, time windows, and per-dataset variable/resolution requests
- `/app/erddap_api_reference.md` — ERDDAP constraint syntax and CF conventions reference
- `/app/output_schema.json` — Required output format with field semantics and computation rules

## Goal

Process every query in `/app/queries.json` against its specified datasets, producing `/app/output/fusion_plan.json` conforming to `/app/output_schema.json`.

Execute: `cd /app && python3 fusion_planner.py`