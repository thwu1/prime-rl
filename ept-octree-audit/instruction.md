An EPT (Entwine Point Tile) dataset at `/app/dataset/` was built from a USGS 3DEP lidar acquisition covering a small area in UTM Zone 15N (NAD83(2011) / NAVD88). The data tiles in `ept-data/` are LAS 1.4 Point Data Record Format 6 binary files, each carrying an extra `PointId` dimension. The EPT metadata (`ept.json`, `ept-hierarchy/`) indexes these tiles.

The dataset contains multiple specification violations spanning the EPT format, the ASPRS LAS 1.4 standard, and the USGS Lidar Base Specification 2023 Rev A. Errors exist in both the EPT metadata and the point data within the LAS tiles. You must identify every violation and produce a fully corrected dataset.

The environment provides python3 and pip. The data tiles are binary and require an appropriate library to parse.

Produce:

1. `/app/audit_report.json` — JSON object with key `"errors"`: an array of objects, each with `"type"` (snake_case identifier), `"description"` (human-readable), and `"details"` (supporting evidence).
2. `/app/remediation.json` — A valid PDAL pipeline JSON that addresses point-level data corrections (classification, flags, return numbers). Must include at least one reader stage, appropriate filter stages, and a writer stage.
3. `/app/dataset_fixed/` — Corrected copy of the full EPT dataset with all errors resolved. Data tiles must remain in LAS 1.4 PDRF 6 format with the `PointId` extra dimension. All original points must be preserved; only attribute corrections, flag adjustments, spatial reassignment to correct octree nodes, and metadata fixes are permitted.