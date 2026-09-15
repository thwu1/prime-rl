An ASAM OpenDRIVE (v1.4) road network at `/app/network.xodr` was exported from a road design tool but contains multiple structural integrity violations that render it unsuitable for driving simulation. A companion OpenSCENARIO (v1.1) scenario at `/app/scenario.xosc` defines vehicle and object placements referencing specific roads, lanes, and s-coordinates in this network.

Produce two output files:

**`/app/repaired_network.xodr`** -- A corrected version of the road network with all integrity violations resolved. The repaired file must be well-formed OpenDRIVE XML and internally self-consistent per the ASAM OpenDRIVE specification.

**`/app/audit_report.json`** -- A structured JSON audit report containing:

- `"defects"`: array of objects, each documenting a defect found in the original network. Each entry must include `"road_id"` (string, or null for junction-level defects), `"element"` (description of the affected XML element), `"category"` (string classifying the defect type), `"description"` (what is wrong), and `"repair"` (what was changed to fix it).

- `"entity_placements"`: array of objects, one per entity teleport/initial-placement in the scenario file. Each entry must include `"entity"` (entity name from the .xosc), `"road_id"` (string), `"lane_id"` (integer), `"s"` (float), `"valid"` (boolean -- whether this placement resolves to an existing road, a lane present in the correct lane section for that s-coordinate, and an in-range s value in the **repaired** network), and `"reason"` (explanation).