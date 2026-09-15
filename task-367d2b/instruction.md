A GeoPackage catalog at `/app/catalog.gpkg` contains 28 geospatial dataset records from a Pacific Northwest environmental monitoring program. An automated ingestion pipeline introduced multiple categories of data corruption; the validation log at `/app/pipeline.log` confirms 9 records are affected but does not identify which records or describe specific issues.

A mission specification at `/app/missions.json` defines a target region and two analysis tasks: a constrained portfolio optimization problem and a multi-dataset efficiency evaluation.

Independently audit the catalog to discover and classify each corruption issue, repair the catalog, and then solve the optimization and evaluation problems.

## Deliverables

- `/app/diagnostic_report.json` — JSON object with:
  - `corrupted_records`: array of objects, each with `dataset_id` (string) and `description` (string explaining the specific corruption type and how it was identified from the data)
  - `total_corrupted`: integer count of corrupted records

- `/app/catalog_fixed.gpkg` — Corrected GeoPackage preserving the original schema (layer `datasets`, same attribute fields). All geometries must be valid EPSG:4326 bounding box rectangles. All temporal ranges must satisfy `temporal_start <= temporal_end`.

- `/app/strategy.json` — JSON object with:
  - `portfolio`: solution to the constrained minimum-cost portfolio optimization defined in `/app/missions.json`
  - `efficiency_analysis`: complete efficiency ranking and per-category best dataset as specified in `/app/missions.json`